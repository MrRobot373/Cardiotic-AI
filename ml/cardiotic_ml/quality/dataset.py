"""Signal-quality training data: clean MIT-BIH windows + real NSTDB noise and failure modes.

Labels (per 2.5 s window, single lead):
  good      clean, or noise at SNR >= 18 dB
  noisy     noise at 3–12 dB: beats visible, morphology unreliable
  unusable  noise at <= -3 dB, flat line / lead-off, saturation, or noise with no ECG at all

SNR gaps (12–18 dB, -3–3 dB) are left out so the first model learns crisp boundaries. These
labels are a *proxy* built from known noise levels. Clinician-labelled windows from partner
hospitals replace them before any clinical claim (docs/AI_ML_ROADMAP.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


LABELS = ["good", "noisy", "unusable"]
FS = 360
WIN = int(2.5 * FS)  # 900 samples
NOISY_KINDS = ("em", "ma", "bw")


@dataclass
class QualitySet:
    x: np.ndarray        # (n, WIN) float32, millivolts, median-removed
    y: np.ndarray        # (n,) int64
    kind: np.ndarray     # (n,) str — how the example was made (for error analysis)


def clean_windows(record_ids: list[int], step: int = WIN) -> np.ndarray:
    """Non-overlapping windows that contain no MIT-BIH signal-quality ('~') or unreadable marks."""
    from cardiotic_ml.data import mitdb

    out = []
    for rid in record_ids:
        rec = mitdb.load_record(rid)
        bad = rec.ann_samples[np.isin(rec.ann_symbols, ["~", "|", "Q"])]
        for s in range(0, len(rec.signal) - WIN, step):
            if np.any((bad >= s - FS) & (bad < s + WIN + FS)):
                continue
            w = rec.signal[s:s + WIN]
            out.append(w - np.median(w))
    return np.asarray(out, dtype=np.float32)


def _noise_segment(pool: dict[str, np.ndarray], kind: str, rng: np.random.Generator) -> np.ndarray:
    arr = pool[kind]
    ch = rng.integers(arr.shape[0])
    s = rng.integers(arr.shape[1] - WIN)
    seg = arr[ch, s:s + WIN].astype(np.float32)
    return seg - seg.mean()


def _add_noise(clean: np.ndarray, seg: np.ndarray, snr_db: float) -> np.ndarray:
    ps = np.mean(clean ** 2) + 1e-8
    pn = np.mean(seg ** 2) + 1e-8
    return clean + seg * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))


def make_example(clean: np.ndarray, pool: dict[str, np.ndarray], rng: np.random.Generator) -> tuple[np.ndarray, int, str]:
    r = rng.random()
    if r < 0.40:  # good
        if rng.random() < 0.5:
            return clean, 0, "clean"
        kind = NOISY_KINDS[rng.integers(3)]
        return _add_noise(clean, _noise_segment(pool, kind, rng), rng.uniform(18, 30)), 0, f"{kind}@high-snr"
    if r < 0.70:  # noisy
        kind = NOISY_KINDS[rng.integers(3)]
        return _add_noise(clean, _noise_segment(pool, kind, rng), rng.uniform(3, 12)), 1, f"{kind}@mid-snr"
    # unusable
    mode = rng.integers(5)
    if mode == 0:
        kind = ("em", "ma")[rng.integers(2)]
        return _add_noise(clean, _noise_segment(pool, kind, rng), rng.uniform(-12, -3)), 2, f"{kind}@low-snr"
    if mode == 1:  # flat line / lead-off: no cardiac signal, tiny noise, optional offset
        x = rng.normal(0, 0.005, WIN).astype(np.float32) + rng.uniform(-0.2, 0.2)
        return x, 2, "flatline"
    if mode == 2:  # lead falls off mid-window: signal then a step to the rail and flat
        cut = rng.integers(WIN // 5, 4 * WIN // 5)
        x = clean.copy()
        x[cut:] = rng.choice([-1, 1]) * rng.uniform(3, 5)
        return x, 2, "lead-off"
    if mode == 3:  # amplifier saturation: big wander clipped at the rail
        big = _add_noise(clean, _noise_segment(pool, "bw", rng), rng.uniform(-15, -8))
        rail = rng.uniform(0.4, 1.0)
        return np.clip(big, -rail, rail), 2, "saturation"
    seg = _noise_segment(pool, ("em", "ma")[rng.integers(2)], rng)  # noise with no ECG
    return seg / (seg.std() + 1e-8) * rng.uniform(0.1, 0.6), 2, "noise-only"


def preprocess(windows: np.ndarray, lowpass_hz: float | None = None) -> np.ndarray:
    """Raw 2.5 s windows at FS -> model input: optional zero-phase low-pass (from v0.4, 40 Hz: the
    small high-frequency hiss of low-amplitude 12-lead limb leads does not impair reading, and the
    Holter-trained v0.3 rated a fifth of clean PTB-XL leads noisy because of it), then median removed.
    Training and every analysis path use this one function."""
    from scipy import signal as sps

    w = np.asarray(windows, dtype=np.float32).reshape(-1, WIN)
    if lowpass_hz:
        sos = sps.butter(4, lowpass_hz, btype="lowpass", fs=FS, output="sos")
        w = sps.sosfiltfilt(sos, w, axis=-1)
    return (w - np.median(w, axis=-1, keepdims=True)).astype(np.float32)


def build(record_ids: list[int] | None, pool: dict[str, np.ndarray], n: int, seed: int,
          extra_clean: np.ndarray | None = None, extra_p: float = 0.0, low_amp_p: float = 0.0,
          real_noisy: np.ndarray | None = None, real_noisy_p: float = 0.0,
          bases: np.ndarray | None = None, lowpass_hz: float | None = None) -> QualitySet:
    """`extra_clean`: additional clean base windows (e.g. AF / other-rhythm windows from another
    dataset) used with probability `extra_p`; `low_amp_p`: share of base windows scaled down to
    0.3–0.8x so small-amplitude ECGs are not learned as "no signal". `real_noisy`: windows from
    recordings experts labelled too noisy to interpret, used as-is with label "noisy" (weak,
    recording-level labels) with probability `real_noisy_p`. `bases`: clean windows to use instead of
    MIT-BIH records (e.g. 12-lead PTB-XL leads). Every example goes through `preprocess`."""
    rng = np.random.default_rng(seed)
    cleans = bases if bases is not None else clean_windows(record_ids)
    xs, ys, kinds = [], [], []
    for _ in range(n):
        if real_noisy is not None and rng.random() < real_noisy_p:
            xs.append(real_noisy[rng.integers(len(real_noisy))]); ys.append(1); kinds.append("real-noisy")
            continue
        use_extra = extra_clean is not None and rng.random() < extra_p
        base = extra_clean[rng.integers(len(extra_clean))] if use_extra else cleans[rng.integers(len(cleans))]
        low = rng.random() < low_amp_p
        if low:
            base = base * rng.uniform(0.3, 0.8)
        x, y, k = make_example(base, pool, rng)
        xs.append(np.clip(x, -10, 10))  # the recorder's range; clipped again after preprocessing
        ys.append(y)
        kinds.append(("extra:" if use_extra else "") + ("low-amp:" if low else "") + k)
    x = np.clip(preprocess(np.asarray(xs, dtype=np.float32), lowpass_hz), -10, 10)
    return QualitySet(x, np.asarray(ys, dtype=np.int64), np.asarray(kinds))


def raw_windows(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Non-overlapping 2.5 s windows of a signal already at FS: (starts, windows)."""
    starts = np.arange(0, max(len(x) - WIN, -1) + 1, WIN)
    return starts, (np.stack([x[s:s + WIN] for s in starts]) if len(starts) else np.zeros((0, WIN))).astype(np.float32)


def signal_windows(signal: np.ndarray, fs: float, lowpass_hz: float | None = None) -> np.ndarray:
    """Non-overlapping 2.5 s windows at 360 Hz in the model's input format."""
    from cardiotic_ml import dsp

    _, w = raw_windows(dsp.resample(np.asarray(signal, dtype=np.float32), fs, FS))
    return preprocess(w, lowpass_hz)


def lowpass_of(card: dict | None) -> float | None:
    """The input low-pass a quality model was trained with (None for v0.1–v0.3)."""
    return ((card or {}).get("recipe") or {}).get("lowpass_hz")


def noise_pools() -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    from cardiotic_ml.data import noise

    train, test = {}, {}
    for kind in noise.NOISE_TYPES:
        a, b = noise.split_noise(noise.load_noise(kind))
        train[kind], test[kind] = a, b
    return train, test
