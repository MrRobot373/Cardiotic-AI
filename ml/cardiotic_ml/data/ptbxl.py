"""PTB-XL 12-lead ECG database (PhysioNet `ptb-xl` 1.0.3, CC BY 4.0) and PTB-XL+ features (1.0.1, CC BY 4.0).

21,799 ten-second 12-lead ECGs from 18,869 patients, at 100 Hz and 500 Hz, with SCP-ECG statements
assigned by up to two cardiologists. The official `strat_fold` (1–10) keeps each patient in one fold:
folds 1–8 train, 9 validation, 10 test (folds 9 and 10 contain only human-validated reports).

PTB-XL+ adds, for the same ECGs, the measurements made by two commercial-grade algorithms
(GE Marquette 12SL and Uni-G). They are a *reference*, not ground truth: they are used to check
our interval measurements, never as training labels for the statement model.
"""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from cardiotic_ml.paths import DATA_ROOT

PTBXL_DIR = DATA_ROOT / "ptbxl"
PTBXL_PLUS_DIR = DATA_ROOT / "ptbxl_plus"
LEADS = ["I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6"]
SUPERCLASSES = ["NORM", "MI", "STTC", "CD", "HYP"]
TRAIN_FOLDS, VAL_FOLDS, TEST_FOLDS = tuple(range(1, 9)), (9,), (10,)


@dataclass(frozen=True)
class Record:
    ecg_id: int
    patient_id: int
    fold: int
    codes: dict[str, float]      # SCP statement -> likelihood (0–100; 0 = unspecified, as in the release)
    filename_lr: str             # 100 Hz
    filename_hr: str             # 500 Hz
    validated: bool
    age: float | None
    sex: int | None              # 0 male, 1 female (PTB-XL convention)


@lru_cache(maxsize=1)
def records() -> list[Record]:
    out = []
    with open(PTBXL_DIR / "ptbxl_database.csv", newline="") as f:
        for r in csv.DictReader(f):
            out.append(Record(int(float(r["ecg_id"])), int(float(r["patient_id"])), int(r["strat_fold"]),
                              ast.literal_eval(r["scp_codes"]), r["filename_lr"], r["filename_hr"],
                              r["validated_by_human"] == "True",
                              float(r["age"]) if r["age"] else None, int(float(r["sex"])) if r["sex"] else None))
    return out


@lru_cache(maxsize=1)
def statements() -> dict[str, dict]:
    """SCP code -> {description, diagnostic, form, rhythm, diagnostic_class}."""
    out = {}
    with open(PTBXL_DIR / "scp_statements.csv", newline="") as f:
        for r in csv.DictReader(f):
            code = r[""] if "" in r else next(iter(r.values()))
            out[code] = {"description": r["description"], "diagnostic": r["diagnostic"] == "1.0",
                         "form": r["form"] == "1.0", "rhythm": r["rhythm"] == "1.0",
                         "diagnostic_class": r["diagnostic_class"] or None}
    return out


def superclasses(rec: Record) -> set[str]:
    st = statements()
    return {st[c]["diagnostic_class"] for c in rec.codes if c in st and st[c]["diagnostic"] and st[c]["diagnostic_class"]}


def all_statements() -> list[str]:
    """Every SCP statement used in the database (the benchmark's "all" task, 71 statements)."""
    used = {c for r in records() for c in r.codes}
    return sorted(c for c in statements() if c in used)


def split(fold_set: tuple[int, ...]) -> list[Record]:
    return [r for r in records() if r.fold in fold_set]


def load_signal(rec: Record, hr: bool = False) -> np.ndarray:
    """(12, n) float32 in mV, leads in LEADS order; 100 Hz (1000 samples) or 500 Hz (5000)."""
    import wfdb

    sig, fields = wfdb.rdsamp(str(PTBXL_DIR / (rec.filename_hr if hr else rec.filename_lr)))
    assert [n.upper() for n in fields["sig_name"]] == LEADS, fields["sig_name"]
    return np.nan_to_num(sig.T).astype(np.float32)


def load_all_lr(cache: Path | None = None) -> np.ndarray:
    """All 100 Hz signals as (n_records, 12, 1000) float32, cached as float16 (about 0.5 GB)."""
    cache = cache or Path(__file__).resolve().parents[2] / "cache" / "ptbxl_lr_float16.npy"
    if cache.exists():
        return np.load(cache).astype(np.float32)
    x = np.stack([load_signal(r) for r in records()])
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, x.astype(np.float16))
    return x


@lru_cache(maxsize=2)
def reference_measurements(algorithm: str = "12sl") -> dict[int, dict[str, float]]:
    """PTB-XL+ global measurements per ecg_id from one algorithm ("12sl" or "unig")."""
    cols = ["HR__Global", "RR_Mean_Global", "PR_Int_Global", "QRS_Dur_Global", "QT_Int_Global",
            "QT_IntBazett_Global", "QT_IntFridericia_Global", "QRS_AxisFront_Global", "R_AxisFrontal_Global",
            "T_AxisFront_Global", "P_AxisFront_Global"]
    out = {}
    with open(PTBXL_PLUS_DIR / "features" / f"{algorithm}_features.csv", newline="") as f:
        for r in csv.DictReader(f):
            vals = {}
            for c in cols:
                v = r.get(c, "")
                try:
                    vals[c] = float(v)
                except ValueError:
                    pass
            out[int(float(r["ecg_id"]))] = vals
    return out
