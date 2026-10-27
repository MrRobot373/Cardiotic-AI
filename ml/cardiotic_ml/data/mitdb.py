"""MIT-BIH Arrhythmia Database (PhysioNet `mitdb`, ODC-By 1.0).

48 half-hour two-channel recordings, 360 Hz, with cardiologist beat-by-beat annotations.
We use the MLII lead and the AAMI EC57 beat classes, with the inter-patient split of
de Chazal et al. (2004) so that no test patient is ever seen during training.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import wfdb

from cardiotic_ml.paths import MITDB_DIR

FS = 360

ALL_RECORDS = [
    100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 111, 112, 113, 114, 115, 116, 117, 118, 119,
    121, 122, 123, 124, 200, 201, 202, 203, 205, 207, 208, 209, 210, 212, 213, 214, 215, 217, 219,
    220, 221, 222, 223, 228, 230, 231, 232, 233, 234,
]
PACED = {102, 104, 107, 217}  # excluded from beat-classification work, as AAMI recommends

# de Chazal et al., IEEE TBME 2004 — the standard inter-patient split.
DS1 = [101, 106, 108, 109, 112, 114, 115, 116, 118, 119, 122, 124, 201, 203, 205, 207, 208, 209,
       215, 220, 223, 230]
DS2 = [100, 103, 105, 111, 113, 117, 121, 123, 200, 202, 210, 212, 213, 214, 219, 221, 222, 228,
       231, 232, 233, 234]

# MIT-BIH beat symbol -> AAMI class
AAMI_MAP = {
    "N": "N", "L": "N", "R": "N", "e": "N", "j": "N",
    "A": "S", "a": "S", "J": "S", "S": "S",
    "V": "V", "E": "V",
    "F": "F",
    "/": "Q", "f": "Q", "Q": "Q",
}
# Every annotation symbol that marks a QRS complex (used for QRS-detection scoring).
QRS_SYMBOLS = set("NLRBAaJSVrFejnE/fQ?")


@dataclass
class Record:
    record_id: int
    fs: int
    signal: np.ndarray        # MLII lead, millivolts, float32
    ann_samples: np.ndarray   # annotation sample indices
    ann_symbols: np.ndarray   # annotation symbols (str)

    @property
    def qrs_samples(self) -> np.ndarray:
        mask = np.isin(self.ann_symbols, list(QRS_SYMBOLS))
        return self.ann_samples[mask]


def load_record(record_id: int, root: Path = MITDB_DIR, lead: str = "MLII") -> Record:
    path = str(Path(root) / str(record_id))
    rec = wfdb.rdrecord(path)
    names = list(rec.sig_name)
    ch = names.index(lead) if lead in names else 0  # 102 and 104 have no MLII (both paced)
    ann = wfdb.rdann(path, "atr")
    return Record(
        record_id=record_id,
        fs=int(rec.fs),
        signal=rec.p_signal[:, ch].astype(np.float32),
        ann_samples=np.asarray(ann.sample, dtype=np.int64),
        ann_symbols=np.asarray(ann.symbol),
    )


def aami_class(symbol: str) -> str | None:
    return AAMI_MAP.get(symbol)
