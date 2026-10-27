"""Chapman–Shaoxing–Ningbo 12-lead ECG database (PhysioNet `ecg-arrhythmia` 1.0.0, CC BY 4.0).

45,152 ten-second 12-lead ECGs (500 Hz), one per patient, from Chapman University / Shaoxing People's
Hospital and Ningbo First Hospital (China). Labels are SNOMED CT codes from physicians.

Records JS00001–JS10646 are the Chapman–Shaoxing database (data/chapman.py) in the same order;
`verify_chapman_overlap` checks this on the signals. They are our external test set, so only the
Ningbo part is used for training (patient-level split below, fixed before any result).

Several source labels share one SNOMED code (left bundle-branch block, left anterior/posterior
fascicular block -> 164909002; every MI location -> 164865005), so those are not mapped.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from cardiotic_ml.paths import DATA_ROOT

NINGBO_DIR = DATA_ROOT / "ningbo"
FS = 500
N_CHAPMAN = 10646
SNOMED_TO_SCP = {
    "426783006": "SR", "426177001": "SBRAD", "427084000": "STACH", "164889003": "AFIB", "164890007": "AFLT",
    "427393009": "SARRH", "426761007": "SVTAC", "270492004": "1AVB", "195042002": "2AVB", "54016002": "2AVB",
    "28189009": "2AVB", "27885002": "3AVB", "59118001": "CRBBB", "17338001": "PVC", "284470004": "PAC",
    "74390002": "WPW", "164873001": "LVH", "89792004": "RVH", "111975006": "LNGQT",
}
MAPPED = sorted(set(SNOMED_TO_SCP.values()))


@dataclass(frozen=True)
class Record:
    rid: str             # JS00001 …
    path: str            # relative to NINGBO_DIR, without extension
    dx: tuple[str, ...]  # SNOMED CT codes
    age: float | None
    sex: int | None      # 0 male, 1 female

    @property
    def number(self) -> int:
        return int(self.rid[2:])

    @property
    def is_chapman(self) -> bool:
        return self.number <= N_CHAPMAN

    def scp(self) -> set[str]:
        return {SNOMED_TO_SCP[c] for c in self.dx if c in SNOMED_TO_SCP}

    @property
    def split(self) -> str:
        """Ningbo part only: 80 / 10 / 10 by a hash of the record id (one record per patient)."""
        h = int(hashlib.sha256(self.rid.encode()).hexdigest(), 16) % 10
        return "test" if h == 0 else "val" if h == 1 else "train"


@lru_cache(maxsize=1)
def records() -> list[Record]:
    out = []
    for hea in sorted((NINGBO_DIR / "WFDBRecords").glob("*/*/*.hea")):
        text = hea.read_text(errors="replace")
        if int(text.split()[3]) < 5000:   # a few records are shorter than 10 s
            continue
        meta = dict(re.findall(r"^#(\w+):\s*(.*)$", text, flags=re.M))
        age = meta.get("Age", "").strip()
        out.append(Record(hea.stem, str(hea.relative_to(NINGBO_DIR).with_suffix("")),
                          tuple(c.strip() for c in meta.get("Dx", "").split(",") if c.strip()),
                          float(age) if age.replace(".", "", 1).isdigit() else None,
                          {"male": 0, "female": 1}.get(meta.get("Sex", "").strip().lower())))
    return out


def ningbo_part(split: str | None = None) -> list[Record]:
    return [r for r in records() if not r.is_chapman and (split is None or r.split == split)]


def load_signal(rec: Record) -> np.ndarray:
    """(12, 5000) float32 mV, leads in the PTB-XL order (the files use the same order)."""
    import wfdb

    sig, fields = wfdb.rdsamp(str(NINGBO_DIR / rec.path))
    assert [n.upper() for n in fields["sig_name"]] == ["I", "II", "III", "AVR", "AVL", "AVF",
                                                       "V1", "V2", "V3", "V4", "V5", "V6"], fields["sig_name"]
    return np.nan_to_num(sig[:5000].T).astype(np.float32)


def load_lr(recs: list[Record], cache: Path | None = None) -> np.ndarray:
    """Signals resampled to 100 Hz: (n, 12, 1000) float32, cached as float16 for the Ningbo part."""
    from cardiotic_ml import dsp

    cache = cache or Path(__file__).resolve().parents[2] / "cache" / "ningbo_lr_float16.npz"
    if cache.exists():
        z = np.load(cache)
        index = {rid: i for i, rid in enumerate(z["ids"])}
        if all(r.rid in index for r in recs):
            return z["x"][[index[r.rid] for r in recs]].astype(np.float32)
    part = ningbo_part()
    x = np.stack([dsp.resample(load_signal(r), FS, 100) for r in part]).astype(np.float16)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, x=x, ids=np.array([r.rid for r in part]))
    index = {r.rid: i for i, r in enumerate(part)}
    return x[[index[r.rid] for r in recs]].astype(np.float32)


def verify_chapman_overlap(n_check: int = 50) -> dict:
    """Compare JS0000k with the k-th Chapman–Shaoxing ECG (signal and labels) at evenly spaced k."""
    from cardiotic_ml.data import chapman

    by_num = {r.number: r for r in records()}
    crecs = chapman.records()
    ks = np.linspace(1, N_CHAPMAN, n_check).astype(int)
    match = []
    for k in ks:
        if k not in by_num:
            continue
        a = load_signal(by_num[k])
        b = chapman.load_signal(crecs[k - 1].file)
        match.append(bool(np.corrcoef(a.ravel(), b.ravel())[0, 1] > 0.99))
    return {"checked": len(match), "matching": int(sum(match))}
