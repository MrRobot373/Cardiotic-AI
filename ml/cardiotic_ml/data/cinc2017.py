"""PhysioNet/Computing in Cardiology Challenge 2017 (PhysioNet `challenge-2017`, ODC-By 1.0).

8,528 single-lead ECGs (AliveCor handheld device, lead I-like), 300 Hz, 9–61 s, labelled by
experts as Normal (N), atrial fibrillation (A), other rhythm (O) or too noisy to classify (~).
We use the revised labels (REFERENCE-v3.csv). The dataset publishes no patient IDs, so the
split is stratified by record; that is a known limitation (one patient may have several records).
"""

from __future__ import annotations

import csv
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.io import loadmat

from cardiotic_ml.paths import DATA_ROOT

CINC_DIR = DATA_ROOT / "cinc2017"
FS = 300
LABELS = ["N", "A", "O", "~"]
LABEL_NAMES = {"N": "normal sinus", "A": "atrial fibrillation", "O": "other rhythm", "~": "too noisy"}


def _zip() -> zipfile.ZipFile:
    return zipfile.ZipFile(CINC_DIR / "training2017.zip")


@lru_cache(maxsize=1)
def reference() -> list[tuple[str, str]]:
    with open(CINC_DIR / "REFERENCE-v3.csv") as f:
        return [(r[0], r[1]) for r in csv.reader(f) if r]


def load_all() -> dict[str, np.ndarray]:
    """All signals in millivolts (ADC gain 1000/mV), read straight from the zip."""
    out = {}
    with _zip() as z:
        for name in z.namelist():
            if name.endswith(".mat"):
                with z.open(name) as fh:
                    out[Path(name).stem] = loadmat(fh)["val"][0].astype(np.float32) / 1000.0
    return out


def split(seed: int = 2017) -> dict[str, list[str]]:
    """Stratified 70 / 10 / 20 train / val / test split by record."""
    rng = np.random.default_rng(seed)
    parts = {"train": [], "val": [], "test": []}
    for label in LABELS:
        recs = sorted(r for r, l in reference() if l == label)
        rng.shuffle(recs)
        n = len(recs)
        a, b = int(0.7 * n), int(0.8 * n)
        parts["train"] += recs[:a]; parts["val"] += recs[a:b]; parts["test"] += recs[b:]
    return parts
