"""Chapman University – Shaoxing People's Hospital 12-lead ECG database (figshare collection 4560497, CC0).

10,646 ten-second 12-lead ECGs (500 Hz, µV), one per patient, recorded on GE MUSE systems in China
(2013–2018). Each ECG has one rhythm label and zero or more condition labels from physicians, plus the
GE MUSE measurements (ventricular rate, QRS, QT, QTc, axes, QRS onset/offset and T offset).

Used only as an **external test set**: no model, threshold or measurement setting is chosen on it.
The same ECGs are also the first 10,646 records of the Chapman–Shaoxing–Ningbo database
(PhysioNet `ecg-arrhythmia`), so those records must never be used for training.

Label mapping to PTB-XL SCP statements is fixed here before any result was seen. Only labels with
an unambiguous counterpart are mapped. Condition labels are not exhaustive, so specificity on this set
is a lower bound.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from cardiotic_ml.paths import DATA_ROOT

CHAPMAN_DIR = DATA_ROOT / "chapman"
FS = 500
RHYTHM_TO_SCP = {"SR": "SR", "SB": "SBRAD", "ST": "STACH", "AFIB": "AFIB", "AF": "AFLT", "SA": "SARRH", "SI": "SARRH", "SVT": "SVTAC"}
# (the label sheet says "SI" for sinus irregularity; the data use "SA")
CONDITION_TO_SCP = {"1AVB": "1AVB", "2AVB": "2AVB", "3AVB": "3AVB", "LBBB": "CLBBB", "RBBB": "CRBBB", "LFBBB": "LAFB",
                    "LVH": "LVH", "VPB": "PVC", "APB": "PAC", "WPW": "WPW", "QTIE": "LNGQT", "MILW": "IMI", "RVH": "RVH"}
MUSE_TO_OURS = {"VentricularRate": "heart_rate_bpm", "QRSDuration": "qrs_ms", "QTInterval": "qt_ms",
                "QTCorrected": "qtc_bazett_ms", "RAxis": "qrs_axis_deg", "TAxis": "t_axis_deg"}


@dataclass(frozen=True)
class Record:
    file: str
    rhythm: str
    conditions: tuple[str, ...]
    age: float | None
    sex: int | None          # 0 male, 1 female (PTB-XL convention)
    muse: dict[str, float]   # GE MUSE measurements, our key names

    def scp(self) -> set[str]:
        out = {RHYTHM_TO_SCP[self.rhythm]} if self.rhythm in RHYTHM_TO_SCP else set()
        out |= {CONDITION_TO_SCP[c] for c in self.conditions if c in CONDITION_TO_SCP}
        if self.rhythm == "SR" and not self.conditions:
            out.add("NORM")  # sinus rhythm with no other finding: closest to PTB-XL "normal ECG"
        return out


@lru_cache(maxsize=1)
def records() -> list[Record]:
    import openpyxl

    ws = openpyxl.load_workbook(CHAPMAN_DIR / "Diagnostics.xlsx", read_only=True).active
    rows = ws.iter_rows(values_only=True)
    head = next(rows)
    out = []
    for row in rows:
        r = dict(zip(head, row))
        cond = tuple(c for c in str(r["Beat"] or "").split() if c != "NONE")
        out.append(Record(r["FileName"], str(r["Rhythm"]).strip(), cond,
                          float(r["PatientAge"]) if r["PatientAge"] not in (None, "") else None,
                          {"MALE": 0, "FEMALE": 1}.get(str(r["Gender"]).strip().upper()),
                          {ours: float(r[m]) for m, ours in MUSE_TO_OURS.items() if r[m] is not None}))
    return out


def load_signal(file: str, zf: zipfile.ZipFile | None = None) -> np.ndarray:
    """(12, 5000) float32 in mV, leads I, II, III, aVR, aVL, aVF, V1–V6 (the PTB-XL order)."""
    own = zf is None
    zf = zf or zipfile.ZipFile(CHAPMAN_DIR / "ECGData.zip")
    try:
        raw = zf.read(f"ECGData/{file}.csv").decode("utf-8-sig")
    finally:
        if own:
            zf.close()
    x = np.loadtxt(io.StringIO(raw), delimiter=",", skiprows=1, dtype=np.float32)
    return np.nan_to_num(x.T / 1000.0).astype(np.float32)


def load_all(cache: Path | None = None) -> np.ndarray:
    """All signals as (n, 12, 5000) float32 mV in records() order, cached as float16 (~1.3 GB)."""
    cache = cache or Path(__file__).resolve().parents[2] / "cache" / "chapman_float16.npy"
    if cache.exists():
        return np.load(cache).astype(np.float32)
    with zipfile.ZipFile(CHAPMAN_DIR / "ECGData.zip") as zf:
        x = np.stack([load_signal(r.file, zf) for r in records()])
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, x.astype(np.float16))
    return x
