"""Build the frontend demo dataset: real public ECGs + real Cardiotic AI engine output.

    PYTHONPATH=engine:ml .venv/bin/python frontend/scripts/build_demo_data.py

Writes frontend/public/demo/. Signals come from public research databases (PTB-XL test fold,
Chapman–Shaoxing, MIT-BIH test records), the results from cardiotic-engine. Patient names, record
numbers, doctors and dates are fictitious; the real dataset and record id are kept in `source`.
Ages, sexes and the time between a patient's ECGs are the real ones (PTB-XL keeps them).
"""

from __future__ import annotations

import base64
import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from cardiotic_engine.api import LEADS, Engine
from cardiotic_ml import dsp
from cardiotic_ml.data import chapman, mitdb, ptbxl
from cardiotic_ml.ecg12 import measure

OUT = Path(os.environ.get("DEMO_OUT", Path(__file__).resolve().parents[1] / "public" / "demo"))
NOW = datetime(2026, 10, 27, 9, 30)
FS_VIEW = 250

# Test-fold patients only (the model never trained or was tuned on them).
PTBXL_PATIENTS = [449, 583, 14026, 9740, 18551, 19832, 19654, 18837, 3399, 15592, 16121]
CHAPMAN_PICKS = {"AF": 1, "SVT": 1, "SB": 1, "ST": 1}   # rhythm label -> how many (first in file order)
HOLTERS = [221, 233, 100]

MALE = ["Ramesh Kulkarni", "Arvind Menon", "Vikram Patil", "Suresh Reddy", "Prakash Nair", "Rajiv Kapoor",
        "Manoj Pillai", "Harish Rao", "Sanjay Verma", "Imran Qureshi", "Deepak Joshi", "Anil Bhatt"]
FEMALE = ["Sunita Deshpande", "Meera Iyer", "Kavita Joshi", "Anita Sharma", "Lata Bhosale", "Neha Gupta",
          "Farida Shaikh", "Pooja Mehta", "Rekha Nambiar", "Shalini Das", "Asha Pawar", "Geeta Kulkarni"]
DOCTORS = ["Dr. Ananya Rao", "Dr. Vivek Sharma", "Dr. Priya Nair", "Dr. Karan Mehta"]
LOCATIONS = ["ECG room 1", "ECG room 2", "Cardiology OPD", "Ward 4B", "Emergency", "CCU"]


def _b64(x: np.ndarray) -> str:
    """Signals ship as little-endian int16 µV, base64 — compact and exact enough for display."""
    return base64.b64encode(np.clip(np.round(x * 1000), -32767, 32767).astype("<i2").tobytes()).decode()


def _view(sig500: np.ndarray, fs: float) -> np.ndarray:
    return dsp.resample(dsp.bandpass(sig500, fs, "diagnostic"), fs, FS_VIEW)


def _median(sig: np.ndarray, fs: float) -> dict | None:
    mb = measure.median_beat(sig, fs)
    if mb is None:
        return None
    beat = dsp.resample(mb.beat, fs, FS_VIEW)
    return {"fs": FS_VIEW, "r": int(round(mb.r * FS_VIEW / fs)), "n_beats": mb.n_used,
            "leads": {l: _b64(beat[i]) for i, l in enumerate(LEADS)},
            "r_peaks_s": [round(float(p) / fs, 3) for p in mb.r_peaks], "in_median": [bool(u) for u in mb.used],
            "detection_lead": mb.detect_lead}


