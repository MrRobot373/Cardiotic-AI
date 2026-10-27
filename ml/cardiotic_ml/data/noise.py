"""MIT-BIH Noise Stress Test Database noise recordings (PhysioNet `nstdb`, ODC-By 1.0).

`bw` baseline wander, `em` electrode motion, `ma` muscle artifact — real noise recorded from
active volunteers with electrodes placed where no ECG is visible. 30 min, 2 channels, 360 Hz.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import wfdb

from cardiotic_ml.paths import NSTDB_DIR

NOISE_TYPES = ("bw", "em", "ma")


def load_noise(kind: str, root: Path = NSTDB_DIR) -> np.ndarray:
    """Both channels concatenated end to end (more distinct noise per split)."""
    rec = wfdb.rdrecord(str(Path(root) / kind))
    return rec.p_signal.T.astype(np.float32)  # shape (2, n)


def split_noise(noise: np.ndarray, train_fraction: float = 0.6) -> tuple[np.ndarray, np.ndarray]:
    """Time-based split: the test portion of each noise recording is never seen in training."""
    cut = int(noise.shape[1] * train_fraction)
    return noise[:, :cut], noise[:, cut:]
