"""Sample ECG files for the end-to-end tests: a real PTB-XL ECG written as DICOM and as HL7 aECG, a PDF."""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "tests"))
import ingest_writers as w  # noqa: E402


def make(out: Path = Path(__file__).parent / ".files") -> Path:
    out.mkdir(exist_ok=True)
    ecg = np.load(ROOT / "engine" / "tests" / "fixtures" / "fixtures.npz")["ecg12"]
    (out / "ecg.dcm").write_bytes(w.dicom_file(ecg, 500))
    (out / "ecg-aecg.xml").write_bytes(w.aecg_file(ecg * 0.9, 500))
    (out / "scan.pdf").write_bytes(b"%PDF-1.4 " + b"0" * 200)
    from cardiotic_ml.data import mitdb
    try:  # a 2.5-hour single-lead Holter from five real MIT-BIH records (when the research data is present)
        sig = np.concatenate([mitdb.load_record(r).signal for r in (221, 203, 210, 219, 201)])
        fs = 360
    except Exception:  # without the research data: the fixture ECG's lead II repeated
        sig, fs = np.tile(ecg[1], 900), 500
    import json as _json
    try:
        strip = mitdb.load_record(203).signal[: 360 * 70]
    except Exception:
        strip = np.load(ROOT / "engine" / "tests" / "fixtures" / "fixtures.npz")["strip"]
    (out / "live-strip.json").write_text(_json.dumps([round(float(v), 4) for v in strip]))
    (out / "holter-2h30.edf").write_bytes(w.edf_file(sig[None].repeat(12, 0)[:, : int(len(sig) // fs * fs)], fs, leads=("II",)))
    return out


if __name__ == "__main__":
    print(make())
