"""M4 experiments on PTB-XL: 12-lead statement model and interval measurements.

Splits are PTB-XL's official patient-wise folds: 1–8 train, 9 validation, 10 test. Every choice
(epoch, temperature, per-statement thresholds, measurement thresholds) is made on training or
validation folds; fold 10 is scored once per version.
"""

from __future__ import annotations

import copy
import itertools
import json
import time
from dataclasses import asdict

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch import nn

from cardiotic_ml import dsp
from cardiotic_ml.data import ptbxl
from cardiotic_ml.ecg12 import measure as ms
from cardiotic_ml.ecg12.model import ECG12Net
from cardiotic_ml.experiments import _meta, _save_model, _write
from cardiotic_ml.paths import REPORTS_DIR
from cardiotic_ml.train_utils import set_seed

FS_LR = 100
CROP = 900                    # training crop (9 s); validation / test use the full 10 s
KEY_STATEMENTS = ["NORM", "IMI", "ASMI", "AMI", "LVH", "CLBBB", "CRBBB", "IRBBB", "LAFB", "1AVB", "WPW",
                  "NDT", "ISCAL", "LNGQT", "AFIB", "AFLT", "STACH", "SBRAD", "SARRH", "PVC", "PACE"]
ECG12_VERSIONS = {"v0.1": {"epochs": 30, "width": 64, "lr": 1e-3, "weight_decay": 1e-2, "batch": 128}}
DATASET = "PhysioNet PTB-XL 1.0.3 (CC BY 4.0)"
DATASET_PLUS = "PhysioNet PTB-XL+ 1.0.1 (CC BY 4.0): GE 12SL and Uni-G measurements"


def label_space() -> tuple[list[str], list[str]]:
    """Output columns: the 71 SCP statements, then the 5 diagnostic superclasses."""
    return ptbxl.all_statements(), [f"SUPER_{c}" for c in ptbxl.SUPERCLASSES]


def targets(recs: list[ptbxl.Record], stmts: list[str]) -> np.ndarray:
    y = np.zeros((len(recs), len(stmts) + len(ptbxl.SUPERCLASSES)), dtype=np.float32)
    col = {c: i for i, c in enumerate(stmts)}
    for i, r in enumerate(recs):
        for c in r.codes:
            if c in col:
                y[i, col[c]] = 1
        for s in ptbxl.superclasses(r):
            y[i, len(stmts) + ptbxl.SUPERCLASSES.index(s)] = 1
    return y


def preprocess(x: np.ndarray) -> np.ndarray:
    """(n, 12, 1000) mV -> diagnostic band-pass (0.05 Hz – 0.45·fs), the same for every input device."""
    return dsp.bandpass(x, FS_LR, "diagnostic")


def _augment(xb: torch.Tensor, rng: np.random.Generator) -> torch.Tensor:
    n, _, L = xb.shape
    starts = rng.integers(0, L - CROP + 1, n)
    out = torch.stack([xb[i, :, s:s + CROP] for i, s in enumerate(starts)])
    scale = torch.from_numpy(rng.uniform(0.85, 1.15, (n, 1, 1)).astype(np.float32))
    return out * scale + 0.02 * torch.randn_like(out)


@torch.no_grad()
def _logits(model: nn.Module, x: np.ndarray, batch: int = 256) -> np.ndarray:
    model.eval()
    return np.concatenate([model(torch.from_numpy(x[i:i + batch])).numpy() for i in range(0, len(x), batch)])


def macro_auc(y: np.ndarray, p: np.ndarray, cols: list[int] | None = None) -> float:
    cols = range(y.shape[1]) if cols is None else cols
    aucs = [roc_auc_score(y[:, j], p[:, j]) for j in cols if 0 < y[:, j].sum() < len(y)]
    return float(np.mean(aucs)) if aucs else float("nan")


def fit_temperature_binary(logits: np.ndarray, y: np.ndarray) -> float:
    lt, yt = torch.from_numpy(logits.astype(np.float32)), torch.from_numpy(y.astype(np.float32))
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

    def closure():
        opt.zero_grad()
        loss = nn.functional.binary_cross_entropy_with_logits(lt / log_t.exp(), yt)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.detach().exp())


def binary_ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    p, y = p.ravel(), y.ravel()
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean() for b in range(bins) if (idx == b).any()))


