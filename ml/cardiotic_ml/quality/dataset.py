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


def build(record_ids: list[int], pool: dict[str, np.ndarray], n: int, seed: int,
          extra_clean: np.ndarray | None = None, extra_p: float = 0.0, low_amp_p: float = 0.0,
          real_noisy: np.ndarray | None = None, real_noisy_p: float = 0.0) -> QualitySet:
    """`extra_clean`: additional clean base windows (e.g. AF / other-rhythm windows from another
    dataset) used with probability `extra_p`; `low_amp_p`: share of base windows scaled down to
    0.3–0.8x so small-amplitude ECGs are not learned as "no signal". `real_noisy`: windows from
    recordings experts labelled too noisy to interpret, used as-is with label "noisy" (weak,
    recording-level labels) with probability `real_noisy_p`."""
    rng = np.random.default_rng(seed)
    cleans = clean_windows(record_ids)
    xs, ys, kinds = [], [], []
    for _ in range(n):
        if real_noisy is not None and rng.random() < real_noisy_p:
            xs.append(np.clip(real_noisy[rng.integers(len(real_noisy))], -10, 10)); ys.append(1); kinds.append("real-noisy")
            continue
        use_extra = extra_clean is not None and rng.random() < extra_p
        base = extra_clean[rng.integers(len(extra_clean))] if use_extra else cleans[rng.integers(len(cleans))]
        low = rng.random() < low_amp_p
        if low:
            base = base * rng.uniform(0.3, 0.8)
        x, y, k = make_example(base, pool, rng)
        xs.append(np.clip(x, -10, 10))
        ys.append(y)
        kinds.append(("extra:" if use_extra else "") + ("low-amp:" if low else "") + k)
    return QualitySet(np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.int64), np.asarray(kinds))


def signal_windows(signal: np.ndarray, fs: float) -> np.ndarray:
    """Non-overlapping 2.5 s windows at 360 Hz, median removed — the model's input format."""
    from cardiotic_ml import dsp

    x = dsp.resample(np.asarray(signal, dtype=np.float32), fs, FS)
    starts = range(0, len(x) - WIN + 1, WIN)
    return np.asarray([x[s:s + WIN] - np.median(x[s:s + WIN]) for s in starts], dtype=np.float32).reshape(-1, WIN)


def noise_pools() -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    from cardiotic_ml.data import noise

    train, test = {}, {}
    for kind in noise.NOISE_TYPES:
        a, b = noise.split_noise(noise.load_noise(kind))
        train[kind], test[kind] = a, b
    return train, test
