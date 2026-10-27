"""Rhythm model M3 (CinC 2017), cross-dataset AF test on MIT-BIH, and calibration (M5)."""

from __future__ import annotations

import json
from collections import Counter

import numpy as np
import torch

from cardiotic_ml import calibration as cal
from cardiotic_ml.data import cinc2017, mitdb
from cardiotic_ml.experiments import _meta, _save_model, _write
from cardiotic_ml.paths import ARTIFACTS_DIR, REPORTS_DIR
from cardiotic_ml.rhythm import dataset as rd
from cardiotic_ml.rhythm.model import RhythmNet
from cardiotic_ml.train_utils import TrainConfig, class_report, predict_logits, train

LABELS = cinc2017.LABELS


def rhythm_augment(x: torch.Tensor, rr: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Handheld recordings are often taken upside down (inverted polarity) and noisy."""
    flip = (torch.rand(x.shape[0], 1) < 0.3).float() * -2 + 1
    return x * flip + torch.randn_like(x) * 0.05, rr


def _record_level(probs: np.ndarray, groups: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray, list]:
    ids = list(dict.fromkeys(groups))
    p = np.stack([probs[groups == g].mean(0) for g in ids])
    y = np.array([ys[groups == g][0] for g in ids])
    return p, y, ids


def challenge_f1(rep: dict) -> float:
    """PhysioNet/CinC 2017 score: mean F1 of normal, AF and other rhythm."""
    return float(np.mean([rep["per_class"][c]["f1"] for c in ("N", "A", "O")]))


RHYTHM_VERSIONS = {
    "v0.1": {"ectopy_features": False, "mitdb_train": False, "epochs": 14},
    # v0.2 targets false AF in ectopy-rich Holter recordings (see RESULTS.md issue 5):
    # ectopy-aware RR features from the beat classifier + MIT-BIH training windows.
    "v0.2": {"ectopy_features": True, "mitdb_train": True, "epochs": 14},
}
# MIT-BIH split for rhythm work. Train: DS1 minus validation. Validation (version choice only):
# 201 (AF), 215 (PVC-rich, most false AF in DS1), 207, 209, 220. Test: DS2 — unseen by every version.
MITDB_RHYTHM_VAL = [201, 215, 207, 209, 220]
MITDB_RHYTHM_TRAIN = [r for r in mitdb.DS1 if r not in MITDB_RHYTHM_VAL]


def _beat_model():
    from cardiotic_ml.beats import dataset as beat_data
    from cardiotic_ml.beats.model import BeatNet
    from cardiotic_ml.pipeline import BEAT_MODEL

    card = json.loads((ARTIFACTS_DIR / f"{BEAT_MODEL}.card.json").read_text())
    m = BeatNet(len(beat_data.CLASSES), dropout=card.get("recipe", {}).get("dropout", 0.3))
    m.load_state_dict(torch.load(ARTIFACTS_DIR / f"{BEAT_MODEL}.pt", weights_only=True))
    return m.eval()


def _cinc_record_report(model, temperature: float, ds) -> tuple[dict, np.ndarray, np.ndarray]:
    logits = predict_logits(model, (torch.from_numpy(ds.x), torch.from_numpy(ds.rr)))
    p, y, _ = _record_level(cal.softmax(logits, temperature), ds.group, ds.y)
    return class_report(y, p.argmax(1), LABELS), p, y


def train_rhythm(version: str = "v0.2") -> dict:
    spec = RHYTHM_VERSIONS[version]
    print(f"loading CinC 2017… ({version}: {spec})", flush=True)
    sigs = cinc2017.load_all()
    lab = {r: LABELS.index(l) for r, l in cinc2017.reference()}
    sp = cinc2017.split()
    bm = _beat_model() if spec["ectopy_features"] else None
    n_rrf = rd.N_RRF_ECTOPY if spec["ectopy_features"] else rd.N_RRF
    print("building windows (beat detection on every record)…", flush=True)
    tr, va, te = (rd.build(sigs, lab, sp[k], cinc2017.FS, beat_model=bm) for k in ("train", "val", "test"))
    n_mitdb = 0
    if spec["mitdb_train"]:
        mt = rd.build_mitdb(MITDB_RHYTHM_TRAIN, beat_model=bm)
        n_mitdb = len(mt.y)
        print(f"MIT-BIH training windows: {n_mitdb} {np.bincount(mt.y, minlength=4).tolist()}", flush=True)
        tr = rd.RhythmSet(np.concatenate([tr.x, mt.x]), np.concatenate([tr.rr, mt.rr]),
                          np.concatenate([tr.y, mt.y]), np.concatenate([tr.group, mt.group]))
    counts = np.bincount(tr.y, minlength=len(LABELS)).astype(float)
    weights = (counts.sum() / np.maximum(counts, 1)) ** 0.5
    weights = (weights / weights.mean()).tolist()
    model = RhythmNet(len(LABELS), n_rrf=n_rrf)
    cfg = TrainConfig(epochs=spec["epochs"], batch_size=64, lr=1e-3, class_weights=weights, augment=rhythm_augment)
    model, info = train(model, (torch.from_numpy(tr.x), torch.from_numpy(tr.rr)), torch.from_numpy(tr.y),
                        (torch.from_numpy(va.x), torch.from_numpy(va.rr)), va.y, LABELS, cfg)
    val_logits = predict_logits(model, (torch.from_numpy(va.x), torch.from_numpy(va.rr)))
    temperature = cal.fit_temperature(val_logits, va.y)
    val_rep, _, _ = _cinc_record_report(model, temperature, va)
    test_logits = predict_logits(model, (torch.from_numpy(te.x), torch.from_numpy(te.rr)))
    raw_p, _, _ = _record_level(cal.softmax(test_logits), te.group, te.y)
    rep, cal_p, y_rec = _cinc_record_report(model, temperature, te)
    calib = {"temperature": temperature, "ece_before": cal.ece(raw_p, y_rec), "ece_after": cal.ece(cal_p, y_rec),
             "confidence_levels": cal.bin_accuracy(cal_p, y_rec)}
    card = _save_model(model, f"rhythm_net_{version}", {
        "name": "rhythm_net", "version": version, "recipe": spec, "n_rrf": n_rrf,
        "task": "30 s single-lead rhythm: N normal / A atrial fibrillation / O other rhythm / ~ too noisy",
        "input": f"{rd.WIN} samples @ {rd.FS_MODEL} Hz (monitoring band-pass, per-window std normalisation) + {n_rrf} RR features"
                 + (" (ectopy-aware: uses the beat classifier's V/F labels)" if spec["ectopy_features"] else ""),
        "labels": LABELS, "temperature": temperature,
        "intended_use": "Research use only. Not validated on clinical monitors.",
        "data": "PhysioNet/CinC Challenge 2017 training set (ODC-By 1.0), REFERENCE-v3 labels, stratified 70/10/20 by record"
                + (f"; plus {n_mitdb} MIT-BIH windows from records {MITDB_RHYTHM_TRAIN}" if n_mitdb else ""),
    })
    result = _meta(task="rhythm_classification", version=version, dataset="CinC 2017 (REFERENCE-v3)",
                   split="stratified by record 70/10/20 (no patient IDs published)",
                   sizes={k: {"records": len(sp[k]), "windows": int(len(s.y))} for k, s in zip(("train", "val", "test"), (tr, va, te))}
                   | {"mitdb_train_windows": n_mitdb},
                   val=val_rep, val_challenge_f1=challenge_f1(val_rep),
                   test=rep, test_challenge_f1=challenge_f1(rep), calibration=calib, training=info, model_card=card)
    result["datasets"]["cinc2017"] = "PhysioNet/CinC Challenge 2017 1.0.0 (ODC-By 1.0)"
    _write(f"rhythm_classification_{version}", result)
    print(json.dumps({"val_challenge_f1": result["val_challenge_f1"], "test_challenge_f1": result["test_challenge_f1"]}), flush=True)
    return result


def load_rhythm_model(version: str = "v0.1") -> tuple[RhythmNet, float, dict]:
    card = json.loads((ARTIFACTS_DIR / f"rhythm_net_{version}.card.json").read_text())
    m = RhythmNet(len(LABELS), n_rrf=card.get("n_rrf", rd.N_RRF))
    m.load_state_dict(torch.load(ARTIFACTS_DIR / f"rhythm_net_{version}.pt", weights_only=True))
    return m.eval(), card["temperature"], card


def cinc_val_for(version: str) -> None:
    """Add CinC validation scores to a rhythm report trained before they were recorded (v0.1)."""
    path = REPORTS_DIR / f"rhythm_classification_{version}.json"
    result = json.loads(path.read_text())
    model, t, card = load_rhythm_model(version)
    bm = _beat_model() if card.get("recipe", {}).get("ectopy_features") else None
    sigs = cinc2017.load_all()
    lab = {r: LABELS.index(l) for r, l in cinc2017.reference()}
    va = rd.build(sigs, lab, cinc2017.split()["val"], cinc2017.FS, beat_model=bm)
    rep, _, _ = _cinc_record_report(model, t, va)
    result["val"], result["val_challenge_f1"] = rep, challenge_f1(rep)
    path.write_text(json.dumps(result, indent=2, default=float))
    print(json.dumps({"val_challenge_f1": result["val_challenge_f1"]}), flush=True)


MITDB_SPLITS = {"val": MITDB_RHYTHM_VAL, "test": mitdb.DS2,
                "all": [r for r in mitdb.ALL_RECORDS if r not in mitdb.PACED]}


def eval_rhythm_mitdb(version: str = "v0.1", split: str = "test") -> dict:
    """AF detection on MIT-BIH Holter MLII. 30 s non-overlapping windows; AF if the whole window is
    annotated (AFIB, non-AF if no AFIB at all; windows straddling an AF boundary are skipped.
    Split 'test' (DS2) is unseen by every version; 'val' is used to choose versions."""
    model, temperature, card = load_rhythm_model(version)
    bm = _beat_model() if card.get("recipe", {}).get("ectopy_features") else None
    rows, tp, fn, fp, tn = [], 0, 0, 0, 0
    pred_on_nonaf = Counter()
    for rid in MITDB_SPLITS[split]:
        rec = mitdb.load_record(rid)
        x, beats, ect = rd.prepare(rec.signal, rec.fs, bm)
        w, r, starts = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect)
        spans = rd.mitdb_rhythm_spans(rid, len(rec.signal))
        p = cal.softmax(predict_logits(model, (torch.from_numpy(w), torch.from_numpy(r))), temperature)
        rec_tp = rec_fn = rec_fp = rec_tn = 0
        for st, prob in zip(starts, p):
            a, b = int(st * rec.fs), int((st + rd.WIN_S) * rec.fs)
            overlap = [lab for s0, e0, lab in spans if s0 < b and e0 > a]
            is_af = overlap == ["(AFIB"]
            if not is_af and "(AFIB" in overlap:
                continue
            said_af = prob.argmax() == LABELS.index("A")
            if is_af:
                rec_tp += said_af; rec_fn += not said_af
            else:
                rec_fp += said_af; rec_tn += not said_af
                pred_on_nonaf[LABELS[prob.argmax()]] += 1
        rec_tp, rec_fn, rec_fp, rec_tn = int(rec_tp), int(rec_fn), int(rec_fp), int(rec_tn)
        tp += rec_tp; fn += rec_fn; fp += rec_fp; tn += rec_tn
        if rec_tp + rec_fn or rec_fp:
            rows.append({"record": rid, "af_windows": rec_tp + rec_fn, "af_detected": rec_tp, "false_af_windows": rec_fp})
        print(f"[{version} {split}] record {rid}: AF windows {rec_tp + rec_fn}, detected {rec_tp}, false AF {rec_fp}", flush=True)
    res = {"windows_af": tp + fn, "windows_non_af": fp + tn, "false_af_windows": fp,
           "af_sensitivity": tp / (tp + fn) if tp + fn else float("nan"),
           "af_ppv": tp / (tp + fp) if tp + fp else float("nan"),
           "af_specificity": tn / (tn + fp) if tn + fp else float("nan"),
           "predictions_on_non_af_windows": dict(pred_on_nonaf), "per_record": rows}
    result = _meta(task="rhythm_mitdb_af", version=version, split=split, records=MITDB_SPLITS[split],
                   protocol="30 s non-overlapping windows; AF = window entirely inside an (AFIB episode; mixed windows skipped", **res)
    _write(f"rhythm_mitdb_{split}_{version}", result)
    print(json.dumps({k: res[k] for k in ("af_sensitivity", "af_ppv", "af_specificity", "false_af_windows")}), flush=True)
    return result


def calibrate_beats() -> dict:
    """Fit a temperature for the adopted beat model on its validation patients; check on DS2."""
    from cardiotic_ml.beats import dataset as beat_data
    from cardiotic_ml.beats.model import BeatNet
    from cardiotic_ml.pipeline import BEAT_MODEL

    card_path = ARTIFACTS_DIR / f"{BEAT_MODEL}.card.json"
    card = json.loads(card_path.read_text())
    model = BeatNet(len(beat_data.CLASSES), dropout=card.get("recipe", {}).get("dropout", 0.3))
    model.load_state_dict(torch.load(ARTIFACTS_DIR / f"{BEAT_MODEL}.pt", weights_only=True))
    _, va, te = beat_data.splits()
    t = cal.fit_temperature(predict_logits(model, (torch.from_numpy(va.x), torch.from_numpy(va.rr))), va.y)
    lt = predict_logits(model, (torch.from_numpy(te.x), torch.from_numpy(te.rr)))
    raw, calp = cal.softmax(lt), cal.softmax(lt, t)
    card["temperature"] = t
    card_path.write_text(json.dumps(card, indent=2, default=float))
    result = _meta(task="beat_calibration", beat_model=BEAT_MODEL, temperature=t,
                   ece_before=cal.ece(raw, te.y), ece_after=cal.ece(calp, te.y),
                   confidence_levels_before=cal.bin_accuracy(raw, te.y), confidence_levels_after=cal.bin_accuracy(calp, te.y))
    _write("beat_calibration", result)
    print(json.dumps({k: result[k] for k in ("temperature", "ece_before", "ece_after")}), flush=True)
    return result