def f1_thresholds(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    grid = np.linspace(0.02, 0.98, 49)
    th = np.full(y.shape[1], 0.5)
    for j in range(y.shape[1]):
        if y[:, j].sum() == 0:
            continue
        pred = p[:, j][:, None] >= grid[None]
        tp = (pred & (y[:, j][:, None] == 1)).sum(0)
        f1 = 2 * tp / (pred.sum(0) + y[:, j].sum() + 1e-9)
        th[j] = grid[int(f1.argmax())]
    return th


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def _task_cols(stmts: list[str]) -> dict[str, list[int]]:
    st = ptbxl.statements()
    n = len(stmts)
    return {"all": list(range(n)),
            "diagnostic": [i for i, c in enumerate(stmts) if st[c]["diagnostic"]],
            "form": [i for i, c in enumerate(stmts) if st[c]["form"]],
            "rhythm": [i for i, c in enumerate(stmts) if st[c]["rhythm"]],
            "superclass": list(range(n, n + len(ptbxl.SUPERCLASSES)))}


def _bootstrap_auc(y, p, cols, n_boot=200, seed=0) -> list[float]:
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        vals.append(macro_auc(y[i], p[i], cols))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def train_ecg12(version: str = "v0.1") -> dict:
    spec = ECG12_VERSIONS[version]
    set_seed(7)
    rng = np.random.default_rng(7)
    recs = ptbxl.records()
    print("loading PTB-XL 100 Hz…", flush=True)
    x = preprocess(ptbxl.load_all_lr())
    folds = np.array([r.fold for r in recs])
    tr, va, te = (np.isin(folds, f) for f in (ptbxl.TRAIN_FOLDS, ptbxl.VAL_FOLDS, ptbxl.TEST_FOLDS))
    stmts, supers = label_space()
    y = targets(recs, stmts)
    mean = x[tr].mean(axis=(0, 2), keepdims=True)
    std = x[tr].std(axis=(0, 2), keepdims=True) + 1e-6
    x = ((x - mean) / std).astype(np.float32)
    xtr, ytr = torch.from_numpy(x[tr]), torch.from_numpy(y[tr])
    model = ECG12Net(y.shape[1], width=spec["width"])
    opt = torch.optim.AdamW(model.parameters(), lr=spec["lr"], weight_decay=spec["weight_decay"])
    steps = spec["epochs"] * int(np.ceil(tr.sum() / spec["batch"]))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=spec["lr"], total_steps=steps)
    loss_fn = nn.BCEWithLogitsLoss()
    best, best_auc, history = None, -1.0, []
    for epoch in range(spec["epochs"]):
        model.train()
        t0, total = time.time(), 0.0
        order = torch.from_numpy(rng.permutation(len(xtr)))
        for i in range(0, len(order), spec["batch"]):
            idx = order[i:i + spec["batch"]]
            opt.zero_grad()
            loss = loss_fn(model(_augment(xtr[idx], rng)), ytr[idx])
            loss.backward()
            opt.step(); sched.step()
            total += loss.item() * len(idx)
        auc = macro_auc(y[va], _sigmoid(_logits(model, x[va])))
        history.append({"epoch": epoch + 1, "train_loss": total / tr.sum(), "val_macro_auc": auc,
                        "seconds": round(time.time() - t0, 1)})
        print(f"epoch {epoch + 1:2d}  loss {total / tr.sum():.4f}  val macro-AUC {auc:.4f}  ({time.time() - t0:.0f}s)", flush=True)
        if auc > best_auc:
            best_auc, best = auc, copy.deepcopy(model.state_dict())
    model.load_state_dict(best)

    val_logits, test_logits = _logits(model, x[va]), _logits(model, x[te])
    temperature = fit_temperature_binary(val_logits, y[va])
    pv, pt = _sigmoid(val_logits / temperature), _sigmoid(test_logits / temperature)
    th = f1_thresholds(y[va], pv)
    cols = _task_cols(stmts)
    labels = stmts + supers
    yt = y[te]
    test_tasks = {k: {"macro_auc": macro_auc(yt, pt, c), "ci95": _bootstrap_auc(yt, pt, c),
                      "n_labels": sum(1 for j in c if 0 < yt[:, j].sum() < len(yt))} for k, c in cols.items()}
    val_tasks = {k: macro_auc(y[va], pv, c) for k, c in cols.items()}
    per_label = {}
    for j, name in enumerate(labels):
        pos = yt[:, j] == 1
        pred = pt[:, j] >= th[j]
        if pos.sum() == 0:
            continue
        per_label[name] = {"support": int(pos.sum()), "auc": float(roc_auc_score(yt[:, j], pt[:, j])) if pos.sum() < len(yt) else None,
                           "threshold": float(th[j]), "sensitivity": float(pred[pos].mean()),
                           "specificity": float((~pred[~pos]).mean()), "ppv": float(pred[pos].sum() / max(pred.sum(), 1)),
                           "description": ptbxl.statements().get(name, {}).get("description", name)}
    # subgroups (fairness): superclass macro-AUC by sex and age band on the test fold
    trec = [r for r, m in zip(recs, te) if m]
    groups = {"female": [r.sex == 1 for r in trec], "male": [r.sex == 0 for r in trec],
              "age <40": [r.age is not None and r.age < 40 for r in trec],
              "age 40–65": [r.age is not None and 40 <= r.age <= 65 for r in trec],
              "age >65": [r.age is not None and 65 < r.age < 300 for r in trec]}
    subgroups = {g: {"n": int(np.sum(m)), "superclass_macro_auc": macro_auc(yt[np.array(m)], pt[np.array(m)], cols["superclass"])}
                 for g, m in groups.items()}
    calib = {"temperature": temperature, "ece_before": binary_ece(_sigmoid(test_logits), yt), "ece_after": binary_ece(pt, yt)}
    card = _save_model(model, f"ecg12_net_{version}", {
        "name": "ecg12_net", "version": version, "recipe": spec, "labels": labels,
        "task": "10 s 12-lead ECG -> probability of each SCP-ECG statement (multi-label) and of 5 diagnostic superclasses",
        "input": f"12 x 1000 samples @ {FS_LR} Hz, leads {ptbxl.LEADS}, mV; diagnostic band-pass, then per-lead standardisation",
        "lead_mean": mean.ravel().tolist(), "lead_std": std.ravel().tolist(), "temperature": temperature,
        "thresholds": dict(zip(labels, map(float, th))),
        "threshold_rule": "per statement, maximise F1 on validation fold 9",
        "intended_use": "Research use only. Not validated on clinical ECG machines.",
        "data": f"{DATASET}: folds 1–8 train ({int(tr.sum())} ECGs), 9 validation, 10 test; patient-wise folds",
    })
    result = _meta(task="ecg12_statements", version=version, sizes={"train": int(tr.sum()), "val": int(va.sum()), "test": int(te.sum())},
                   val=val_tasks, test=test_tasks, per_label=per_label, subgroups=subgroups, calibration=calib,
                   training={"history": history, "best_val_macro_auc": best_auc}, model_card=card,
                   benchmark_note="Published PTB-XL benchmark (Strodthoff et al. 2021, separate model per task): macro-AUC "
                                  "all 0.925, diagnostic 0.937, form 0.896, rhythm 0.957, superclass 0.930 (best models).")
    result["datasets"] = {"ptbxl": DATASET}
    _write(f"ecg12_statements_{version}", result)
    print(json.dumps({k: round(v["macro_auc"], 4) for k, v in test_tasks.items()}), flush=True)
    return result


