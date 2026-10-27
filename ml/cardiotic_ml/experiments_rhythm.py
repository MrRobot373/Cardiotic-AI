"""Rhythm model M3 (CinC 2017), cross-dataset AF test on MIT-BIH, and calibration (M5)."""

from __future__ import annotations

import json
from collections import Counter

import numpy as np
import torch

from cardiotic_ml import calibration as cal
from cardiotic_ml.data import afdb, cinc2017, mitdb
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
    # Retry with many AF patients (MIT-BIH AF Database). v0.4: v0.2 + AFDB training patients, whose AF
    # includes ectopic beats (breaks the "many PVCs = not AF" shortcut). v0.5: ablation without the
    # ectopy features. Chosen by `select_rhythm` on validation only (rule fixed before AFDB results).
    "v0.4": {"ectopy_features": True, "mitdb_train": True, "afdb_train": True, "epochs": 14},
    "v0.5": {"ectopy_features": False, "mitdb_train": True, "afdb_train": True, "epochs": 14},
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
    if spec.get("afdb_train"):
        at = build_afdb(afdb.split()["train"], bm if spec["ectopy_features"] else None, cap=AFDB_TRAIN_CAP)
        print(f"AFDB training windows: {len(at.y)} {np.bincount(at.y, minlength=4).tolist()}", flush=True)
        tr = rd.RhythmSet(np.concatenate([tr.x, at.x]), np.concatenate([tr.rr, at.rr]),
                          np.concatenate([tr.y, at.y]), np.concatenate([tr.group, at.group]))
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
                + (f"; plus {n_mitdb} MIT-BIH windows from records {MITDB_RHYTHM_TRAIN}" if n_mitdb else "")
                + (f"; plus MIT-BIH AF Database training patients {afdb.split()['train']} (ODC-By 1.0)" if spec.get("afdb_train") else ""),
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
    """Versions with a `base_model` (v0.3) reuse that model's weights and add an ectopy gate."""
    card = json.loads((ARTIFACTS_DIR / f"rhythm_net_{version}.card.json").read_text())
    base = json.loads((ARTIFACTS_DIR / f"{card['base_model']}.card.json").read_text()) if "base_model" in card else card
    m = RhythmNet(len(LABELS), n_rrf=base.get("n_rrf", rd.N_RRF))
    m.load_state_dict(torch.load(ARTIFACTS_DIR / base["file"], weights_only=True))
    return m.eval(), base["temperature"], card | {"recipe": base.get("recipe", {}), "temperature": base["temperature"]}


GATE_LEADS = ["MLII", "II"]
GATE_GRID = {"pvc_min": (0.02, 0.05, 0.1, 0.15), "tau": tuple(round(t, 2) for t in np.arange(0.04, 0.20, 0.01))}


