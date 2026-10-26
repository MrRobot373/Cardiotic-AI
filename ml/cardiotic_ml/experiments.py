"""Reproducible experiments. Each writes a JSON result to ml/reports/ and models to ml/artifacts/."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from cardiotic_ml import __version__, qrs
from cardiotic_ml.beats import dataset as beat_data
from cardiotic_ml.beats.model import BeatNet
from cardiotic_ml.data import mitdb
from cardiotic_ml.paths import ARTIFACTS_DIR, REPORTS_DIR
from cardiotic_ml.quality import dataset as q_data
from cardiotic_ml.quality.model import QualityNet
from cardiotic_ml.train_utils import TrainConfig, class_report, predict, train


def _meta(**extra) -> dict:
    return {
        "cardiotic_ml_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "torch": torch.__version__,
        "python": platform.python_version(),
        "datasets": {"mitdb": "PhysioNet MIT-BIH Arrhythmia Database 1.0.0 (ODC-By 1.0)",
                     "nstdb": "PhysioNet MIT-BIH Noise Stress Test Database 1.0.0 (ODC-By 1.0)"},
        **extra,
    }


def _write(name: str, payload: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=float))
    return path


def _save_model(model: torch.nn.Module, name: str, card: dict) -> dict:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"{name}.pt"
    torch.save(model.state_dict(), path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    card = {**card, "file": path.name, "sha256": digest, "parameters": sum(p.numel() for p in model.parameters())}
    (ARTIFACTS_DIR / f"{name}.card.json").write_text(json.dumps(card, indent=2, default=float))
    return card


# ---------------------------------------------------------------- QRS detection (EC57-style)
def eval_qrs(methods: tuple[str, ...] = qrs.DETECTORS) -> dict:
    per_method = {}
    for method in methods:
        rows, total, total_np = [], qrs.MatchResult(0, 0, 0), qrs.MatchResult(0, 0, 0)
        t0 = time.time()
        for rid in mitdb.ALL_RECORDS:
            rec = mitdb.load_record(rid)
            det = qrs.detect_qrs(rec.signal, rec.fs, method)
            m = qrs.match_beats(rec.qrs_samples, det, rec.fs, end_sample=len(rec.signal))
            rows.append({"record": rid, "tp": m.tp, "fn": m.fn, "fp": m.fp,
                         "sensitivity": m.sensitivity, "ppv": m.ppv})
            total = total + m
            if rid not in mitdb.PACED:
                total_np = total_np + m
        per_method[method] = {
            "all_48": {"tp": total.tp, "fn": total.fn, "fp": total.fp, "sensitivity": total.sensitivity, "ppv": total.ppv},
            "non_paced_44": {"tp": total_np.tp, "fn": total_np.fn, "fp": total_np.fp,
                             "sensitivity": total_np.sensitivity, "ppv": total_np.ppv},
            "per_record": rows,
            "seconds": round(time.time() - t0, 1),
        }
        print(f"{method:16s} Se {total.sensitivity:.4f}  +P {total.ppv:.4f}  (48 records)", flush=True)
    result = _meta(task="qrs_detection", protocol="150 ms match window; scoring from 5:00 to end; MLII lead",
                   methods=per_method)
    _write("qrs_detection", result)
    return result


# ---------------------------------------------------------------- signal quality
def train_quality(n_train: int = 30000, n_val: int = 5000, n_test: int = 10000, epochs: int = 10) -> dict:
    pool_train, pool_test = q_data.noise_pools()
    val_ids = [106, 118, 207, 220]
    train_ids = [r for r in mitdb.DS1 if r not in val_ids]
    print("building quality datasets…", flush=True)
    tr = q_data.build(train_ids, pool_train, n_train, seed=1)
    va = q_data.build(val_ids, pool_train, n_val, seed=2)
    te = q_data.build(mitdb.DS2, pool_test, n_test, seed=3)
    model = QualityNet(len(q_data.LABELS))
    cfg = TrainConfig(epochs=epochs, batch_size=256, lr=2e-3)
    model, info = train(model, (torch.from_numpy(tr.x),), torch.from_numpy(tr.y),
                        (torch.from_numpy(va.x),), va.y, q_data.LABELS, cfg)
    probs = predict(model, (torch.from_numpy(te.x),))
    rep = class_report(te.y, probs.argmax(1), q_data.LABELS)
    by_kind = {k: float((probs.argmax(1)[te.kind == k] == te.y[te.kind == k]).mean()) for k in sorted(set(te.kind))}
    card = _save_model(model, "quality_net", {
        "name": "quality_net", "task": "single-lead 2.5 s window signal quality: good / noisy / unusable",
        "input": "900 samples @ 360 Hz, millivolts, median removed", "labels": q_data.LABELS,
        "intended_use": "Research use only. Gate for downstream analysis; not validated on clinical data.",
        "train_patients": train_ids, "val_patients": val_ids, "test_patients": mitdb.DS2,
        "noise_split": "NSTDB bw/em/ma: first 60% of each recording train, last 40% test",
        "label_source": "proxy labels from known injected SNR and synthetic failure modes (see quality/dataset.py)",
    })
    result = _meta(task="signal_quality", sizes={"train": len(tr.y), "val": len(va.y), "test": len(te.y)},
                   test=rep, test_accuracy_by_generator=by_kind, training=info, model_card=card)
    _write("signal_quality", result)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1")}), flush=True)
    return result


# ---------------------------------------------------------------- beat classification
def beat_augment(x: torch.Tensor, rr: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Patient-to-patient variation the training set under-represents: gain, baseline, noise,
    small misalignment of the R peak, and slight RR jitter."""
    n = x.shape[0]
    x = x * torch.empty(n, 1).uniform_(0.7, 1.3) + torch.randn(n, 1) * 0.1
    x = x + torch.randn_like(x) * 0.03
    x = torch.roll(x, shifts=int(torch.randint(-4, 5, (1,))), dims=1)
    rr = rr * torch.empty(n, 1).uniform_(0.95, 1.05)
    return x, rr