# ---------------------------------------------------------------- interval measurements
MEASURE_KEYS = {  # ours -> PTB-XL+ column
    "heart_rate_bpm": "HR__Global", "pr_ms": "PR_Int_Global", "qrs_ms": "QRS_Dur_Global", "qt_ms": "QT_Int_Global",
    "qtc_bazett_ms": "QT_IntBazett_Global", "qrs_axis_deg": "QRS_AXIS", "t_axis_deg": "T_AxisFront_Global",
}
# IEC 60601-2-25 orientation: acceptable mean difference / SD vs the CSE referee (CSE database, not PTB-XL)
IEC_TOLERANCE_MS = {"pr_ms": (10, 10), "qrs_ms": (6, 10), "qt_ms": (12, 30)}
# v0.1: one grid, objective = median |difference| (QRS/10 + PR/10 + QT/30). Scored on test once; large misses
# in wide QRS, low P and flat T waves (RESULTS.md section 7). v0.2: new rules (QRS core + velocity minimum,
# T end capped after the tangent, P search window), staged search, objective in the IEC terms (mean and SD).
ADOPTED_MEASURE = "v0.2"  # chosen on validation fold 9 (lower SD for QRS, PR and QT; means within IEC orientation)
MEASURE_VERSIONS = {
    "v0.1": {"grid": {"qrs_on": (0.02, 0.03, 0.05, 0.08), "qrs_off": (0.03, 0.05, 0.08, 0.12), "p_frac": (0.05, 0.1, 0.2),
                      "t_frac": (None, 0.03, 0.05, 0.07, 0.1)}, "objective": "median"},
    "v0.2": {"stages": [{"qrs_core": (None, 0.1, 0.15), "qrs_on": (0.02, 0.03, 0.05), "qrs_off": (0.03, 0.05, 0.08)},
                        {"t_frac": (None, 0.03, 0.05), "t_cap_ms": (None, 20, 30, 40)},
                        {"p_frac": (None, 0.1, 0.2), "p_search_ms": (300, 350, 400)}], "objective": "iec"},
}
TUNE_N = 1000