def main() -> None:
    eng = Engine()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ecg").mkdir(exist_ok=True)
    (OUT / "holter").mkdir(exist_ok=True)
    meta = {int(float(r["ecg_id"])): r for r in csv.DictReader(open(ptbxl.PTBXL_DIR / "ptbxl_database.csv"))}
    st = ptbxl.statements()
    test = [r for r in ptbxl.split(ptbxl.TEST_FOLDS)]
    patients, ecgs, names_used = [], [], {"m": 0, "f": 0}
    descriptions = {}

    def new_patient(age, sex, origin) -> dict:
        key = "f" if sex == 1 else "m"
        name = (FEMALE if sex == 1 else MALE)[names_used[key] % 12]
        names_used[key] += 1
        p = {"id": f"P{len(patients) + 1:03d}", "name": name, "mrn": f"UH-{20400 + 7 * len(patients)}",
             "age": None if age is None else (90 if age >= 90 else int(age)), "age_90_plus": bool(age and age >= 90),
             "sex": "F" if sex == 1 else "M", "origin": origin}  # PTB-XL codes ages over 89 as 300
        patients.append(p)
        return p

    def add_ecg(p, sig, fs, when, source, device, reference, n):
        res = eng.analyze_ecg12({l: sig[i] for i, l in enumerate(LEADS)}, fs)
        for s in res["result"]["statements"]:
            descriptions[s["statement"]] = st.get(s["statement"].replace("SUPER_", ""), {}).get("description", s["statement"])
        for c in reference:
            descriptions.setdefault(c, st.get(c, {}).get("description", c))
        eid = f"E{len(ecgs) + 1:04d}"
        view = _view(sig, fs)
        detail = {"id": eid, "fs": FS_VIEW, "leads": {l: _b64(view[i]) for i, l in enumerate(LEADS)},
                  "median": _median(sig, fs), "analysis": res}
        (OUT / "ecg" / f"{eid}.json").write_text(json.dumps(detail, default=float))
        r = res["result"]
        ecgs.append({"id": eid, "patient_id": p["id"], "recorded_at": when.isoformat(timespec="minutes"),
                     "location": LOCATIONS[n % len(LOCATIONS)], "ordered_by": DOCTORS[n % len(DOCTORS)],
                     "device": device, "source": source, "reference_statements": reference,
                     "statements": [{k: s[k] for k in ("statement", "probability", "confidence")} for s in r["statements"]],
                     "measurements": {k: v for k, v in r["measurements"].items() if k.endswith(("_ms", "_bpm", "_deg")) or k == "ok"},
                     "unusable_leads": [l for l, q in r["lead_quality"].items() if q == "unusable"],
                     "noisy_leads": [l for l, q in r["lead_quality"].items() if q == "noisy"],
                     "notes": r["notes"] + res["input_notes"]})

    n = 0
    for k, pid in enumerate(PTBXL_PATIENTS):
        recs = sorted([r for r in test if r.patient_id == pid], key=lambda r: meta[r.ecg_id]["recording_date"])
        if not recs:
            continue
        p = new_patient(recs[-1].age, recs[-1].sex, "PTB-XL")
        dates = [datetime.fromisoformat(meta[r.ecg_id]["recording_date"]) for r in recs]
        latest = NOW - timedelta(hours=1 + 2.5 * k)
        for r, d in zip(recs, dates):
            when = latest - (dates[-1] - d)
            add_ecg(p, ptbxl.load_signal(r, hr=True), 500, when,
                    {"dataset": "PTB-XL 1.0.3", "record": r.ecg_id, "licence": "CC BY 4.0", "role": "test fold (never used for training)"},
                    "Schiller AT-6 / CS-12 (PTB-XL)", sorted(c for c, v in r.codes.items()), n)
            n += 1
    crecs = chapman.records()
    for label, count in CHAPMAN_PICKS.items():
        picks = [r for r in crecs if r.rhythm == label][:count]
        for r in picks:
            p = new_patient(r.age, r.sex, "Chapman–Shaoxing")
            add_ecg(p, chapman.load_signal(r.file), 500, NOW - timedelta(minutes=20 + 13 * n),
                    {"dataset": "Chapman–Shaoxing", "record": r.file, "licence": "CC0", "role": "held-out test set"},
                    "GE MUSE (Chapman–Shaoxing)", sorted(r.scp()), n)
            n += 1

    holters = []
    for i, rid in enumerate(HOLTERS):
        rec = mitdb.load_record(rid)
        res = eng.analyze_rhythm(rec.signal, rec.fs, lead="MLII")
        hid = f"H{i + 1:03d}"
        sig = rec.signal.astype(np.float32)
        (OUT / "holter" / f"{hid}.i16").write_bytes(np.clip(np.round(sig * 1000), -32767, 32767).astype("<i2").tobytes())
        ref = [{"t": round(float(s) / rec.fs, 3), "c": mitdb.aami_class(c)} for s, c in zip(rec.ann_samples, rec.ann_symbols)
               if mitdb.aami_class(c) in ("N", "S", "V", "F", "Q")]
        (OUT / "holter" / f"{hid}.json").write_text(json.dumps({"id": hid, "fs": rec.fs, "n_samples": len(sig),
                                                                "analysis": res, "reference_beats": ref}, default=float))
        import wfdb
        age_s, sex_s = wfdb.rdheader(str(mitdb.MITDB_DIR / str(rid))).comments[0].split()[:2]  # e.g. "69 M 1085 1629 x1"
        p = new_patient(float(age_s) if age_s.isdigit() else None, 1 if sex_s == "F" else 0, "MIT-BIH")
        r = res["result"]
        holters.append({"id": hid, "patient_id": p["id"], "recorded_at": (NOW - timedelta(days=1, hours=3 * i)).isoformat(timespec="minutes"),
                        "duration_s": len(sig) / rec.fs, "lead": "MLII", "fs": rec.fs,
                        "source": {"dataset": "MIT-BIH Arrhythmia", "record": rid, "licence": "ODC-By 1.0", "role": "test record (DS2)"},
                        "device": "Holter (MIT-BIH, 1975–79)", "ordered_by": DOCTORS[i % len(DOCTORS)],
                        "findings": r["findings"], "measurements": r["measurements"]})
    catalog = {"generated": NOW.isoformat(timespec="minutes"), "engine": eng.info(), "patients": patients,
               "ecgs": ecgs, "holters": holters, "statement_descriptions": descriptions,
               "disclaimer": "Demo data. Signals from public research databases (PTB-XL CC BY 4.0, Chapman–Shaoxing CC0, "
                             "MIT-BIH ODC-By 1.0); patient names, record numbers, doctors and dates are fictitious. "
                             "AI output is real Cardiotic AI engine output. Research use only — not a medical device."}
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=1, default=float))
    print(len(patients), "patients,", len(ecgs), "ECGs,", len(holters), "Holters")


if __name__ == "__main__":
    main()
