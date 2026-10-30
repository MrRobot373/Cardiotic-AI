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
    # v0.3: v0.2 became lenient on real noisy handheld recordings (validation), so it also sees
    # windows from CinC train-split recordings labelled "too noisy" as noisy examples.
    "v0.3": {"extra_p": 0.3, "low_amp_p": 0.3, "real_noisy_p": 0.1, "epochs": 10},
    # v0.4 / v0.5 target 12-lead ECGs: v0.3 rated 19% of leads in un-annotated PTB-XL validation
    # ECGs noisy (limb leads up to 46%), driven by high-frequency hiss on low-amplitude leads.
    # v0.4: v0.3 recipe on 40 Hz low-passed input. v0.5: also clean 12-lead PTB-XL leads (training
    # folds, records without any technician noise note) as bases, clean and with injected noise.
    "v0.4": {"extra_p": 0.3, "low_amp_p": 0.3, "real_noisy_p": 0.1, "epochs": 10, "lowpass_hz": 40},
    "v0.5": {"extra_p": 0.3, "low_amp_p": 0.3, "real_noisy_p": 0.1, "epochs": 10, "lowpass_hz": 40, "ptbxl_p": 0.4},
}
# Pre-declared before any v0.4/v0.5 result was seen. A candidate replaces v0.3 only if, on
# VALIDATION data, all hold (v0.3's own value as reference):
QUALITY_12_RULE = {
    "ptbxl_clean_leads_not_good_max": 0.05,         # PTB-XL fold 9, ECGs without noise notes (v0.3: 0.188)
    "ptbxl_synthetic_unusable_se_drop_max": 0.02,   # PTB-XL fold 9 leads with injected noise / failures
    "ptbxl_synthetic_not_good_se_drop_max": 0.02,
    "mitdb_val_macro_f1_drop_max": 0.02,            # Holter use must not get worse
    "cinc_noisy_not_good_drop_max": 0.05,           # CinC 'too noisy' windows rated noisy or unusable
    "cinc_clean_unusable_rise_max": 0.005,          # CinC normal / AF / other windows rated unusable
    "ptbxl_note_auc_drop_max": 0.03,                # technician noise notes (weak labels)
    "tie_break": "lowest PTB-XL clean-lead not-good rate; equal within 0.5 points -> the simpler recipe (v0.4)",
}
QUALITY_12_CANDIDATES = ("v0.4", "v0.5")
# Neither retrained candidate met the clean-lead rule (v0.4 14.8%, v0.5 15.3%: limb leads still flagged).
# v0.6 = v0.3's weights unchanged, input low-passed at 40 Hz (no retraining). It was suggested by a diagnostic
# run on 300 validation-fold ECGs, so validation is not independent for it: it must pass QUALITY_12_RULE on
# validation AND, scored once, the confirmation below on the PTB-XL test fold.
QUALITY_V06_TEST_CONFIRMATION = {"ptbxl_clean_leads_not_good_max": 0.05, "ptbxl_synthetic_unusable_se_drop_max": 0.02,
                                 "ptbxl_synthetic_not_good_se_drop_max": 0.02}
QUALITY_VAL_PATIENTS = [106, 118, 207, 220]


def _cinc_quality_bases(records: list[str], signals: dict[str, np.ndarray], lowpass_hz: float | None = None) -> np.ndarray:
    from cardiotic_ml.data import cinc2017
    return np.concatenate([q_data.signal_windows(signals[r], cinc2017.FS, lowpass_hz) for r in records])