def _ref_value(ref: dict, key: str) -> float | None:
    col = MEASURE_KEYS[key]
    if col == "QRS_AXIS":  # 12SL publishes the frontal QRS axis as R_AxisFrontal, Uni-G as QRS_AxisFront
        v = ref.get("QRS_AxisFront_Global", ref.get("R_AxisFrontal_Global"))
    else:
        v = ref.get(col)
    if v is None or v != v:
        return None
    if key in ("pr_ms", "qrs_ms", "qt_ms", "qtc_bazett_ms") and v <= 0:
        return None
    return v


def _diff(key: str, a: float, b: float) -> float:
    d = a - b
    return (d + 180) % 360 - 180 if key.endswith("_deg") else d


def _agreement(pairs: dict[str, list[tuple[float, float]]]) -> dict:
    out = {}
    for key, ab in pairs.items():
        if not ab:
            continue
        d = np.array([_diff(key, a, b) for a, b in ab])
        tol = 10 if key in ("pr_ms", "qrs_ms") else 20 if key.endswith("_ms") else 5 if key == "heart_rate_bpm" else 30
        out[key] = {"n": len(d), "mean_diff": float(d.mean()), "sd_diff": float(d.std()),
                    "median_abs": float(np.median(np.abs(d))), "within": tol, "share_within": float(np.mean(np.abs(d) <= tol))}
    return out


def _median_beats(recs: list[ptbxl.Record]) -> dict[int, ms.MedianBeat | None]:
    out = {}
    for i, r in enumerate(recs):
        out[r.ecg_id] = ms.median_beat(ptbxl.load_signal(r, hr=True), 500)
        if (i + 1) % 250 == 0:
            print(f"  median beats {i + 1}/{len(recs)}", flush=True)
    return out


def _errors(mbs: dict, recs: list, ref: dict, p: ms.Params) -> dict[str, np.ndarray]:
    err = {"qrs_ms": [], "pr_ms": [], "qt_ms": []}
    for r in recs:
        mb, rv = mbs[r.ecg_id], ref.get(r.ecg_id, {})
        if mb is None:
            continue
        m = ms.delineate(mb, p)
        for k in err:
            b = _ref_value(rv, k)
            if m[k] is not None and b is not None:
                err[k].append(m[k] - b)
    return {k: np.array(v) for k, v in err.items()}


def _score(err: dict[str, np.ndarray], objective: str) -> float:
    if objective == "median":
        return sum(float(np.median(np.abs(err[k]))) / IEC_TOLERANCE_MS[k][1] for k in err)
    return sum(abs(float(err[k].mean())) / IEC_TOLERANCE_MS[k][0] + float(err[k].std()) / IEC_TOLERANCE_MS[k][1] for k in err)


def _row(params: dict, err: dict) -> dict:
    return {**params, **{f"{k}_{stat}": float(f(v)) for k, v in err.items()
                         for stat, f in (("mean", np.mean), ("sd", np.std), ("median_abs", lambda x: np.median(np.abs(x))))}}


