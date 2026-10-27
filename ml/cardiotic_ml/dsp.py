"""Signal-processing helpers. Filter *modes* are explicit — never one filter for every task."""

from __future__ import annotations

import numpy as np
from scipy import signal as sps

FILTER_MODES = {
    # Rhythm / QRS work on noisy monitoring data.
    "monitoring": (0.5, 40.0),
    # 12-lead morphology, ST, intervals (IEC 60601-2-25 diagnostic bandwidth).
    "diagnostic": (0.05, 150.0),
}


def bandpass(x: np.ndarray, fs: float, mode: str = "monitoring", order: int = 2) -> np.ndarray:
    lo, hi = FILTER_MODES[mode]
    hi = min(hi, 0.45 * fs)
    sos = sps.butter(order, [lo, hi], btype="bandpass", fs=fs, output="sos")
    return sps.sosfiltfilt(sos, x).astype(np.float32)


def resample(x: np.ndarray, fs_in: float, fs_out: float) -> np.ndarray:
    """Polyphase resampling with anti-aliasing along the last (time) axis, so (leads, samples) works too.
    The original signal is always kept elsewhere."""
    if fs_in == fs_out:
        return x.astype(np.float32)
    from fractions import Fraction

    frac = Fraction(fs_out / fs_in).limit_denominator(1000)
    return sps.resample_poly(x, frac.numerator, frac.denominator, axis=-1).astype(np.float32)