BEAT_VERSIONS = {
    "v0.1": {"dropout": 0.3, "augment": False, "label_smoothing": 0.0, "epochs": 14},
    "v0.2": {"dropout": 0.5, "augment": True, "label_smoothing": 0.05, "epochs": 14},
}


def train_beats(version: str = "v0.2") -> dict:
    spec = BEAT_VERSIONS[version]
    epochs = spec["epochs"]
    print(f"building beat datasets… ({version}: {spec})", flush=True)
    tr, va, te = beat_data.splits()
    counts = np.bincount(tr.y, minlength=len(beat_data.CLASSES)).astype(float)
    weights = (counts.sum() / np.maximum(counts, 1)) ** 0.5
    weights = (weights / weights.mean()).tolist()
    model = BeatNet(len(beat_data.CLASSES), dropout=spec["dropout"])
    cfg = TrainConfig(epochs=epochs, batch_size=256, lr=1e-3, class_weights=weights,
                      label_smoothing=spec["label_smoothing"], augment=beat_augment if spec["augment"] else None)
    model, info = train(model, (torch.from_numpy(tr.x), torch.from_numpy(tr.rr)), torch.from_numpy(tr.y),
                        (torch.from_numpy(va.x), torch.from_numpy(va.rr)), va.y, beat_data.CLASSES, cfg)
    probs = predict(model, (torch.from_numpy(te.x), torch.from_numpy(te.rr)))
    rep = class_report(te.y, probs.argmax(1), beat_data.CLASSES)
    per_record = {}
    for rid in np.unique(te.record):
        m = te.record == rid
        per_record[int(rid)] = class_report(te.y[m], probs[m].argmax(1), beat_data.CLASSES)["per_class"]
    card = _save_model(model, f"beat_net_{version}", {
        "name": "beat_net", "version": version, "recipe": spec, "task": "AAMI beat class N / S / V / F from MLII beat window + RR features",
        "input": f"{beat_data.PRE + beat_data.POST} samples @ 360 Hz (0.25 s before to 0.40 s after R), monitoring filter 0.5–40 Hz",
        "labels": beat_data.CLASSES,
        "intended_use": "Research use only. Not validated on clinical data or other devices.",
        "train_patients": sorted(set(tr.record.tolist())), "val_patients": beat_data.VAL_PATIENTS, "test_patients": mitdb.DS2,
        "class_weights": weights,
    })
    result = _meta(task="beat_classification", version=version, split="de Chazal inter-patient: DS1 train (minus val patients), DS2 test",
                   sizes={"train": np.bincount(tr.y, minlength=4).tolist(), "val": np.bincount(va.y, minlength=4).tolist(),
                          "test": np.bincount(te.y, minlength=4).tolist()},
                   test=rep, test_per_record=per_record, training=info, model_card=card)
    _write(f"beat_classification_{version}", result)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1")}), flush=True)
    return result


