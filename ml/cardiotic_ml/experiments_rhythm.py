"""Rhythm model M3 (CinC 2017), cross-dataset AF test on MIT-BIH, and calibration (M5)."""

from __future__ import annotations

import json
from collections import Counter

import numpy as np
import torch
import wfdb

from cardiotic_ml import calibration as cal
from cardiotic_ml.data import cinc2017, mitdb
from cardiotic_ml.experiments import _meta, _save_model, _write
from cardiotic_ml.paths import ARTIFACTS_DIR, MITDB_DIR
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


def train_rhythm(epochs: int = 16) -> dict:
    print("loading CinC 2017…", flush=True)
    sigs = cinc2017.load_all()
    lab = {r: LABELS.index(l) for r, l in cinc2017.reference()}
    sp = cinc2017.split()
    print("building windows (beat detection on every record)…", flush=True)
    tr, va, te = (rd.build(sigs, lab, sp[k], cinc2017.FS) for k in ("train", "val", "test"))
    counts = np.bincount(tr.y, minlength=len(LABELS)).astype(float)
    weights = (counts.sum() / np.maximum(counts, 1)) ** 0.5
    weights = (weights / weights.mean()).tolist()
    model = RhythmNet(len(LABELS))
    cfg = TrainConfig(epochs=epochs, batch_size=64, lr=1e-3, class_weights=weights, augment=rhythm_augment)
    model, info = train(model, (torch.from_numpy(tr.x), torch.from_numpy(tr.rr)), torch.from_numpy(tr.y),
                        (torch.from_numpy(va.x), torch.from_numpy(va.rr)), va.y, LABELS, cfg)
    # calibration: fit on validation windows only
    val_logits = predict_logits(model, (torch.from_numpy(va.x), torch.from_numpy(va.rr)))
    temperature = cal.fit_temperature(val_logits, va.y)
    test_logits = predict_logits(model, (torch.from_numpy(te.x), torch.from_numpy(te.rr)))
    raw_p, _, _ = _record_level(cal.softmax(test_logits), te.group, te.y)
    cal_p, y_rec, _ = _record_level(cal.softmax(test_logits, temperature), te.group, te.y)
    rep = class_report(y_rec, cal_p.argmax(1), LABELS)
    calib = {"temperature": temperature, "ece_before": cal.ece(raw_p, y_rec), "ece_after": cal.ece(cal_p, y_rec),
             "confidence_levels": cal.bin_accuracy(cal_p, y_rec)}
    card = _save_model(model, "rhythm_net_v0.1", {
        "name": "rhythm_net", "version": "v0.1",
        "task": "30 s single-lead rhythm: N normal / A atrial fibrillation / O other rhythm / ~ too noisy",
        "input": f"{rd.WIN} samples @ {rd.FS_MODEL} Hz (monitoring band-pass, per-window std normalisation) + {rd.N_RRF} RR features",
        "labels": LABELS, "temperature": temperature,
        "intended_use": "Research use only. Trained on handheld single-lead ECGs; not validated on clinical monitors.",
        "data": "PhysioNet/CinC Challenge 2017 training set (ODC-By 1.0), REFERENCE-v3 labels, stratified 70/10/20 by record",
    })
    result = _meta(task="rhythm_classification", dataset="CinC 2017 (REFERENCE-v3)",
                   split="stratified by record 70/10/20 (no patient IDs published)",
                   sizes={k: {"records": len(sp[k]), "windows": int(len(s.y))} for k, s in zip(("train", "val", "test"), (tr, va, te))},
                   test=rep, test_challenge_f1=challenge_f1(rep), calibration=calib, training=info, model_card=card)
    result["datasets"]["cinc2017"] = "PhysioNet/CinC Challenge 2017 1.0.0 (ODC-By 1.0)"
    _write("rhythm_classification_v0.1", result)
    print(json.dumps({"challenge_f1": result["test_challenge_f1"], **{k: calib[k] for k in ("ece_before", "ece_after")}}), flush=True)
    return result


