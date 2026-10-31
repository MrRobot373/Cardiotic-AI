"""Export the adopted models to ONNX for the Cardiotic AI engine, with a signed-off manifest.

The engine never loads PyTorch weights. Each export is checked: ONNX Runtime and PyTorch must give
the same outputs (max |difference| below EXPORT_TOLERANCE) on random and real-shaped inputs, or the
export fails. The manifest records, per model: file, SHA-256, the source weights' SHA-256, inputs,
labels, calibration temperature, thresholds and the check result.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from cardiotic_ml import __version__
from cardiotic_ml.paths import ARTIFACTS_DIR, REPO_ROOT

ENGINE_MODELS_DIR = REPO_ROOT / "engine" / "cardiotic_engine" / "models"
EXPORT_TOLERANCE = 1e-4
OPSET = 17


def _adopted() -> dict[str, str]:
    from cardiotic_ml import pipeline
    from cardiotic_ml.ecg12 import analyze

    return {"quality": analyze.QUALITY_MODEL, "beats": pipeline.BEAT_MODEL, "rhythm": pipeline.RHYTHM_MODEL,
            "ecg12": analyze.ECG12_MODEL}


def _build(role: str, card: dict) -> tuple[torch.nn.Module, dict[str, tuple[int, ...]]]:
    from cardiotic_ml.beats import dataset as bd
    from cardiotic_ml.beats.model import BeatNet
    from cardiotic_ml.ecg12.model import ECG12Net
    from cardiotic_ml.quality import dataset as qd
    from cardiotic_ml.quality.model import QualityNet
    from cardiotic_ml.rhythm import dataset as rd
    from cardiotic_ml.rhythm.model import RhythmNet

    if role == "quality":
        return QualityNet(len(card["labels"])), {"x": (qd.WIN,)}
    if role == "beats":
        return BeatNet(len(card["labels"])), {"x": (bd.PRE + bd.POST,), "rr": (bd.N_RR,)}
    if role == "ecg12_print":
        return ECG12Net(len(card["labels"]), width=card["recipe"]["width"]), {"x": (12, 1000)}
    if role == "rhythm":
        n_rrf = card.get("n_rrf", rd.N_RRF)
        return RhythmNet(len(card["labels"]), n_rrf=n_rrf), {"x": (rd.WIN,), "rr": (n_rrf,)}
    return ECG12Net(len(card["labels"]), width=card["recipe"]["width"]), {"x": (12, 1000)}


class _FixedAdaptiveAvgPool1d(torch.nn.Module):
    """AdaptiveAvgPool1d for a known input length as a constant averaging matrix (same bins as PyTorch:
    start = floor(i·L/out), end = ceil((i+1)·L/out)). ONNX cannot export uneven adaptive pooling."""

    def __init__(self, length: int, out: int):
        super().__init__()
        w = torch.zeros(length, out)
        for i in range(out):
            a, b = (i * length) // out, -((-(i + 1) * length) // out)
            w[a:b, i] = 1.0 / (b - a)
        self.register_buffer("w", w)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x @ self.w


def _make_exportable(model: torch.nn.Module, inputs: dict[str, tuple[int, ...]]) -> torch.nn.Module:
    """Replace uneven AdaptiveAvgPool1d layers by their fixed-length equivalent (model is unchanged otherwise)."""
    seqs = [m for m in model.modules() if isinstance(m, torch.nn.Sequential)]
    for seq in seqs:
        for i, layer in enumerate(seq):
            if isinstance(layer, torch.nn.AdaptiveAvgPool1d):
                lengths = []
                hook = layer.register_forward_hook(lambda m, inp, out: lengths.append(inp[0].shape[-1]))
                with torch.no_grad():
                    model(*(torch.zeros((1, *s)) for s in inputs.values()))
                hook.remove()
                out = layer.output_size if isinstance(layer.output_size, int) else layer.output_size[0]
                if lengths[0] % out:
                    seq[i] = _FixedAdaptiveAvgPool1d(lengths[0], out)
    return model


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_to_engine(role: str, name: str, out_dir: Path = ENGINE_MODELS_DIR) -> dict:
    """Export one more model into the existing engine manifest without touching the models already there
    (their files and SHA-256 stay byte-identical, so their validation still holds)."""
    manifest = json.loads((out_dir / "manifest.json").read_text())
    entry = _export(role, name, out_dir, np.random.default_rng(0))
    manifest["models"][role] = entry
    manifest["engine_models_version"] = manifest["engine_models_version"] + "+" + role
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return entry


def export_engine(out_dir: Path = ENGINE_MODELS_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    entries = {role: _export(role, name, out_dir, rng) for role, name in _adopted().items()}
    manifest = {"engine_models_version": "2026.10.1", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "exported_by": f"cardiotic-ml {__version__}, torch {torch.__version__}, onnx opset {OPSET}",
                "intended_use": "Research use only. Not a medical device. Not validated for clinical use.",
                "models": entries}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _export(role: str, name: str, out_dir: Path, rng) -> dict:
    import onnxruntime as ort

    if True:
        card = json.loads((ARTIFACTS_DIR / f"{name}.card.json").read_text())
        src = ARTIFACTS_DIR / card["file"]
        assert _sha(src) == card["sha256"], f"{name}: weights do not match their model card"
        model, inputs = _build(role, card)
        model.load_state_dict(torch.load(src, weights_only=True))
        model.eval()
        reference = model
        model = _make_exportable(__import__("copy").deepcopy(model), inputs).eval()
        dummy = tuple(torch.zeros((2, *shape)) for shape in inputs.values())
        path = out_dir / f"{name}.onnx"
        torch.onnx.export(model, dummy, str(path), input_names=list(inputs), output_names=["logits"],
                          dynamic_axes={k: {0: "batch"} for k in [*inputs, "logits"]}, opset_version=OPSET, dynamo=False)
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        worst = 0.0
        for batch in (1, 7, 64):
            arrays = [rng.normal(0, 1, (batch, *shape)).astype(np.float32) for shape in inputs.values()]
            with torch.no_grad():
                ref = reference(*(torch.from_numpy(a) for a in arrays)).numpy()  # the original, unmodified model
            got = sess.run(None, dict(zip(inputs, arrays)))[0]
            worst = max(worst, float(np.abs(ref - got).max()))
        if worst > EXPORT_TOLERANCE:
            raise RuntimeError(f"{name}: ONNX differs from PyTorch by {worst:.2e} (> {EXPORT_TOLERANCE})")
        entry = {"role": role, "name": card["name"], "version": card["version"], "file": path.name, "sha256": _sha(path),
                 "source_weights_sha256": card["sha256"], "inputs": {k: ["batch", *v] for k, v in inputs.items()},
                 "labels": card["labels"], "temperature": card.get("temperature", 1.0), "task": card["task"],
                 "intended_use": card.get("intended_use"), "export_check": {"max_abs_diff_vs_pytorch": worst,
                                                                             "tolerance": EXPORT_TOLERANCE}}
        for k in ("thresholds", "lead_mean", "lead_std", "n_rrf", "recipe"):
            if k in card:
                entry[k] = card[k]
        print(f"{role:8s} {name}: max |ONNX − PyTorch| = {worst:.1e}", flush=True)
        return entry