def tune_measurements(version: str = "v0.2") -> dict:
    """Choose Params on TUNE_N training-fold ECGs against 12SL (never on validation or test folds)."""
    spec = MEASURE_VERSIONS[version]
    rng = np.random.default_rng(0)
    pool = ptbxl.split(ptbxl.TRAIN_FOLDS)
    recs = [pool[i] for i in rng.choice(len(pool), TUNE_N, replace=False)]
    ref = ptbxl.reference_measurements("12sl")
    mbs = _median_beats(recs)
    rows, chosen = [], {}
    for stage in spec.get("stages", [spec.get("grid")]):
        best, best_score = None, np.inf
        for values in itertools.product(*stage.values()):
            trial = {**chosen, **dict(zip(stage, values))}
            err = _errors(mbs, recs, ref, ms.Params(**trial))
            sc = _score(err, spec["objective"])
            rows.append({**_row(trial, err), "score": sc})
            if sc < best_score:
                best, best_score = trial, sc
        chosen = best
    params = asdict(ms.Params(**chosen))
    result = _meta(task="ecg12_measurement_tuning", version=version, n_records=len(recs), spec=spec,
                   objective=("sum over QRS, PR, QT of |mean diff| / IEC mean tolerance + SD / IEC SD tolerance"
                              if spec["objective"] == "iec" else "sum over QRS, PR, QT of median |diff| / IEC SD tolerance")
                             + " vs 12SL; training folds only",
                   rows=rows, chosen=params, chosen_row=min(rows, key=lambda r: r["score"]))
    result["datasets"] = {"ptbxl": DATASET, "ptbxl_plus": DATASET_PLUS}
    _write(f"ecg12_measurement_tuning_{version}", result)
    print(json.dumps(result["chosen_row"]), flush=True)
    return result


def eval_measurements(version: str = "v0.2", split: str = "val") -> dict:
    """Agreement with 12SL and Uni-G on validation fold 9 or test fold 10; 12SL-vs-Uni-G is the yardstick."""
    tuned = json.loads((REPORTS_DIR / f"ecg12_measurement_tuning_{version}.json").read_text())["chosen"]
    p = ms.Params(**{k: v for k, v in tuned.items() if k in ms.Params.__dataclass_fields__})
    recs = ptbxl.split(ptbxl.TEST_FOLDS if split == "test" else ptbxl.VAL_FOLDS)
    r12, rug = ptbxl.reference_measurements("12sl"), ptbxl.reference_measurements("unig")
    pairs = {name: {k: [] for k in MEASURE_KEYS} for name in ("vs_12sl", "vs_unig", "12sl_vs_unig")}
    failed, t0 = 0, time.time()
    for i, r in enumerate(recs):
        m = ms.measure(ptbxl.load_signal(r, hr=True), 500, p)
        a, b = r12.get(r.ecg_id, {}), rug.get(r.ecg_id, {})
        for k in MEASURE_KEYS:
            va, vb = _ref_value(a, k), _ref_value(b, k)
            if va is not None and vb is not None:
                pairs["12sl_vs_unig"][k].append((va, vb))
            if not m["ok"] or m.get(k) is None:
                continue
            if va is not None:
                pairs["vs_12sl"][k].append((m[k], va))
            if vb is not None:
                pairs["vs_unig"][k].append((m[k], vb))
        failed += not m["ok"]
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(recs)}", flush=True)
    pr_found = len(pairs["vs_12sl"]["pr_ms"])
    result = _meta(task="ecg12_measurements", version=version, split=split, params=asdict(p), n_records=len(recs), failed=failed,
                   seconds_per_ecg=(time.time() - t0) / len(recs),
                   agreement={k: _agreement(v) for k, v in pairs.items()}, iec_orientation_ms=IEC_TOLERANCE_MS,
                   pr_reported_where_12sl_reports=pr_found,
                   note="12SL and Uni-G are commercial algorithms, not ground truth. IEC 60601-2-25 tolerances are "
                        "defined against the CSE referee on the CSE database; shown for orientation only.")
    result["datasets"] = {"ptbxl": DATASET, "ptbxl_plus": DATASET_PLUS}
    _write(f"ecg12_measurements_{split}_{version}", result)
    print(json.dumps({k: {kk: round(vv["mean_diff"], 1) for kk, vv in v.items()} for k, v in result["agreement"].items()}), flush=True)
    return result