def load_rhythm_model() -> tuple[RhythmNet, float, dict]:
    card = json.loads((ARTIFACTS_DIR / "rhythm_net_v0.1.card.json").read_text())
    m = RhythmNet(len(LABELS))
    m.load_state_dict(torch.load(ARTIFACTS_DIR / "rhythm_net_v0.1.pt", weights_only=True))
    m.eval()
    return m, card["temperature"], card


def _rhythm_spans(rid: int, n_samples: int) -> list[tuple[int, int, str]]:
    ann = wfdb.rdann(str(MITDB_DIR / str(rid)), "atr")
    marks = [(s, a.strip("\x00")) for s, sym, a in zip(ann.sample, ann.symbol, ann.aux_note) if sym == "+"]
    return [(s, marks[i + 1][0] if i + 1 < len(marks) else n_samples, a) for i, (s, a) in enumerate(marks)]


def eval_rhythm_mitdb() -> dict:
    """Cross-dataset test: a model trained only on handheld CinC ECGs, run on MIT-BIH Holter MLII.
    30 s non-overlapping windows; AF if the whole window is annotated (AFIB, non-AF if no AFIB at all,
    windows that straddle an AF boundary are skipped. Paced records are excluded."""
    model, temperature, _ = load_rhythm_model()
    rows, tp, fn, fp, tn = [], 0, 0, 0, 0
    pred_on_nonaf = Counter()
    for rid in mitdb.ALL_RECORDS:
        if rid in mitdb.PACED:
            continue
        rec = mitdb.load_record(rid)
        x, beats = rd.prepare(rec.signal, rec.fs)
        w, r, starts = rd.windows(x, beats, stride_s=rd.WIN_S)
        spans = _rhythm_spans(rid, len(rec.signal))
        p = cal.softmax(predict_logits(model, (torch.from_numpy(w), torch.from_numpy(r))), temperature)
        rec_tp = rec_fn = rec_fp = rec_tn = 0
        for st, prob in zip(starts, p):
            a, b = int(st * rec.fs), int((st + rd.WIN_S) * rec.fs)
            overlap = [lab for s, e, lab in spans if s < b and e > a]
            is_af = overlap == ["(AFIB"]
            if not is_af and "(AFIB" in overlap:
                continue
            said_af = prob.argmax() == LABELS.index("A")
            if is_af:
                rec_tp += said_af; rec_fn += not said_af
            else:
                rec_fp += said_af; rec_tn += not said_af
                pred_on_nonaf[LABELS[prob.argmax()]] += 1
        tp += rec_tp; fn += rec_fn; fp += rec_fp; tn += rec_tn
        if rec_tp + rec_fn or rec_fp:
            rows.append({"record": rid, "af_windows": rec_tp + rec_fn, "af_detected": rec_tp, "false_af_windows": rec_fp})
        print(f"record {rid}: AF windows {rec_tp + rec_fn}, detected {rec_tp}, false AF {rec_fp}", flush=True)
    res = {"windows_af": tp + fn, "windows_non_af": fp + tn,
           "af_sensitivity": tp / (tp + fn) if tp + fn else float("nan"),
           "af_ppv": tp / (tp + fp) if tp + fp else float("nan"),
           "af_specificity": tn / (tn + fp) if tn + fp else float("nan"),
           "predictions_on_non_af_windows": dict(pred_on_nonaf), "per_record": rows}
    result = _meta(task="rhythm_cross_dataset_af", train_data="CinC 2017 only", test_data="MIT-BIH Arrhythmia (all non-paced records), MLII",
                   protocol="30 s non-overlapping windows; AF = window entirely inside an (AFIB episode; mixed windows skipped", **res)
    _write("rhythm_cross_dataset_mitdb", result)
    print(json.dumps({k: res[k] for k in ("af_sensitivity", "af_ppv", "af_specificity")}), flush=True)
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
