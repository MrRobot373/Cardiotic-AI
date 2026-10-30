"""PTB-XL technician notes on signal quality, parsed into per-lead flags.

Columns baseline_drift, static_noise, burst_noise, electrodes_problems are free text (German),
e.g. ", I-AVF", "alles", "v1-6", "V5stark!", "mittel". A range follows LEADS order (I-AVF = I, II,
III, aVR, aVL, aVF); "alles"/"alle" means every lead; a bare digit after a V lead is another V
lead ("V5,6"); a note with no lead at all ("mittel", "noisy recording") applies to every lead.
These are weak labels: a lead without a note is not guaranteed clean, and the notes do not grade
severity consistently. They are used to *evaluate* the quality model on real 12-lead ECGs.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache

import numpy as np

from cardiotic_ml.data.ptbxl import LEADS, PTBXL_DIR

COLUMNS = ("baseline_drift", "static_noise", "burst_noise", "electrodes_problems")
_IDX = {name: i for i, name in enumerate(LEADS)}
_ALIAS = {"ALF": "AVF"}


def _lead(tok: str, prev_v: bool) -> int | None:
    t = _ALIAS.get(tok, tok)
    if t in _IDX:
        return _IDX[t]
    if t.isdigit() and prev_v and f"V{t}" in _IDX:
        return _IDX[f"V{t}"]
    if re.fullmatch(r"V[1-6]", t):
        return _IDX[t]
    return None


def parse(text: str) -> np.ndarray:
    """Free-text note -> (12,) bool, True for each lead the note names."""
    out = np.zeros(len(LEADS), dtype=bool)
    if not text or not text.strip():
        return out
    t = text.upper().replace(";", ",").replace(".", ",").replace("&", "")
    words = re.search(r"[A-Z]", t)
    t = re.sub(r"(STARK|MITTEL|LEICHT|STUFE|\?|!)", " ", t)
    if re.search(r"ALLE", t):
        out[:] = True
        return out
    named, prev_v = False, False
    for part in re.split(r"[,\s]+", t):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            ia = _lead(a, prev_v)
            ib = _lead(b if not b.isdigit() else f"V{b}" if a.startswith("V") else b, prev_v)
            if ia is not None and ib is not None and ia <= ib:
                out[ia:ib + 1] = True
                named, prev_v = True, LEADS[ib].startswith("V")
            continue
        i = _lead(part, prev_v)
        if i is not None:
            out[i] = True
            named, prev_v = True, LEADS[i].startswith("V")
    if not named and words:  # a note with no lead ("mittel", "noisy recording")
        out[:] = True
    return out


@lru_cache(maxsize=1)
def lead_flags() -> dict[int, dict[str, np.ndarray]]:
    """ecg_id -> {column: (12,) bool} for every record (all-False when there is no note)."""
    out = {}
    with open(PTBXL_DIR / "ptbxl_database.csv", newline="") as f:
        for r in csv.DictReader(f):
            out[int(float(r["ecg_id"]))] = {c: parse(r[c]) for c in COLUMNS}
    return out


def any_note(ecg_id: int) -> np.ndarray:
    """(12,) bool: the lead is named in any of the four notes."""
    f = lead_flags()[ecg_id]
    return np.any([f[c] for c in COLUMNS], axis=0)
