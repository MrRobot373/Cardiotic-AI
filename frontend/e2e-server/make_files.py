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
    return out


if __name__ == "__main__":
    print(make())