def _ptbxl_lead_windows(folds: tuple[int, ...], max_records: int | None = None, seed: int = 0) -> dict:
    """Raw (not preprocessed) 2.5 s windows at 360 Hz of every lead of PTB-XL 500 Hz records:
    {"x": (records, 12, 4, WIN), "note": (records, 12) technician noise note, "ecg_id": ...}. Cached."""
    from cardiotic_ml import dsp
    from cardiotic_ml.data import ptbxl, ptbxl_noise

    tag = "-".join(map(str, folds)) + (f"_n{max_records}_s{seed}" if max_records else "")
    cache = Path(__file__).resolve().parents[1] / "cache" / f"ptbxl_quality_windows_{tag}.npz"
    if cache.exists():
        d = np.load(cache)
        return {"x": d["x"].astype(np.float32), "note": d["note"], "ecg_id": d["ecg_id"]}
    recs = ptbxl.split(folds)
    if max_records:
        rng = np.random.default_rng(seed)
        recs = [recs[i] for i in sorted(rng.choice(len(recs), min(max_records, len(recs)), replace=False))]
    xs, notes = [], []
    for r in recs:
        sig = dsp.resample(ptbxl.load_signal(r, hr=True), 500, q_data.FS)
        xs.append(np.stack([q_data.raw_windows(lead)[1] for lead in sig]))
        notes.append(ptbxl_noise.any_note(r.ecg_id))
    out = {"x": np.stack(xs).astype(np.float32), "note": np.stack(notes), "ecg_id": np.array([r.ecg_id for r in recs])}
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, x=out["x"].astype(np.float16), note=out["note"], ecg_id=out["ecg_id"])
    return out


def _clean_ptbxl_bases(d: dict) -> np.ndarray:
    """Median-removed windows of every lead of records with no technician noise note."""
    w = d["x"][~d["note"].any(1)].reshape(-1, q_data.WIN)
    return w - np.median(w, axis=1, keepdims=True)


@torch.no_grad()
def quality_12lead(model: QualityNet, d: dict, lowpass_hz: float | None) -> dict:
    """How a quality model rates real 12-lead leads (PTB-XL), with the analysis path's per-lead rule
    (unusable if most windows are unusable, noisy if most are noisy or unusable)."""
    from sklearn.metrics import roc_auc_score

    from cardiotic_ml.data.ptbxl import LEADS
    model.eval()
    n, L, W, _ = d["x"].shape
    w = np.clip(q_data.preprocess(d["x"].reshape(-1, q_data.WIN), lowpass_hz), -10, 10)
    p = predict(model, (torch.from_numpy(w),)).reshape(n, L, W, 3)
    a = p.argmax(-1)
    lab = np.where((a == 2).mean(-1) > 0.5, 2, np.where((a >= 1).mean(-1) > 0.5, 1, 0))
    clean = ~d["note"].any(1)
    cl = lab[clean]
    return {"records": int(n), "records_without_notes": int(clean.sum()),
            "clean_leads_not_good": float((cl >= 1).mean()), "clean_leads_unusable": float((cl == 2).mean()),
            "clean_ecgs_with_a_not_good_lead": float((cl >= 1).any(1).mean()),
            "clean_ecgs_with_an_unusable_lead": float((cl == 2).any(1).mean()),
            "clean_not_good_by_lead": {ld: float(v) for ld, v in zip(LEADS, (cl >= 1).mean(0))},
            "noted_leads_not_good": float((lab[d["note"]] >= 1).mean()),
            "note_auc": float(roc_auc_score(d["note"].ravel(), p[..., 1:].sum(-1).mean(-1).ravel()))}


def _synthetic_scores(model: QualityNet, s: q_data.QualitySet) -> dict:
    pred = predict(model, (torch.from_numpy(s.x),)).argmax(1)
    rep = class_report(s.y, pred, q_data.LABELS)
    return {"macro_f1": rep["macro_f1"], "unusable_sensitivity": float((pred[s.y == 2] == 2).mean()),
            "not_good_sensitivity": float((pred[s.y >= 1] >= 1).mean()), "good_kept": float((pred[s.y == 0] == 0).mean())}


@torch.no_grad()
def rate_windows(model: QualityNet, windows: np.ndarray) -> np.ndarray:
    model.eval()
    if len(windows) == 0:
        return np.zeros(0, dtype=np.int64)
    return model(torch.from_numpy(np.clip(windows, -10, 10))).argmax(1).numpy()