def make_rhythm_gate() -> dict:
    """Choose the ectopy gate's thresholds on MIT-BIH VALIDATION records only (the lead the beat
    classifier is validated on). Rule, fixed in advance: minimise false-AF windows, subject to
    losing at most 2 points of AF sensitivity; ties -> smaller tau (gentler gate)."""
    from cardiotic_ml.rhythm import gate as rgate

    bm = _beat_model()
    model, t, _ = load_rhythm_model("v0.1")
    rows = []
    for rid in MITDB_RHYTHM_VAL:
        rec = mitdb.load_record(rid)
        x, beats, ect = rd.prepare(rec.signal, rec.fs, bm)
        wb, rb, st = rd.windows(x, beats, stride_s=rd.WIN_S)
        _, re_, _ = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect)
        p = cal.softmax(predict_logits(model, (torch.from_numpy(wb), torch.from_numpy(rb))), t)
        spans = rd.mitdb_rhythm_spans(rid, len(rec.signal))
        for s0, pr, f in zip(st, p, re_):
            a, b = int(s0 * rec.fs), int((s0 + rd.WIN_S) * rec.fs)
            ov = [l for x0, x1, l in spans if x0 < b and x1 > a]
            if ov != ["(AFIB"] and "(AFIB" in ov:
                continue
            rows.append((ov == ["(AFIB"], pr, f))
    is_af = np.array([r[0] for r in rows]); P = np.stack([r[1] for r in rows]); F = np.stack([r[2] for r in rows])
    base_af = P.argmax(1) == rgate.A
    grid, best = [], None
    for pmin in GATE_GRID["pvc_min"]:
        for tau in GATE_GRID["tau"]:
            _, g = rgate.apply(P, F, {"pvc_min": pmin, "tau": tau})
            se0 = (base_af & is_af).sum() / is_af.sum(); se1 = (base_af & ~g & is_af).sum() / is_af.sum()
            fa = int((base_af & ~g & ~is_af).sum())
            grid.append({"pvc_min": pmin, "tau": tau, "af_sensitivity": float(se1), "false_af_windows": fa})
            if se0 - se1 <= 0.02 and (best is None or fa < best["false_af_windows"] or (fa == best["false_af_windows"] and tau < best["tau"])):
                best = grid[-1]
    gate = {"pvc_min": best["pvc_min"], "tau": best["tau"], "leads": GATE_LEADS}
    card = {"name": "rhythm_net", "version": "v0.3", "base_model": "rhythm_net_v0.1", "gate": gate,
            "task": "rhythm_net v0.1 + ectopy gate for AF calls (rhythm/gate.py)",
            "intended_use": "Research use only. Gate active only for leads " + ", ".join(GATE_LEADS) + "; otherwise identical to v0.1.",
            "selection": "thresholds chosen on MIT-BIH validation records " + str(MITDB_RHYTHM_VAL)
                         + " only: minimise false-AF windows, AF sensitivity loss <= 2 points"}
    (ARTIFACTS_DIR / "rhythm_net_v0.3.card.json").write_text(json.dumps(card, indent=2, default=float))
    result = _meta(task="rhythm_gate_selection", version="v0.3", base_model="rhythm_net_v0.1", chosen=gate,
                   validation_records=MITDB_RHYTHM_VAL, validation_af_windows=int(is_af.sum()),
                   baseline_false_af_windows=int((base_af & ~is_af).sum()), grid=grid,
                   why_lead_restricted="On CinC 2017 validation (handheld lead I) the beat classifier labels many AF beats as "
                                       "ventricular (75th percentile PVC share 10.8% in true-AF windows), so any gate setting lost "
                                       "more than 2 points of AF sensitivity there.")
    _write("rhythm_gate_v0.3", result)
    print(json.dumps({"chosen": gate, "val_false_af": [result["baseline_false_af_windows"], best["false_af_windows"]]}), flush=True)
    return result


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
    from cardiotic_ml.rhythm import gate as rgate

    model, temperature, card = load_rhythm_model(version)
    gate = card.get("gate") if card.get("gate") and rgate.applies(card["gate"], "MLII") else None
    bm = _beat_model() if card.get("recipe", {}).get("ectopy_features") or gate else None
    n_gated = 0
    rows, tp, fn, fp, tn = [], 0, 0, 0, 0
    pred_on_nonaf = Counter()
    for rid in MITDB_SPLITS[split]:
        rec = mitdb.load_record(rid)
        x, beats, ect = rd.prepare(rec.signal, rec.fs, bm)
        uses_ect = card.get("recipe", {}).get("ectopy_features")
        w, r, starts = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect if uses_ect else None)
        spans = rd.mitdb_rhythm_spans(rid, len(rec.signal))
        p = cal.softmax(predict_logits(model, (torch.from_numpy(w), torch.from_numpy(r))), temperature)
        if gate:
            _, r_ect, _ = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect)
            p, gated = rgate.apply(p, r_ect, gate)
            n_gated += int(gated.sum())
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
    res = {"windows_af": tp + fn, "windows_non_af": fp + tn, "false_af_windows": fp, "gated_windows": n_gated,
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


# ---------------------------------------------------------------- MIT-BIH AF Database (many AF patients)
AFDB_TRAIN_CAP = 250   # max AF and max non-AF windows sampled per training patient
AFDB_CACHE = REPORTS_DIR.parent / "cache"


def _afdb_prepared(rid: str, beat_model) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Beat detection + beat classes on a 10 h record, cached (they do not depend on the rhythm model)."""
    AFDB_CACHE.mkdir(parents=True, exist_ok=True)
    path = AFDB_CACHE / f"afdb_{rid}.npz"
    if path.exists():
        z = np.load(path)
        return z["x"], z["beats"], z["ect"]
    x, beats, ect = rd.prepare(afdb.load_signal(rid), afdb.FS, beat_model if beat_model is not None else _beat_model())
    np.savez_compressed(path, x=x, beats=beats, ect=ect)
    return x, beats, ect


def _afdb_window_rhythms(rid: str, starts: np.ndarray) -> list[list[str]]:
    spans, _ = afdb.rhythm_spans(rid)
    out = []
    for st in starts:
        a, b = int(st * afdb.FS), int((st + rd.WIN_S) * afdb.FS)
        out.append([lab for s0, e0, lab in spans if s0 < b and e0 > a])
    return out


def build_afdb(record_ids: list[str], beat_model=None, cap: int | None = None, seed: int = 0) -> rd.RhythmSet:
    """Training windows. AF = window entirely (AFIB. Non-AF: (AFL / (J -> other rhythm; (N with >= 3
    beats the beat classifier calls V/F -> other rhythm, with none -> normal, 1-2 -> skipped. AFDB has
    no beat-type labels, so the N/O split is a weak label; AF vs non-AF is from the manual annotations."""
    rng = np.random.default_rng(seed)
    xs, rs, ys, gs = [], [], [], []
    for rid in record_ids:
        x, beats, ect = _afdb_prepared(rid, beat_model)
        w, r, starts = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect if beat_model is not None else None)
        labs = []
        for wi, rh in enumerate(_afdb_window_rhythms(rid, starts)):
            t0 = starts[wi]
            n_ect = int(ect[(beats >= t0) & (beats < t0 + rd.WIN_S)].sum())
            if rh == ["(AFIB"]:
                labs.append(LABELS.index("A"))
            elif not rh or "(AFIB" in rh:
                labs.append(-1)
            elif any(l in ("(AFL", "(J") for l in rh):
                labs.append(LABELS.index("O"))
            else:
                labs.append(LABELS.index("N") if n_ect == 0 else LABELS.index("O") if n_ect >= 3 else -1)
        labs = np.array(labs)
        keep = []
        for is_af in (True, False):
            idx = np.flatnonzero((labs == LABELS.index("A")) if is_af else ((labs >= 0) & (labs != LABELS.index("A"))))
            if cap and len(idx) > cap:
                idx = rng.choice(idx, cap, replace=False)
            keep += idx.tolist()
        keep = np.array(sorted(keep), dtype=int)
        xs.append(w[keep]); rs.append(r[keep]); ys.append(labs[keep]); gs += [f"afdb{rid}"] * len(keep)
    return rd.RhythmSet(np.concatenate(xs), np.concatenate(rs), np.concatenate(ys).astype(np.int64), np.asarray(gs))


def eval_rhythm_afdb(version: str = "v0.1", split: str = "val") -> dict:
    """AF vs non-AF on AFDB patients: 30 s non-overlapping windows, AF = window entirely (AFIB, non-AF =
    no AFIB at all, mixed windows skipped. Reported overall and per patient."""
    model, temperature, card = load_rhythm_model(version)
    uses_ect = card.get("recipe", {}).get("ectopy_features")
    bm = _beat_model()
    tp = fn = fp = tn = 0
    per = []
    for rid in afdb.split()[split]:
        x, beats, ect = _afdb_prepared(rid, bm)
        w, r, starts = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect if uses_ect else None)
        p = cal.softmax(predict_logits(model, (torch.from_numpy(w), torch.from_numpy(r))), temperature)
        said = p.argmax(1) == LABELS.index("A")
        rh = _afdb_window_rhythms(rid, starts)
        is_af = np.array([x_ == ["(AFIB"] for x_ in rh])
        non_af = np.array([bool(x_) and "(AFIB" not in x_ for x_ in rh])
        a, b, c, d = int((said & is_af).sum()), int((~said & is_af).sum()), int((said & non_af).sum()), int((~said & non_af).sum())
        tp += a; fn += b; fp += c; tn += d
        per.append({"record": rid, "af_windows": a + b, "af_detected": a, "false_af_windows": c, "non_af_windows": c + d,
                    "af_sensitivity": a / (a + b) if a + b else None})
        print(f"[{version} afdb-{split}] {rid}: AF {a}/{a + b}, false AF {c}/{c + d}", flush=True)
    res = {"windows_af": tp + fn, "windows_non_af": fp + tn, "false_af_windows": fp,
           "af_sensitivity": tp / (tp + fn) if tp + fn else float("nan"),
           "af_ppv": tp / (tp + fp) if tp + fp else float("nan"),
           "af_specificity": tn / (tn + fp) if tn + fp else float("nan"), "per_record": per}
    result = _meta(task="rhythm_afdb_af", version=version, split=split, records=afdb.split()[split],
                   protocol="30 s non-overlapping windows on AFDB channel 0; AF = window entirely (AFIB; non-AF = no AFIB; mixed skipped",
                   **res)
    result["datasets"]["afdb"] = "PhysioNet MIT-BIH Atrial Fibrillation Database 1.0.0 (ODC-By 1.0)"
    _write(f"rhythm_afdb_{split}_{version}", result)
    print(json.dumps({k: res[k] for k in ("af_sensitivity", "af_ppv", "af_specificity", "false_af_windows")}), flush=True)
    return result


SELECTION_RULE = ("Adopt a candidate over v0.1 only if, on VALIDATION data: (1) AF sensitivity drops by at most 2 points "
                  "on AFDB-val and on MIT-BIH-val, and no AFDB-val AF patient's AF sensitivity drops by more than 10 points; "
                  "(2) CinC val challenge F1 drops by at most 1 point; (3) false-AF windows on AFDB-val + MIT-BIH-val are "
                  "fewer than v0.1's. Among passing candidates, fewest false-AF windows wins. Fixed before any AFDB result.")


def select_rhythm(candidates: tuple[str, ...] = ("v0.4", "v0.5"), baseline: str = "v0.1") -> dict:
    def load(name):
        return json.loads((REPORTS_DIR / f"{name}.json").read_text())

    base = {"afdb": load(f"rhythm_afdb_val_{baseline}"), "mitdb": load(f"rhythm_mitdb_val_{baseline}"),
            "cinc": load(f"rhythm_classification_{baseline}")}
    base_pat = {p["record"]: p["af_sensitivity"] for p in base["afdb"]["per_record"] if p["af_sensitivity"] is not None}
    rows, passing = [], []
    for c in candidates:
        try:
            cur = {"afdb": load(f"rhythm_afdb_val_{c}"), "mitdb": load(f"rhythm_mitdb_val_{c}"), "cinc": load(f"rhythm_classification_{c}")}
        except FileNotFoundError:
            continue
        pat_drop = max(base_pat[p["record"]] - p["af_sensitivity"] for p in cur["afdb"]["per_record"] if p["record"] in base_pat)
        checks = {
            "afdb_af_se_drop": base["afdb"]["af_sensitivity"] - cur["afdb"]["af_sensitivity"],
            "mitdb_af_se_drop": base["mitdb"]["af_sensitivity"] - cur["mitdb"]["af_sensitivity"],
            "worst_patient_af_se_drop": pat_drop,
            "cinc_val_f1_drop": base["cinc"]["val_challenge_f1"] - cur["cinc"]["val_challenge_f1"],
            "false_af": cur["afdb"]["false_af_windows"] + cur["mitdb"]["false_af_windows"],
            "false_af_baseline": base["afdb"]["false_af_windows"] + base["mitdb"]["false_af_windows"],
        }
        ok = (checks["afdb_af_se_drop"] <= 0.02 and checks["mitdb_af_se_drop"] <= 0.02 and checks["worst_patient_af_se_drop"] <= 0.10
              and checks["cinc_val_f1_drop"] <= 0.01 and checks["false_af"] < checks["false_af_baseline"])
        rows.append({"version": c, "passes": ok, **checks})
        if ok:
            passing.append((checks["false_af"], c))
    chosen = min(passing)[1] if passing else baseline
    result = _meta(task="rhythm_selection", rule=SELECTION_RULE, baseline=baseline, candidates=rows, chosen=chosen)
    _write("rhythm_selection", result)
    print(json.dumps({"chosen": chosen, "candidates": rows}, indent=1, default=float), flush=True)
    return result
