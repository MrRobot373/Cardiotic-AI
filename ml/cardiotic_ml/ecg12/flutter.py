"""Atrial-activity features for atrial flutter (signal processing, no learning).

Flutter waves are regular atrial depolarisations at 240-350 /min (4-6 Hz), best seen in II, III, aVF and V1
between the QRS-T complexes. After subtracting each beat's median QRS-T (QRST cancellation), the residual of a
flutter ECG has a sharp spectral peak near 4-6 Hz; fibrillation gives a broader, faster (5-9 Hz) and less
organised spectrum; sinus rhythm leaves little atrial power at all.
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sps

from cardiotic_ml import dsp
from cardiotic_ml.ecg12 import measure

LEADS = ("I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6")
ATRIAL_LEADS = ("II", "AVF", "V1")
NAMES = [f"{lead}_{k}" for lead in ATRIAL_LEADS for k in ("f_dom", "organisation", "atrial_power")] + ["rr_cv", "rate_bpm", "rr_ratio_regular"]


def features(signal: np.ndarray, fs: float) -> np.ndarray | None:
    """(12, n) mV -> feature vector (NAMES order), or None when too few beats are found."""
    x = dsp.bandpass(np.asarray(signal, dtype=np.float32), fs, "diagnostic")
    mb = measure.median_beat(signal, fs)
    if mb is None or len(mb.r_peaks) < 4:
        return None
    L = mb.beat.shape[1]
    resid = x.copy()
    for p in mb.r_peaks:  # QRST cancellation: subtract the median beat at every beat
        a = int(p) - mb.r
        lo, hi = max(0, a), min(x.shape[1], a + L)
        if hi > lo:
            resid[:, lo:hi] -= mb.beat[:, lo - a:hi - a]
    blank = np.zeros(x.shape[1], dtype=bool)  # the QRS itself never cancels perfectly: leave it out
    for p in mb.r_peaks:
        blank[max(0, int(p - 0.05 * fs)):int(p + 0.07 * fs)] = True
    out = []
    for lead in ATRIAL_LEADS:
        r = resid[LEADS.index(lead)].copy()
        r[blank] = 0.0
        r = sps.sosfiltfilt(sps.butter(3, [3, 15], btype="bandpass", fs=fs, output="sos"), r)
        f, pxx = sps.welch(r, fs=fs, nperseg=min(len(r), int(4 * fs)))
        band = (f >= 3) & (f <= 10)
        if not band.any() or pxx[band].sum() <= 0:
            out += [0.0, 0.0, 0.0]
            continue
        k = int(np.argmax(np.where(band, pxx, 0)))
        fd = float(f[k])
        near = np.zeros_like(band)
        for h in (1, 2):  # the peak and its first harmonic
            near |= np.abs(f - h * fd) <= 0.5
        total = pxx[(f >= 3) & (f <= 15)].sum()
        out += [fd, float(pxx[near].sum() / total) if total > 0 else 0.0, float(np.log10(total + 1e-9))]
    rr = np.diff(mb.r_peaks) / fs
    ratio = np.round((60 / rr.mean()) / 75)  # flutter often conducts 2:1 (~150) or 4:1 (~75): rate near a multiple
    return np.array(out + [float(rr.std() / rr.mean()), float(60 / rr.mean()), float(abs((60 / rr.mean()) / 75 - ratio) if ratio > 0 else 1.0)], dtype=np.float32)