def quality_real_data(model: QualityNet, split: str, signals: dict[str, np.ndarray] | None = None,
                      lowpass_hz: float | None = None) -> dict:
    """Real expert-labelled check (CinC 2017): share of windows rated good / noisy / unusable for
    normal, AF, other-rhythm and 'too noisy' recordings — the last one should be rated badly,
    the other three should not. For split='test' also the MIT-BIH DS2 AF / flutter records."""
    from cardiotic_ml.data import cinc2017
    signals = signals if signals is not None else cinc2017.load_all()
    ref = dict(cinc2017.reference())
    out = {}
    for lab in cinc2017.LABELS:
        recs = [r for r in cinc2017.split()[split] if ref[r] == lab]
        pred = rate_windows(model, _cinc_quality_bases(recs, signals, lowpass_hz))
        out[f"cinc_{lab}"] = {q: float(np.mean(pred == i)) for i, q in enumerate(q_data.LABELS)} | {"windows": int(len(pred))}
    if split == "test":
        for rid in (201, 203, 210, 219, 221, 222):  # all have AF; 222 also flutter and low amplitude
            if rid in mitdb.DS2:
                rec = mitdb.load_record(rid)
                pred = rate_windows(model, q_data.signal_windows(rec.signal, rec.fs, lowpass_hz))
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
    real_noisy = None
    if spec.get("real_noisy_p"):
        real_noisy = _cinc_quality_bases([r for r in cinc2017.split()["train"] if ref[r] == "~"], signals)
    lp = spec.get("lowpass_hz")
    print(f"building quality datasets… ({version}: {spec})", flush=True)
    n_ptb = int(n_train * spec.get("ptbxl_p", 0.0))
    tr = q_data.build(train_ids, pool_train, n_train - n_ptb, seed=1, extra_clean=extra, extra_p=spec["extra_p"], low_amp_p=spec["low_amp_p"],
                      real_noisy=real_noisy, real_noisy_p=spec.get("real_noisy_p", 0.0), lowpass_hz=lp)
    if n_ptb:
        from cardiotic_ml.data import ptbxl
        ptb = q_data.build(None, pool_train, n_ptb, seed=5, low_amp_p=spec["low_amp_p"], lowpass_hz=lp,
                           bases=_clean_ptbxl_bases(_ptbxl_lead_windows(ptbxl.TRAIN_FOLDS, max_records=3000, seed=1)))
        tr = q_data.QualitySet(np.concatenate([tr.x, ptb.x]), np.concatenate([tr.y, ptb.y]), np.concatenate([tr.kind, "ptbxl:" + ptb.kind]))
    va = q_data.build(val_ids, pool_train, n_val, seed=2, lowpass_hz=lp)
    te = q_data.build(mitdb.DS2, pool_test, n_test, seed=3, lowpass_hz=lp)
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
        "input": "900 samples @ 360 Hz, millivolts" + (f", {lp:g} Hz low-pass (zero-phase)" if lp else "") + ", median removed",
        "labels": q_data.LABELS,
        "intended_use": "Research use only. Gate for downstream analysis; not validated on clinical data.",
        "train_patients": train_ids, "val_patients": val_ids, "test_patients": mitdb.DS2,
        "noise_split": "NSTDB bw/em/ma: first 60% of each recording train, last 40% test",
        "label_source": "proxy labels from known injected SNR and synthetic failure modes (see quality/dataset.py)"
                        + ("; extra good bases from CinC 2017 train-split AF / other-rhythm records" if extra is not None else "")
                        + ("; real noisy windows from CinC 2017 train-split 'too noisy' records" if real_noisy is not None else "")
                        + ("; clean 12-lead leads from PTB-XL training folds (records without technician noise notes)" if n_ptb else ""),
    })
    print("real-data checks…", flush=True)
    result = _meta(task="signal_quality", version=version, sizes={"train": len(tr.y), "val": len(va.y), "test": len(te.y)},
                   test=rep, val=val_rep, test_accuracy_by_generator=by_kind, training=info, model_card=card,
                   real_data_val=quality_real_data(model, "val", signals, lp), real_data_test=quality_real_data(model, "test", signals, lp))
    if lp is not None:  # 12-lead checks (added with v0.4; v0.3's are computed by select_quality_12)
        result |= quality_12_checks(model, lp)
    _write(f"signal_quality_{version}", result)
    print(json.dumps({k: rep[k] for k in ("accuracy", "macro_f1")}), flush=True)
    return result


