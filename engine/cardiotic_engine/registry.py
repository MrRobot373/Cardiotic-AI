"""Model registry: load the manifest, verify every model file, run models with ONNX Runtime."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

MODELS_DIR = Path(os.environ.get("CARDIOTIC_ENGINE_MODELS", Path(__file__).resolve().parent / "models"))
ROLES = ("quality", "beats", "rhythm", "ecg12")


class IntegrityError(RuntimeError):
    """A model file is missing, altered, or not the version the analysis code expects."""


class OnnxRunner:
    """runner(*arrays) -> logits, single-threaded by default so results are deterministic and the
    engine never takes over a shared hospital server (CARDIOTIC_ENGINE_THREADS to change)."""

    def __init__(self, path: Path, threads: int | None = None):
        import onnxruntime as ort

        ort.disable_telemetry_events()  # on-premise: the runtime sends nothing anywhere
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads or int(os.environ.get("CARDIOTIC_ENGINE_THREADS", "1"))
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.inputs = [i.name for i in self.session.get_inputs()]
        self.n_out = self.session.get_outputs()[0].shape[-1]

    def __call__(self, *arrays: np.ndarray) -> np.ndarray:
        return self.session.run(None, {k: np.asarray(a, dtype=np.float32) for k, a in zip(self.inputs, arrays)})[0]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest(directory: Path = MODELS_DIR) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    missing = [r for r in ROLES if r not in manifest["models"]]
    if missing:
        raise IntegrityError(f"manifest has no model for: {missing}")
    return manifest


def verify(directory: Path = MODELS_DIR) -> dict:
    """Check every model file against its manifest SHA-256, and that the versions are the ones the
    analysis code was validated with. Raises IntegrityError on any mismatch."""
    from cardiotic_ml import pipeline
    from cardiotic_ml.ecg12 import analyze

    manifest = load_manifest(directory)
    expected = {"quality": analyze.QUALITY_MODEL, "beats": pipeline.BEAT_MODEL, "rhythm": pipeline.RHYTHM_MODEL,
                "ecg12": analyze.ECG12_MODEL}
    if pipeline.QUALITY_MODEL != analyze.QUALITY_MODEL:
        raise IntegrityError("single-lead and 12-lead pipelines expect different quality models")
    report = {}
    for role in ROLES:
        m = manifest["models"][role]
        path = directory / m["file"]
        if not path.exists():
            raise IntegrityError(f"{role}: {m['file']} is missing")
        digest = _sha256(path)
        if digest != m["sha256"]:
            raise IntegrityError(f"{role}: {m['file']} has SHA-256 {digest[:12]}…, manifest says {m['sha256'][:12]}…")
        if f"{m['name']}_{m['version']}" != expected[role]:
            raise IntegrityError(f"{role}: manifest has {m['name']}_{m['version']}, analysis code expects {expected[role]}")
        report[role] = {"model": expected[role], "sha256": digest}
    return report
