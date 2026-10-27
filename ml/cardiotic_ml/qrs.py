"""QRS (heartbeat) detection and EC57-style beat-by-beat scoring.

Benchmark detectors come from NeuroKit2 (MIT licence). The product detector (Pan-Tompkins) is
implemented here without NeuroKit2 (`pantompkins`), reproducing NeuroKit2 0.2.13's
`pantompkins1985` cleaning and detection exactly (it adapts py-ecg-detectors, GPL-free), so the
engine needs only NumPy and SciPy. A test checks both give identical beats. Scoring follows ANSI/AAMI EC57 conventions as
implemented by PhysioNet's `bxb`: a detection matches a reference beat if it lies within
150 ms, and scoring starts 5 minutes into each record.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy import signal as sps

from cardiotic_ml import dsp

DETECTORS = ("neurokit", "pantompkins1985", "hamilton2002", "elgendi2010")


def pantompkins(x: np.ndarray, fs: int) -> np.ndarray:
    """Pan & Tompkins (1985) QRS detection: 5–15 Hz band-pass, derivative, squaring, 120 ms moving
    window integration, adaptive thresholds with search-back. Returns integration-peak indices."""
    x = np.asarray(x, dtype=np.float64)
    if np.isnan(x).any():
        idx = np.arange(len(x)); ok = ~np.isnan(x)
        x = np.interp(idx, idx[ok], x[ok]) if ok.any() else np.zeros_like(x)
    sos = sps.butter(1, [5, 15], btype="bandpass", output="sos", fs=fs)
    clean = sps.sosfilt(sos, x, zi=sps.sosfilt_zi(sos) * np.mean(x))[0]
    d = np.diff(clean)
    sq = d * d
    n = int(0.12 * fs)
    mwa = ndimage.uniform_filter1d(sq, n, origin=(n - 1) // 2)
    head = min(n - 1, len(sq))
    mwa[:head] = np.cumsum(sq[:head]) / np.linspace(1, head, head)
    mwa[: int(0.2 * fs)] = 0
    return _peakdetect(mwa, fs)


def _peakdetect(det: np.ndarray, fs: int) -> np.ndarray:
    min_dist, min_missed = int(0.3 * fs), int(0.25 * fs)
    out: list[int] = []
    spki = npki = 0.0
    last_peak, last_index = 0, -1
    peaks, _ = sps.find_peaks(det, plateau_size=(1, 1))
    for index, peak in enumerate(peaks):
        v = det[peak]
        th1 = npki + 0.25 * (spki - npki)
        if v > th1 and peak > last_peak + min_dist:
            out.append(peak)
            if len(out) > 9:  # search back for a missed beat after an unusually long RR
                rr_missed = int(1.66 * ((out[-2] - out[-10]) // 8))
                if peak - last_peak > rr_missed:
                    missed = peaks[last_index + 1:index]
                    missed = missed[(missed > last_peak + min_missed) & (missed < peak - min_missed)]
                    missed = missed[det[missed] > 0.5 * th1]
                    if len(missed):
                        out[-1] = missed[np.argmax(det[missed])]
                        out.append(peak)
            last_peak, last_index = peak, index
            spki = 0.125 * v + 0.875 * spki
        else:
            npki = 0.125 * v + 0.875 * npki
    return np.asarray(out, dtype=np.int64)


def detect_qrs(x: np.ndarray, fs: int, method: str = "neurokit") -> np.ndarray:
    """Return R-peak sample indices."""
    if method == "pantompkins1985":
        return pantompkins(x, fs)
    import neurokit2 as nk

    clean_method = method if method in ("neurokit", "pantompkins1985", "hamilton2002", "elgendi2010") else "neurokit"
    cleaned = nk.ecg_clean(x, sampling_rate=fs, method=clean_method)
    _, info = nk.ecg_peaks(cleaned, sampling_rate=fs, method=method, correct_artifacts=False)
    return np.asarray(info["ECG_R_Peaks"], dtype=np.int64)


def refine_peaks(x: np.ndarray, fs: int, peaks: np.ndarray, before_s: float = 0.10, after_s: float = 0.05) -> np.ndarray:
    """Move each detection to the R-peak fiducial: the largest deflection of the band-passed signal
    near it. Pan-Tompkins marks beats ~40 ms late (it works on an integrated signal); the beat
    classifier is trained on R-peak positions, so detections must be aligned before classification."""
    f = dsp.bandpass(x, fs, "monitoring")
    f = f - np.median(f)
    b, a = int(before_s * fs), int(after_s * fs)
    out = [max(0, p - b) + int(np.argmax(np.abs(f[max(0, p - b):min(len(f), p + a + 1)]))) for p in peaks]
    return np.unique(np.asarray(out, dtype=np.int64))


STARTUP_S = 0.4


def detect_beats(x: np.ndarray, fs: int, method: str = "pantompkins1985") -> np.ndarray:
    """Detection (best-benchmarked detector) followed by R-peak refinement. Detections in the first
    0.4 s are dropped: Pan-Tompkins' adaptive thresholds are still settling there and it marks
    false beats (seen on MIT-BIH 221: a detection at 0.32 s, first real beat at 0.61 s)."""
    peaks = refine_peaks(x, fs, detect_qrs(x, fs, method))
    return peaks[peaks >= int(STARTUP_S * fs)]


@dataclass
class MatchResult:
    tp: int
    fn: int
    fp: int

    @property
    def sensitivity(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else float("nan")

    @property
    def ppv(self) -> float:  # "positive predictivity" (+P) in EC57
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else float("nan")

    def __add__(self, other: "MatchResult") -> "MatchResult":
        return MatchResult(self.tp + other.tp, self.fn + other.fn, self.fp + other.fp)


def match_beats(ref: np.ndarray, det: np.ndarray, fs: int, tol_s: float = 0.150,
                start_s: float = 300.0, end_sample: int | None = None) -> MatchResult:
    """One-to-one greedy matching of detections to reference beats within ±tol."""
    ref = np.sort(ref)
    det = np.sort(det)
    lo = int(start_s * fs)
    hi = end_sample if end_sample is not None else max(ref.max(initial=0), det.max(initial=0)) + 1
    ref = ref[(ref >= lo) & (ref < hi)]
    det = det[(det >= lo) & (det < hi)]
    tol = int(round(tol_s * fs))
    used = np.zeros(len(det), dtype=bool)
    tp = 0
    j = 0
    for r in ref:
        while j < len(det) and det[j] < r - tol:
            j += 1
        best, best_d = -1, tol + 1
        k = j
        while k < len(det) and det[k] <= r + tol:
            if not used[k] and abs(det[k] - r) < best_d:
                best, best_d = k, abs(det[k] - r)
            k += 1
        if best >= 0:
            used[best] = True
            tp += 1
    return MatchResult(tp=tp, fn=len(ref) - tp, fp=int((~used).sum()))