def quality_12_checks(model: QualityNet, lp: float | None) -> dict:
    """Validation (PTB-XL fold 9) and test (fold 10) checks on real 12-lead ECGs: technician notes
    and clean leads, plus injected noise on clean 12-lead leads (NSTDB train / test noise split)."""
    from cardiotic_ml.data import ptbxl
    pool_train, pool_test = q_data.noise_pools()
    out = {}
    for split, folds, pool, seed in (("val", ptbxl.VAL_FOLDS, pool_train, 4), ("test", ptbxl.TEST_FOLDS, pool_test, 6)):
        d = _ptbxl_lead_windows(folds)
        syn = q_data.build(None, pool, 5000, seed=seed, bases=_clean_ptbxl_bases(d), lowpass_hz=lp)
        out[f"ptbxl_{split}"] = quality_12lead(model, d, lp) | {"synthetic": _synthetic_scores(model, syn)}
    return out


def _load_quality(version: str) -> tuple[QualityNet, dict]:
    card = json.loads((ARTIFACTS_DIR / f"quality_net_{version}.card.json").read_text())
    model = QualityNet(len(q_data.LABELS))
    model.load_state_dict(torch.load(ARTIFACTS_DIR / f"quality_net_{version}.pt", weights_only=True))
    return model, card


def make_quality_v06() -> None:
    """v0.6: copy of v0.3's weights with a 40 Hz input low-pass recorded in its card."""
    import shutil
    card = json.loads((ARTIFACTS_DIR / "quality_net_v0.3.card.json").read_text())
    shutil.copy(ARTIFACTS_DIR / "quality_net_v0.3.pt", ARTIFACTS_DIR / "quality_net_v0.6.pt")
    card.update(version="v0.6", file="quality_net_v0.6.pt", recipe={**card["recipe"], "lowpass_hz": 40, "weights_from": "v0.3"},
                input="900 samples @ 360 Hz, millivolts, 40 Hz low-pass (zero-phase), median removed")
    (ARTIFACTS_DIR / "quality_net_v0.6.card.json").write_text(json.dumps(card, indent=1))


