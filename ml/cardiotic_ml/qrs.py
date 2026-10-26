"""QRS (heartbeat) detection and EC57-style beat-by-beat scoring.

Detectors come from NeuroKit2 (MIT licence). Scoring follows ANSI/AAMI EC57 conventions as
implemented by PhysioNet's `bxb`: a detection matches a reference beat if it lies within
150 ms, and scoring starts 5 minutes into each record.
"""

from __future__ import annotations

from dataclasses import dataclass

import neurokit2 as nk
import numpy as np

DETECTORS = ("neurokit", "pantompkins1985", "hamilton2002", "elgendi2010")


def detect_qrs(x: np.ndarray, fs: int, method: str = "neurokit") -> np.ndarray:
    """Return R-peak sample indices."""
    clean_method = method if method in ("neurokit", "pantompkins1985", "hamilton2002", "elgendi2010") else "neurokit"
    cleaned = nk.ecg_clean(x, sampling_rate=fs, method=clean_method)
    _, info = nk.ecg_peaks(cleaned, sampling_rate=fs, method=method, correct_artifacts=False)
    return np.asarray(info["ECG_R_Peaks"], dtype=np.int64)


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
