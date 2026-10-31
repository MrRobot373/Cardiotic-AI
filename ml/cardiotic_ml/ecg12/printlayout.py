"""The standard printed 12-lead layout: 3 rows x 4 columns of 2.5 s, plus a 10 s lead II rhythm strip.

    I    aVR  V1  V4
    II   aVL  V2  V5
    III  aVF  V3  V6
    II (rhythm, full 10 s)

An ECG read back from paper or a PDF in this layout has each lead only in its own 2.5 s column (lead II has
all 10 s). `mask` reproduces that on a full recording, so a model can be trained and tested on exactly what a
printout contains.
"""

from __future__ import annotations

import numpy as np

LEADS = ("I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6")
GRID = [["I", "AVR", "V1", "V4"], ["II", "AVL", "V2", "V5"], ["III", "AVF", "V3", "V6"]]
COLUMN = {lead: c for row in GRID for c, lead in enumerate(row)}
RHYTHM = "II"


def windows(n: int) -> dict[str, tuple[int, int]]:
    """Sample range each lead has in a printout of n samples (10 s)."""
    seg = n // 4
    return {lead: (0, n) if lead == RHYTHM else (COLUMN[lead] * seg, (COLUMN[lead] + 1) * seg) for lead in LEADS}


def mask(x: np.ndarray, fill: float = 0.0) -> np.ndarray:
    """(..., 12, n) -> same shape with every sample a printout does not show set to `fill`."""
    y = np.full_like(x, fill)
    for i, (a, b) in enumerate(windows(x.shape[-1])[lead] for lead in LEADS):
        y[..., i, a:b] = x[..., i, a:b]
    return y