def select_quality_12(current: str = "v0.3", candidates: tuple[str, ...] = QUALITY_12_CANDIDATES, name: str = "quality_selection") -> dict:
    """Apply QUALITY_12_RULE to the candidates on validation data only; writes reports/quality_selection.json."""
    from cardiotic_ml.data import cinc2017
    rule = QUALITY_12_RULE
    pool_train, _ = q_data.noise_pools()
    signals = cinc2017.load_all()
    rows = {}
    for v in (current, *candidates):
        if v == "v0.6" and not (ARTIFACTS_DIR / "quality_net_v0.6.pt").exists():
            make_quality_v06()
        if not (ARTIFACTS_DIR / f"quality_net_{v}.pt").exists():
            train_quality(v)
        model, card = _load_quality(v)
        lp = q_data.lowpass_of(card)
        val12 = quality_12_checks(model, lp)["ptbxl_val"]
        real = quality_real_data(model, "val", signals, lp)
        mit = _synthetic_scores(model, q_data.build(QUALITY_VAL_PATIENTS, pool_train, 5000, seed=2, lowpass_hz=lp))
        rows[v] = {"ptbxl_clean_leads_not_good": val12["clean_leads_not_good"],
                   "ptbxl_clean_ecgs_with_a_not_good_lead": val12["clean_ecgs_with_a_not_good_lead"],
                   "ptbxl_synthetic_unusable_se": val12["synthetic"]["unusable_sensitivity"],
                   "ptbxl_synthetic_not_good_se": val12["synthetic"]["not_good_sensitivity"],
                   "ptbxl_note_auc": val12["note_auc"], "mitdb_val_macro_f1": mit["macro_f1"],
                   "cinc_noisy_not_good": 1 - real["cinc_~"]["good"],
                   "cinc_clean_unusable": float(np.mean([real[f"cinc_{k}"]["unusable"] for k in "NAO"]))}
    ref = rows[current]
    passed = {}
    for v in candidates:
        c = rows[v]
        checks = {
            "ptbxl_clean_leads_not_good": c["ptbxl_clean_leads_not_good"] <= rule["ptbxl_clean_leads_not_good_max"],
            "ptbxl_synthetic_unusable_se": c["ptbxl_synthetic_unusable_se"] >= ref["ptbxl_synthetic_unusable_se"] - rule["ptbxl_synthetic_unusable_se_drop_max"],
            "ptbxl_synthetic_not_good_se": c["ptbxl_synthetic_not_good_se"] >= ref["ptbxl_synthetic_not_good_se"] - rule["ptbxl_synthetic_not_good_se_drop_max"],
            "mitdb_val_macro_f1": c["mitdb_val_macro_f1"] >= ref["mitdb_val_macro_f1"] - rule["mitdb_val_macro_f1_drop_max"],
            "cinc_noisy_not_good": c["cinc_noisy_not_good"] >= ref["cinc_noisy_not_good"] - rule["cinc_noisy_not_good_drop_max"],
            "cinc_clean_unusable": c["cinc_clean_unusable"] <= ref["cinc_clean_unusable"] + rule["cinc_clean_unusable_rise_max"],
            "ptbxl_note_auc": c["ptbxl_note_auc"] >= ref["ptbxl_note_auc"] - rule["ptbxl_note_auc_drop_max"],
        }
        passed[v] = {"checks": checks, "passed": all(checks.values())}
    ok = [v for v in candidates if passed[v]["passed"]]
    chosen = current
    if ok:
        best = min(ok, key=lambda v: rows[v]["ptbxl_clean_leads_not_good"])
        simple = ok[0]  # candidates are listed simplest first
        chosen = simple if rows[simple]["ptbxl_clean_leads_not_good"] - rows[best]["ptbxl_clean_leads_not_good"] <= 0.005 else best
    test = None
    if "v0.6" in ok:  # confirmation on the test fold, scored once
        conf = QUALITY_V06_TEST_CONFIRMATION
        t = {v: quality_12_checks(_load_quality(v)[0], q_data.lowpass_of(_load_quality(v)[1]))["ptbxl_test"] for v in (current, "v0.6")}
        checks = {"ptbxl_clean_leads_not_good": t["v0.6"]["clean_leads_not_good"] <= conf["ptbxl_clean_leads_not_good_max"],
                  "ptbxl_synthetic_unusable_se": t["v0.6"]["synthetic"]["unusable_sensitivity"] >= t[current]["synthetic"]["unusable_sensitivity"] - conf["ptbxl_synthetic_unusable_se_drop_max"],
                  "ptbxl_synthetic_not_good_se": t["v0.6"]["synthetic"]["not_good_sensitivity"] >= t[current]["synthetic"]["not_good_sensitivity"] - conf["ptbxl_synthetic_not_good_se_drop_max"]}
        test = {"rule": conf, "results": t, "checks": checks, "passed": all(checks.values())}
        if not test["passed"]:
            ok.remove("v0.6")
            chosen = current if not ok else chosen if chosen != "v0.6" else ok[0]
    result = _meta(task="quality_selection_12lead", rule=rule, current=current, validation=rows, candidates=passed, chosen=chosen,
                   test_confirmation=test)
    _write(name, result)
    print(json.dumps({"chosen": chosen, "validation": rows}, indent=1), flush=True)
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
