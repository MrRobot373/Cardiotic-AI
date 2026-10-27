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
QUALITY_VERSIONS = {
    "v0.1": {"extra_p": 0.0, "low_amp_p": 0.0, "epochs": 10},
    # v0.2 targets the record-222 finding: real AF / other-rhythm windows (CinC 2017) as "good"
    # bases, and low-amplitude versions of clean windows.
    "v0.2": {"extra_p": 0.3, "low_amp_p": 0.3, "epochs": 10},
}
QUALITY_VAL_PATIENTS = [106, 118, 207, 220]


def _cinc_quality_bases(records: list[str], signals: dict[str, np.ndarray]) -> np.ndarray:
    from cardiotic_ml.data import cinc2017
    return np.concatenate([q_data.signal_windows(signals[r], cinc2017.FS) for r in records])


@torch.no_grad()
def rate_windows(model: QualityNet, windows: np.ndarray) -> np.ndarray:
    model.eval()
    if len(windows) == 0:
        return np.zeros(0, dtype=np.int64)
    return model(torch.from_numpy(np.clip(windows, -10, 10))).argmax(1).numpy()


def quality_real_data(model: QualityNet, split: str, signals: dict[str, np.ndarray] | None = None) -> dict:
    """Real expert-labelled check (CinC 2017): share of windows rated good / noisy / unusable for
    normal, AF, other-rhythm and 'too noisy' recordings — the last one should be rated badly,
    the other three should not. For split='test' also the MIT-BIH DS2 AF / flutter records."""
    from cardiotic_ml.data import cinc2017
    signals = signals if signals is not None else cinc2017.load_all()
    ref = dict(cinc2017.reference())
    out = {}
    for lab in cinc2017.LABELS:
        recs = [r for r in cinc2017.split()[split] if ref[r] == lab]
        pred = rate_windows(model, _cinc_quality_bases(recs, signals))
        out[f"cinc_{lab}"] = {q: float(np.mean(pred == i)) for i, q in enumerate(q_data.LABELS)} | {"windows": int(len(pred))}
    if split == "test":
        for rid in (201, 203, 210, 219, 221, 222):  # all have AF; 222 also flutter and low amplitude
            if rid in mitdb.DS2:
                rec = mitdb.load_record(rid)
                pred = rate_windows(model, q_data.signal_windows(rec.signal, rec.fs))
                out[f"mitdb_{rid}"] = {q: float(np.mean(pred == i)) for i, q in enumerate(q_data.LABELS)}
    return out


def train_quality(version: str = "v0.2", n_train: int = 30000, n_val: int = 5000, n_test: int = 10000) -> dict:
    spec = QUALITY_VERSIONS[version]
    pool_train, pool_test = q_data.noise_pools()
    val_ids = QUALITY_VAL_PATIENTS
    train_ids = [r for r in mitdb.DS1 if r not in val_ids]
    signals, extra = None, None
    if spec["extra_p"]:
        from cardiotic_ml.data import cinc2017
        signals = cinc2017.load_all()
        ref = dict(cinc2017.reference())
        extra = _cinc_quality_bases([r for r in cinc2017.split()["train"] if ref[r] in ("A", "O")], signals)
    print(f"building quality datasets… ({version}: {spec})", flush=True)
    tr = q_data.build(train_ids, pool_train, n_train, seed=1, extra_clean=extra, extra_p=spec["extra_p"], low_amp_p=spec["low_amp_p"])
    va = q_data.build(val_ids, pool_train, n_val, seed=2)
    te = q_data.build(mitdb.DS2, pool_test, n_test, seed=3)
    model = QualityNet(len(q_data.LABELS))
    cfg = TrainConfig(epochs=spec["epochs"], batch_size=256, lr=2e-3)
    model, info = train(model, (torch.from_numpy(tr.x),), torch.from_numpy(tr.y),
                        (torch.from_numpy(va.x),), va.y, q_data.LABELS, cfg)
    probs = predict(model, (torch.from_numpy(te.x),))
    rep = class_report(te.y, probs.argmax(1), q_data.LABELS)
    val_rep = class_report(va.y, predict(model, (torch.from_numpy(va.x),)).argmax(1), q_data.LABELS)
    by_kind = {k: float((probs.argmax(1)[te.kind == k] == te.y[te.kind == k]).mean()) for k in sorted(set(te.kind))}
    card = _save_model(model, f"quality_net_{version}", {
        "name": "quality_net", "version": version, "recipe": spec,
        "task": "single-lead 2.5 s window signal quality: good / noisy / unusable",
        "input": "900 samples @ 360 Hz, millivolts, median removed", "labels": q_data.LABELS,
        "intended_use": "Research use only. Gate for downstream analysis; not validated on clinical data.",
        "train_patients": train_ids, "val_patients": val_ids, "test_patients": mitdb.DS2,
        "noise_split": "NSTDB bw/em/ma: first 60% of each recording train, last 40% test",
        "label_source": "proxy labels from known injected SNR and synthetic failure modes (see quality/dataset.py)"
                        + ("; extra good bases from CinC 2017 train-split AF / other-rhythm records" if extra is not None else ""),
    })
    print("real-data checks…", flush=True)
    result = _meta(task="signal_quality", version=version, sizes={"train": len(tr.y), "val": len(va.y), "test": len(te.y)},
                   test=rep, val=val_rep, test_accuracy_by_generator=by_kind, training=info, model_card=card,
                   real_data_val=quality_real_data(model, "val", signals), real_data_test=quality_real_data(model, "test", signals))
    _write(f"signal_quality_{version}", result)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1")}), flush=True)
    return result


def quality_real_data_for(version: str) -> None:
    """Add the real-data checks to an existing quality report (used for v0.1, trained before they existed)."""
    path = REPORTS_DIR / f"signal_quality_{version}.json"
    result = json.loads(path.read_text())
    model = QualityNet(len(q_data.LABELS))
    model.load_state_dict(torch.load(ARTIFACTS_DIR / f"quality_net_{version}.pt", weights_only=True))
    from cardiotic_ml.data import cinc2017
    signals = cinc2017.load_all()
    pool_train, _ = q_data.noise_pools()
    va = q_data.build(QUALITY_VAL_PATIENTS, pool_train, 5000, seed=2)
    result["val"] = class_report(va.y, predict(model, (torch.from_numpy(va.x),)).argmax(1), q_data.LABELS)
    result["real_data_val"] = quality_real_data(model, "val", signals)
    result["real_data_test"] = quality_real_data(model, "test", signals)
    path.write_text(json.dumps(result, indent=2, default=float))


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
    result = _meta(task="end_to_end_pipeline", quality_model=pipeline.QUALITY_MODEL, beat_model=pipeline.BEAT_MODEL, qrs_method=pipeline.QRS_METHOD,
                   test_patients=mitdb.DS2, test=rep,
                   totals={"matched": len(y_true), "missed": missed_total, "in_unusable_segments": gated_total,
                           "unmatched_detections": extra_total},
                   per_record=per_record)
    _write("end_to_end_pipeline", result)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1")}), flush=True)
    return result
