"""Rhythm data (model M3): 30 s single-lead windows -> N / A / O / ~ (CinC 2017 label set).

Waveform: monitoring band-pass, resampled to 150 Hz (AF information — RR irregularity, absent P
waves, f-waves at 4–9 Hz — survives easily), then amplitude-normalised per window.
RR features: computed from the detected beats inside each window. Irregularity of RR intervals is
the single strongest AF marker, so it is given to the model explicitly as well.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cardiotic_ml import dsp, qrs

FS_MODEL = 150
WIN_S = 30
WIN = FS_MODEL * WIN_S       # 4500 samples
STRIDE_S = 15
N_RRF = 10


@dataclass
class RhythmSet:
    x: np.ndarray        # (n, WIN) float32
    rr: np.ndarray       # (n, N_RRF) float32
    y: np.ndarray        # (n,) int64 (-1 when unknown)
    group: np.ndarray    # (n,) record id the window came from (for record-level aggregation)


def rr_window_features(peaks_s: np.ndarray, duration_s: float) -> np.ndarray:
    f = np.zeros(N_RRF, dtype=np.float32)
    if len(peaks_s) < 4:
        f[-1] = 1.0  # "too few beats" flag
        return f
    rr = np.diff(peaks_s)
    d = np.abs(np.diff(rr))
    mean, med = rr.mean(), np.median(rr)
    f[:9] = [
        len(peaks_s) / duration_s,                     # beats per second
        mean, rr.std() / mean,                         # mean RR, coefficient of variation
        np.sqrt(np.mean(np.diff(rr) ** 2)) / mean,     # normalised RMSSD
        np.mean(d > 0.05),                             # pNN50
        np.median(d) / med,                            # median successive change
        (np.percentile(rr, 75) - np.percentile(rr, 25)) / med,
        np.mean(d / rr[:-1] > 0.15),                   # share of >15 % beat-to-beat changes
        rr.min() / med,
    ]
    return np.clip(f, 0, 10)


def prepare(signal: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Band-passed 150 Hz signal and beat times (s) for one recording."""
    peaks = qrs.detect_beats(signal, int(fs))
    x = dsp.resample(dsp.bandpass(signal, fs, "monitoring"), fs, FS_MODEL)
    return x, peaks / fs


def windows(x: np.ndarray, beats_s: np.ndarray, stride_s: float = STRIDE_S) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(waveforms, rr features, start seconds). Short recordings are zero-padded to 30 s."""
    starts = list(range(0, max(len(x) - WIN, 0) + 1, int(stride_s * FS_MODEL))) or [0]
    if len(x) > WIN and (len(x) - WIN) not in starts:
        starts.append(len(x) - WIN)  # cover the tail
    xs, rs = [], []
    for s in starts:
        w = x[s:s + WIN]
        dur = len(w) / FS_MODEL
        w = np.pad(w, (0, WIN - len(w)))
        xs.append(w / (np.std(w[: int(dur * FS_MODEL)]) + 1e-3))
        t0 = s / FS_MODEL
        rs.append(rr_window_features(beats_s[(beats_s >= t0) & (beats_s < t0 + dur)] - t0, dur))
    return np.asarray(xs, dtype=np.float32), np.asarray(rs, dtype=np.float32), np.asarray(starts) / FS_MODEL


def build(signals: dict[str, np.ndarray], labels: dict[str, int], record_ids: list[str], fs: float) -> RhythmSet:
    xs, rs, ys, gs = [], [], [], []
    for rid in record_ids:
        x, beats = prepare(signals[rid], fs)
        w, r, _ = windows(x, beats)
        xs.append(w); rs.append(r); ys += [labels[rid]] * len(w); gs += [rid] * len(w)
    return RhythmSet(np.concatenate(xs), np.concatenate(rs), np.asarray(ys, dtype=np.int64), np.asarray(gs))