# ---------------------------------------------------------------- end to end (what a user would get)
def eval_pipeline() -> dict:
    """Full pipeline (quality gate -> detection -> refinement -> classification) on every DS2 record,
    scored against the cardiologist annotations. Reference beats with no matching detection count as
    missed; beats in segments the quality gate rejected are reported separately."""
    from cardiotic_ml import pipeline

    models = pipeline.load_models()
    labels = beat_data.CLASSES
    y_true, y_pred, per_record = [], [], {}
    missed_total = gated_total = extra_total = 0
    for rid in mitdb.DS2:
        rec = mitdb.load_record(rid)
        res = pipeline.analyze(rec.signal, rec.fs, models)
        det = np.array([round(b["time_s"] * rec.fs) for b in res["beats"]], dtype=np.int64)
        cls = np.array([labels.index(b["class"]) for b in res["beats"]], dtype=np.int64)
        unusable = [(s["start_s"], s["end_s"]) for s in res["quality_segments"] if s["quality"] == "unusable"]
        tol = int(0.150 * rec.fs)
        used = np.zeros(len(det), dtype=bool)
        t_r, p_r, missed, gated = [], [], 0, 0
        for samp, sym in zip(rec.ann_samples, rec.ann_symbols):
            c = mitdb.aami_class(sym)
            if c not in labels:
                continue
            j = np.searchsorted(det, samp)
            cand = [k for k in (j - 1, j) if 0 <= k < len(det) and not used[k] and abs(det[k] - samp) <= tol]
            if cand:
                k = min(cand, key=lambda k: abs(det[k] - samp))
                used[k] = True
                t_r.append(labels.index(c)); p_r.append(cls[k])
            elif any(a <= samp / rec.fs < b for a, b in unusable):
                gated += 1
            else:
                missed += 1
        y_true += t_r; y_pred += p_r
        missed_total += missed; gated_total += gated; extra_total += int((~used).sum())
        per_record[rid] = {"matched": len(t_r), "missed": missed, "in_unusable_segments": gated,
                           "unmatched_detections": int((~used).sum()),
                           "usable_fraction": res["measurements"].get("usable_fraction")}
        print(f"record {rid}: matched {len(t_r)}, missed {missed}, gated {gated}", flush=True)
    rep = class_report(np.array(y_true), np.array(y_pred), labels)
    result = _meta(task="end_to_end_pipeline", beat_model=pipeline.BEAT_MODEL, qrs_method=pipeline.QRS_METHOD,
                   test_patients=mitdb.DS2, test=rep,
                   totals={"matched": len(y_true), "missed": missed_total, "in_unusable_segments": gated_total,
                           "unmatched_detections": extra_total},
                   per_record=per_record)
    _write("end_to_end_pipeline", result)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1")}), flush=True)
    return result
