"""MIT-BIH Atrial Fibrillation Database (PhysioNet `afdb`, ODC-By 1.0).

23 long-term Holter recordings (~10 h each) with signals, mostly paroxysmal AF; 250 Hz, two ECG
leads. Rhythm annotations are manual: (AFIB, (AFL, (J (junctional) and (N (all other rhythms).
There are no beat-type labels. Records 00735 and 03665 have no signal files and are not used.

Patient split (fixed before any AFDB result was seen): records ranked by AF burden, then dealt
cyclically into train / val / test, so each split spans low to high AF burden.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import wfdb

from cardiotic_ml.paths import DATA_ROOT

AFDB_DIR = DATA_ROOT / "afdb"
FS = 250
RECORDS = ["04015", "04043", "04048", "04126", "04746", "04908", "04936", "05091", "05121", "05261", "06426",
           "06453", "06995", "07162", "07859", "07879", "07910", "08215", "08219", "08378", "08405", "08434", "08455"]


def rhythm_spans(rid: str) -> tuple[list[tuple[int, int, str]], int]:
    ann = wfdb.rdann(str(AFDB_DIR / rid), "atr")
    n = wfdb.rdheader(str(AFDB_DIR / rid)).sig_len
    marks = [(s, a.strip("\x00")) for s, sym, a in zip(ann.sample, ann.symbol, ann.aux_note) if sym == "+"]
    return [(s, marks[i + 1][0] if i + 1 < len(marks) else n, a) for i, (s, a) in enumerate(marks)], n


def af_burden(rid: str) -> float:
    spans, n = rhythm_spans(rid)
    return sum(e - s for s, e, a in spans if a == "(AFIB") / n


@lru_cache(maxsize=1)
def split() -> dict[str, list[str]]:
    ranked = sorted(RECORDS, key=lambda r: (af_burden(r), r))
    parts = {"train": [], "val": [], "test": []}
    for i, rid in enumerate(ranked):
        parts[("train", "val", "test")[i % 3]].append(rid)
    return parts


def load_signal(rid: str, channel: int = 0) -> np.ndarray:
    rec = wfdb.rdrecord(str(Path(AFDB_DIR) / rid), channels=[channel])
    return np.nan_to_num(rec.p_signal[:, 0]).astype(np.float32)
