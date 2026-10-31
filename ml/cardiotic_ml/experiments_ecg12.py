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
ECG12_VERSIONS = {
    "v0.1": {"epochs": 30, "width": 64, "lr": 1e-3, "weight_decay": 1e-2, "batch": 128},
    # + Ningbo part of Chapman–Shaoxing–Ningbo (China): more flutter, PACs, bradycardia, AV block. Loss is masked:
    # Ningbo rows only teach the statements its labels map to unambiguously (data/ningbo.py).
    "v0.2": {"epochs": 20, "width": 64, "lr": 1e-3, "weight_decay": 1e-2, "batch": 128, "ningbo": True, "ningbo_map": "v0.2"},
    # v0.3: same recipe, corrected Ningbo label map (data/ningbo.py: PVC, complete/incomplete RBBB, LBBB, LAFB, pacing…)
    "v0.3": {"epochs": 20, "width": 64, "lr": 1e-3, "weight_decay": 1e-2, "batch": 128, "ningbo": True, "ningbo_map": "v0.3"},
    # v0.4: v0.3 + the sex-gap finding (reports/ecg12_sex_gap_v0.3.json: the gap is myocardial infarction; 19% of
    # training women vs 31% of men are MI-positive). PTB-XL training women with MI weigh 1.62x (= 0.308 / 0.190)
    # on the MI outputs (SUPER_MI and every MI statement).
    "v0.4": {"epochs": 20, "width": 64, "lr": 1e-3, "weight_decay": 1e-2, "batch": 128, "ningbo": True, "ningbo_map": "v0.3",
             "women_mi_weight": 1.62},
    # print-v0.1: v0.3 fine-tuned on what a printed 3x4 + lead II ECG contains (ecg12/printlayout.py), for ECGs read
    # back from paper / PDF by the digitiser. Train, validation and test data are all masked the same way.
    "print-v0.1": {"epochs": 8, "width": 64, "lr": 3e-4, "weight_decay": 1e-2, "batch": 128, "ningbo": True, "ningbo_map": "v0.3",
                   "init_from": "v0.3", "print_mask": True},
}
# Pre-declared before print-v0.1 was trained: adopt it for digitised printouts only if, on VALIDATION data masked as a
# printout, its macro-AUC (all statements) beats v0.3 on the same masked data by at least 0.03 and its superclass
# macro-AUC is at least 0.90. Otherwise digitised printouts get rhythm and measurements only, no statements.
PRINT_RULE = {"min_gain_all": 0.03, "min_superclass": 0.90}
# Pre-declared before v0.4 was trained. Adopt v0.4 over v0.3 only if, on VALIDATION data:
SEX_GAP_RULE = {
    "ptbxl_val_all_drop_max": 0.003,       # PTB-XL fold 9 macro-AUC, all statements
    "ningbo_val_drop_max": 0.005,          # Ningbo validation, mapped statements (map v0.3)
    "women_mi_auc_gain_min": 0.010,        # PTB-XL fold 9, SUPER_MI AUC in women
    "men_mi_auc_drop_max": 0.005,          # ... and in men
}
ECG12_SELECTION_RULE = ("Adopt a candidate over the current model only if, on VALIDATION data: PTB-XL macro-AUC (all "
                        "statements) drops by at most 0.005, and Ningbo-validation macro-AUC on the mapped statements "
                        "improves (both models scored with the same, current label map).")
DATASET = "PhysioNet PTB-XL 1.0.3 (CC BY 4.0)"
NINGBO_DATASET = "PhysioNet Chapman–Shaoxing–Ningbo 12-lead ECG database 1.0.0 (CC BY 4.0)"
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


def _masked_macro_auc(y: np.ndarray, p: np.ndarray, unknown: np.ndarray, cols: list[int]) -> float:
    aucs = []
    for j in cols:
        keep = unknown[:, j] == 0
        if 0 < y[keep, j].sum() < keep.sum():
            aucs.append(roc_auc_score(y[keep, j], p[keep, j]))
    return float(np.mean(aucs)) if aucs else float("nan")


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
    mtr = torch.ones_like(ytr)
    labels_all = stmts + supers
    if spec.get("women_mi_weight"):
        st = ptbxl.statements()
        mi_cols = [j for j, c in enumerate(labels_all) if c == "SUPER_MI" or (st.get(c, {}).get("diagnostic") and st[c]["diagnostic_class"] == "MI")]
        women_mi = np.array([r.sex == 1 for r, keep in zip(recs, tr) if keep]) & (y[tr, labels_all.index("SUPER_MI")] == 1)
        rows = torch.from_numpy(np.flatnonzero(women_mi))
        mtr[rows[:, None], torch.tensor(mi_cols)[None, :]] = spec["women_mi_weight"]
        print(f"women with MI in training: {int(women_mi.sum())}; weight {spec['women_mi_weight']} on {len(mi_cols)} MI outputs", flush=True)
    nb = None
    if spec.get("ningbo"):
        from cardiotic_ml.data import ningbo
        map_v = spec["ningbo_map"]
        print(f"loading Ningbo 100 Hz… (label map {map_v})", flush=True)
        nb = {}
        for part in ("train", "val", "test"):
            nrecs = ningbo.ningbo_part(part)
            xn = ((preprocess(ningbo.load_lr(nrecs)) - mean) / std).astype(np.float32)
            yn = np.zeros((len(nrecs), len(labels_all)), dtype=np.float32)
            un = np.zeros_like(yn)
            for i, r in enumerate(nrecs):
                for c in r.scp(map_v):
                    yn[i, labels_all.index(c)] = 1
                for c in r.unknown(map_v):
                    un[i, labels_all.index(c)] = 1
            nb[part] = (xn, yn, un)
        nb_cols = [labels_all.index(c) for c in ningbo.mapped(map_v)]
        mn = np.zeros_like(nb["train"][1]); mn[:, nb_cols] = 1
        mn *= 1 - nb["train"][2]
        xtr = torch.cat([xtr, torch.from_numpy(nb["train"][0])])
        ytr = torch.cat([ytr, torch.from_numpy(nb["train"][1])])
        mtr = torch.cat([mtr, torch.from_numpy(mn)])
        print(f"training ECGs: PTB-XL {int(tr.sum())} + Ningbo {len(nb['train'][1])}", flush=True)
    if spec.get("print_mask"):
        from cardiotic_ml.ecg12 import printlayout
        x = printlayout.mask(x)  # after normalisation: 0 is the lead's mean, what a blank stretch of paper reads as
        xtr = torch.from_numpy(x[tr])
        if nb:
            nb = {k: (printlayout.mask(v[0]), v[1], v[2]) for k, v in nb.items()}
            xtr = torch.cat([xtr, torch.from_numpy(nb["train"][0])])
    model = ECG12Net(y.shape[1], width=spec["width"])
    if spec.get("init_from"):
        from cardiotic_ml.paths import ARTIFACTS_DIR
        model.load_state_dict(torch.load(ARTIFACTS_DIR / f"ecg12_net_{spec['init_from']}.pt", weights_only=True))
    opt = torch.optim.AdamW(model.parameters(), lr=spec["lr"], weight_decay=spec["weight_decay"])
    steps = spec["epochs"] * int(np.ceil(len(xtr) / spec["batch"]))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=spec["lr"], total_steps=steps)
    loss_fn = nn.BCEWithLogitsLoss(reduction="none")
    best, best_auc, history = None, -1.0, []
    # resume after an interruption: everything that decides the next epoch is saved after each one
    ckpt = REPORTS_DIR.parent / "cache" / f"ecg12_net_{version}.resume.pt"
    start = 0
    if ckpt.exists():
        st = torch.load(ckpt, weights_only=False)
        model.load_state_dict(st["model"]); opt.load_state_dict(st["opt"]); sched.load_state_dict(st["sched"])
        rng.bit_generator.state = st["numpy_rng"]; torch.set_rng_state(st["torch_rng"])
        best, best_auc, history, start = st["best"], st["best_auc"], st["history"], st["epoch"]
        print(f"resuming after epoch {start}", flush=True)
    for epoch in range(start, spec["epochs"]):
        model.train()
        t0, total = time.time(), 0.0
        order = torch.from_numpy(rng.permutation(len(xtr)))
        for i in range(0, len(order), spec["batch"]):
            idx = order[i:i + spec["batch"]]
            opt.zero_grad()
            loss = (loss_fn(model(_augment(xtr[idx], rng)), ytr[idx]) * mtr[idx]).sum() / mtr[idx].sum()
            loss.backward()
            opt.step(); sched.step()
            total += loss.item() * len(idx)
        auc = macro_auc(y[va], _sigmoid(_logits(model, x[va])))
        nb_auc = _masked_macro_auc(nb["val"][1], _sigmoid(_logits(model, nb["val"][0])), nb["val"][2], nb_cols) if nb else None
        history.append({"epoch": epoch + 1, "train_loss": total / len(xtr), "val_macro_auc": auc,
                        "ningbo_val_macro_auc": nb_auc, "seconds": round(time.time() - t0, 1)})
        print(f"epoch {epoch + 1:2d}  loss {total / len(xtr):.4f}  val macro-AUC {auc:.4f}"
              + (f"  Ningbo val {nb_auc:.4f}" if nb else "") + f"  ({time.time() - t0:.0f}s)", flush=True)
        auc = auc if nb_auc is None else (auc + nb_auc) / 2
        if auc > best_auc:
            best_auc, best = auc, copy.deepcopy(model.state_dict())
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                    "numpy_rng": rng.bit_generator.state, "torch_rng": torch.get_rng_state(), "best": best,
                    "best_auc": best_auc, "history": history, "epoch": epoch + 1}, ckpt.with_suffix(".tmp"))
        ckpt.with_suffix(".tmp").replace(ckpt)
    model.load_state_dict(best)
    ckpt.unlink(missing_ok=True)

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
    ningbo_eval = None
    if nb:
        ningbo_eval = {}
        for part in ("val", "test"):
            xn, yn, un = nb[part]
            pn = _sigmoid(_logits(model, xn) / temperature)
            ningbo_eval[part] = {"n": len(yn), "label_map": map_v, "macro_auc_mapped": _masked_macro_auc(yn, pn, un, nb_cols),
                                 "per_label": {labels[j]: {"support": int(yn[:, j].sum()),
                                                           "auc": float(roc_auc_score(yn[un[:, j] == 0, j], pn[un[:, j] == 0, j]))}
                                               for j in nb_cols if 0 < yn[:, j].sum() < len(yn)}}
    card = _save_model(model, f"ecg12_net_{version}", {
        "name": "ecg12_net", "version": version, "recipe": spec, "labels": labels,
        "task": "10 s 12-lead ECG -> probability of each SCP-ECG statement (multi-label) and of 5 diagnostic superclasses",
        "input": f"12 x 1000 samples @ {FS_LR} Hz, leads {ptbxl.LEADS}, mV; diagnostic band-pass, then per-lead standardisation",
        "lead_mean": mean.ravel().tolist(), "lead_std": std.ravel().tolist(), "temperature": temperature,
        "thresholds": dict(zip(labels, map(float, th))),
        "threshold_rule": "per statement, maximise F1 on validation fold 9",
        "intended_use": "Research use only. Not validated on clinical ECG machines.",
        "data": f"{DATASET}: folds 1–8 train ({int(tr.sum())} ECGs), 9 validation, 10 test; patient-wise folds"
                + (f"; plus {NINGBO_DATASET}, Ningbo part only (Chapman–Shaoxing records excluded), {len(nb['train'][1])} "
                   f"training ECGs, label map {map_v}: statements {ningbo.mapped(map_v)} only" if nb else ""),
    })
    result = _meta(task="ecg12_statements", version=version, sizes={"train": int(tr.sum()), "val": int(va.sum()), "test": int(te.sum())},
                   val=val_tasks, test=test_tasks, per_label=per_label, subgroups=subgroups, calibration=calib,
                   training={"history": history, "best_val_selection_metric": best_auc}, model_card=card, ningbo=ningbo_eval,
                   benchmark_note="Published PTB-XL benchmark (Strodthoff et al. 2021, separate model per task): macro-AUC "
                                  "all 0.925, diagnostic 0.937, form 0.896, rhythm 0.957, superclass 0.930 (best models).")
    result["datasets"] = {"ptbxl": DATASET} | ({"ningbo": NINGBO_DATASET} if nb else {})
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



# ---------------------------------------------------------------- external test: Chapman–Shaoxing (China, GE MUSE)
EXTERNAL_MIN_POSITIVES = 20


def predict_statements(x: np.ndarray, fs: float, version: str = "v0.1", print_mask: bool = False) -> tuple[np.ndarray, dict]:
    """(n, 12, samples) mV at fs -> calibrated probabilities (n, labels) with a shipped statement model."""
    from cardiotic_ml.paths import ARTIFACTS_DIR

    card = json.loads((ARTIFACTS_DIR / f"ecg12_net_{version}.card.json").read_text())
    model = ECG12Net(len(card["labels"]), width=card["recipe"]["width"])
    model.load_state_dict(torch.load(ARTIFACTS_DIR / f"ecg12_net_{version}.pt", weights_only=True))
    out = []
    for i in range(0, len(x), 512):
        xb = dsp.resample(x[i:i + 512], fs, FS_LR) if fs != FS_LR else x[i:i + 512]
        xb = xb[..., :1000] if xb.shape[-1] >= 1000 else np.pad(xb, ((0, 0), (0, 0), (0, 1000 - xb.shape[-1])))
        xb = (preprocess(xb) - np.array(card["lead_mean"])[None, :, None]) / np.array(card["lead_std"])[None, :, None]
        if print_mask:
            from cardiotic_ml.ecg12 import printlayout
            xb = printlayout.mask(xb)
        out.append(_sigmoid(_logits(model, xb.astype(np.float32)) / card["temperature"]))
    return np.concatenate(out), card


def eval_external_chapman(version: str = "v0.1") -> dict:
    """Statements and measurements on all 10,646 Chapman–Shaoxing ECGs (never used for any choice)."""
    from cardiotic_ml.data import chapman

    recs = chapman.records()
    x = chapman.load_all()
    p, card = predict_statements(x, chapman.FS, version)
    labels = card["labels"]
    per_label = {}
    for name in sorted({s for r in recs for s in r.scp()}):
        y = np.array([name in r.scp() for r in recs])
        if y.sum() < EXTERNAL_MIN_POSITIVES or name not in labels:
            continue
        j = labels.index(name)
        pred = p[:, j] >= card["thresholds"][name]
        per_label[name] = {"support": int(y.sum()), "auc": float(roc_auc_score(y, p[:, j])),
                           "sensitivity": float(pred[y].mean()), "specificity": float((~pred[~y]).mean()),
                           "ppv": float(pred[y].sum() / max(pred.sum(), 1)),
                           "description": ptbxl.statements()[name]["description"]}
    sex = np.array([r.sex for r in recs])
    af = np.array(["AFIB" in r.scp() for r in recs])
    jaf = labels.index("AFIB")
    subgroups = {g: {"n": int((sex == v).sum()), "afib_auc": float(roc_auc_score(af[sex == v], p[sex == v, jaf]))}
                 for g, v in (("female", 1), ("male", 0))}
    # measurements vs GE MUSE
    pairs = {k: [] for k in chapman.MUSE_TO_OURS.values()}
    failed, t0 = 0, time.time()
    for i, r in enumerate(recs):
        m = ms.measure(x[i], chapman.FS)
        failed += not m["ok"]
        for k in pairs:
            if m.get("ok") and m.get(k) is not None and k in r.muse and (r.muse[k] > 0 or k.endswith("_deg")):
                pairs[k].append((m[k], r.muse[k]))
    result = _meta(task="ecg12_external_chapman", version=version, measure_version=ADOPTED_MEASURE, n_records=len(recs),
                   per_label=per_label, subgroups=subgroups,
                   measurements={"failed": failed, "seconds_per_ecg": (time.time() - t0) / len(recs),
                                 "vs_muse": _agreement(pairs)},
                   label_mapping={"rhythm": chapman.RHYTHM_TO_SCP, "condition": chapman.CONDITION_TO_SCP,
                                  "NORM": "rhythm SR and no condition label"},
                   note="External: different country (China), years (2013–2018) and ECG system (GE MUSE) from PTB-XL. "
                        "Condition labels are not exhaustive, so specificity and PPV are lower bounds.")
    result["datasets"] = {"chapman": "Chapman University – Shaoxing People's Hospital 12-lead ECG database (figshare, CC0)"}
    _write(f"ecg12_external_chapman_{version}", result)
    print(json.dumps({k: round(v["auc"], 3) for k, v in per_label.items()}), flush=True)
    return result


# ---------------------------------------------------------------- measurement rules vs learned statements
RULE_SELECTION = ("For each rule statement, use the rule instead of the statement model if its F1 on PTB-XL "
                  "validation fold 9 is at least the model's.")


def _binary(y: np.ndarray, pred: np.ndarray) -> dict:
    tp = int((pred & y).sum())
    se = tp / max(int(y.sum()), 1)
    ppv = tp / max(int(pred.sum()), 1)
    return {"support": int(y.sum()), "sensitivity": se, "specificity": float((~pred[~y]).mean()), "ppv": ppv,
            "f1": 2 * se * ppv / (se + ppv) if se + ppv else 0.0}


def _rule_eval(signals_500, probs, card, truth: list[set[str]]) -> dict:
    from cardiotic_ml.ecg12 import rules

    labels, th = card["labels"], card["thresholds"]
    ia, il = labels.index("AFIB"), labels.index("AFLT")
    rule_pred = {k: [] for k in rules.RULES}
    for i, sig in enumerate(signals_500):
        m = ms.measure(sig, 500)
        sin = rules.sinus(m, probs[i, ia], probs[i, il], th["AFIB"], th["AFLT"])
        for k, v in rules.rule_statements(m, sin).items():
            rule_pred[k].append(v)
    out = {}
    for k in rules.RULES:
        y = np.array([k in t for t in truth])
        out[k] = {"model": _binary(y, probs[:, labels.index(k)] >= th[k]), "rule": _binary(y, np.array(rule_pred[k]))}
    return out


def eval_rules(version: str = "v0.1") -> dict:
    from cardiotic_ml.data import chapman
    from cardiotic_ml.ecg12 import rules

    recs = ptbxl.records()
    x100 = ptbxl.load_all_lr()
    folds = np.array([r.fold for r in recs])
    res = {}
    for split, fset in (("ptbxl_val", ptbxl.VAL_FOLDS), ("ptbxl_test", ptbxl.TEST_FOLDS)):
        idx = np.flatnonzero(np.isin(folds, fset))
        p, card = predict_statements(x100[idx], FS_LR, version)
        sigs = (ptbxl.load_signal(recs[i], hr=True) for i in idx)
        res[split] = _rule_eval(sigs, p, card, [set(recs[i].codes) for i in idx])
        print(split, "done", flush=True)
    crecs = chapman.records()
    cx = chapman.load_all()
    p, card = predict_statements(cx, chapman.FS, version)
    res["chapman_external"] = _rule_eval(cx, p, card, [r.scp() for r in crecs])
    chosen = {k: "rule" if res["ptbxl_val"][k]["rule"]["f1"] >= res["ptbxl_val"][k]["model"]["f1"] else "model" for k in rules.RULES}
    result = _meta(task="ecg12_rules", version=version, selection_rule=RULE_SELECTION, rules=rules.RULES, chosen=chosen,
                   results=res)
    result["datasets"] = {"ptbxl": DATASET, "chapman": "Chapman–Shaoxing (figshare, CC0), external"}
    _write(f"ecg12_rules_{version}", result)
    print(json.dumps(chosen), flush=True)
    return result


def select_ecg12(candidate: str = "v0.3", current: str = "v0.2", versions: tuple[str, ...] = ("v0.1", "v0.2", "v0.3")) -> dict:
    """Apply ECG12_SELECTION_RULE on validation numbers only (PTB-XL fold 9 and the Ningbo validation split).
    Every version is re-scored on Ningbo validation with the current label map, so all are compared alike."""
    from cardiotic_ml.data import ningbo

    nrecs = ningbo.ningbo_part("val")
    xn = ningbo.load_lr(nrecs)
    ptb, nbv = {}, {}
    for v in versions:
        rep = json.loads((REPORTS_DIR / f"ecg12_statements_{v}.json").read_text())
        ptb[v] = rep["val"]["all"]
        p, card = predict_statements(xn, FS_LR, v)
        labels = card["labels"]
        yn = np.zeros((len(nrecs), len(labels)), dtype=np.float32)
        un = np.zeros_like(yn)
        for i, r in enumerate(nrecs):
            for c in r.scp():
                yn[i, labels.index(c)] = 1
            for c in r.unknown():
                un[i, labels.index(c)] = 1
        nbv[v] = _masked_macro_auc(yn, p, un, [labels.index(c) for c in ningbo.MAPPED])
    adopt = ptb[current] - ptb[candidate] <= 0.005 and nbv[candidate] > nbv[current]
    result = _meta(task="ecg12_selection", rule=ECG12_SELECTION_RULE, label_map=ningbo.MAP_VERSION, current=current,
                   candidate=candidate, ptbxl_val_all=ptb, ningbo_val_mapped=nbv, chosen=candidate if adopt else current,
                   history="v0.2 was adopted over v0.1 by this rule with the v0.2 label map; its external-test PVC drop "
                           "led to finding the label-map error fixed in v0.3.")
    _write("ecg12_selection", result)
    print(json.dumps({k: result[k] for k in ("ptbxl_val_all", "ningbo_val_mapped", "chosen")}), flush=True)
    return result


# ---------------------------------------------------------------- subgroup analysis: sex
def sex_gap_analysis(version: str = "v0.3", min_pos: int = 15) -> dict:
    """Where does the women / men gap come from? Validation fold only (the test fold is not looked at):
    superclass AUC by sex, overall and age 40–80 (women are older in PTB-XL), statement AUCs by sex
    (statements with >= min_pos positives in each sex), and training-fold prevalence by sex."""
    stm, sup = label_space()
    x = ptbxl.load_all_lr()
    idx = {r.ecg_id: i for i, r in enumerate(ptbxl.records())}
    va = ptbxl.split(ptbxl.VAL_FOLDS)
    y = targets(va, stm)
    sex = np.array([r.sex for r in va])
    age = np.array([r.age if r.age is not None else np.nan for r in va])
    p, _ = predict_statements(x[[idx[r.ecg_id] for r in va]], FS_LR, version)
    k = len(stm)

    def auc(mask, j):
        return float(roc_auc_score(y[mask, j], p[mask, j])) if 0 < y[mask, j].sum() < mask.sum() else None

    f, m = sex == 1, sex == 0
    mid = (age >= 40) & (age <= 80)
    superclass = {s: {"women": auc(f, k + i), "men": auc(m, k + i), "women_40_80": auc(f & mid, k + i), "men_40_80": auc(m & mid, k + i),
                      "positives_women": int(y[f, k + i].sum()), "positives_men": int(y[m, k + i].sum())}
                  for i, s in enumerate(ptbxl.SUPERCLASSES)}
    stmts = []
    for j, c in enumerate(stm):
        if y[f, j].sum() >= min_pos and y[m, j].sum() >= min_pos:
            a, b = auc(f, j), auc(m, j)
            stmts.append({"statement": c, "positives_women": int(y[f, j].sum()), "positives_men": int(y[m, j].sum()),
                          "auc_women": a, "auc_men": b, "gap": a - b})
    stmts.sort(key=lambda d: d["gap"])
    tr = ptbxl.split(ptbxl.TRAIN_FOLDS)
    yt, st = targets(tr, stm), np.array([r.sex for r in tr])
    prevalence = {s: {"women": float(yt[st == 1, k + i].mean()), "men": float(yt[st == 0, k + i].mean())} for i, s in enumerate(ptbxl.SUPERCLASSES)}
    result = _meta(task="ecg12_sex_gap", version=version, split="PTB-XL validation fold 9",
                   n={"women": int(f.sum()), "men": int(m.sum())},
                   mean_age={"women": float(np.nanmean(age[f])), "men": float(np.nanmean(age[m]))},
                   superclass=superclass, statements=stmts, train_prevalence=prevalence,
                   train_counts={"women": int((st == 1).sum()), "men": int((st == 0).sum())})
    _write(f"ecg12_sex_gap_{version}", result)
    return result


def _ningbo_val_auc(version: str) -> float:
    from cardiotic_ml.data import ningbo
    nrecs = ningbo.ningbo_part("val")
    p, card = predict_statements(ningbo.load_lr(nrecs), FS_LR, version)
    labels = card["labels"]
    yn = np.zeros((len(nrecs), len(labels)), dtype=np.float32)
    un = np.zeros_like(yn)
    for i, r in enumerate(nrecs):
        for c in r.scp():
            yn[i, labels.index(c)] = 1
        for c in r.unknown():
            un[i, labels.index(c)] = 1
    return _masked_macro_auc(yn, p, un, [labels.index(c) for c in ningbo.MAPPED])


def select_sex_weighted(candidate: str = "v0.4", current: str = "v0.3") -> dict:
    """Apply SEX_GAP_RULE (validation data only); writes reports/ecg12_selection_sex.json."""
    rule, rows = SEX_GAP_RULE, {}
    for v in (current, candidate):
        if not (REPORTS_DIR / f"ecg12_statements_{v}.json").exists():
            train_ecg12(v)
        gap = sex_gap_analysis(v)
        rows[v] = {"ptbxl_val_all": json.loads((REPORTS_DIR / f"ecg12_statements_{v}.json").read_text())["val"]["all"],
                   "ningbo_val_mapped": _ningbo_val_auc(v),
                   "mi_auc_women": gap["superclass"]["MI"]["women"], "mi_auc_men": gap["superclass"]["MI"]["men"],
                   "superclass_women": float(np.mean([g["women"] for g in gap["superclass"].values()])),
                   "superclass_men": float(np.mean([g["men"] for g in gap["superclass"].values()]))}
    c, ref = rows[candidate], rows[current]
    checks = {"ptbxl_val_all": ref["ptbxl_val_all"] - c["ptbxl_val_all"] <= rule["ptbxl_val_all_drop_max"],
              "ningbo_val_mapped": ref["ningbo_val_mapped"] - c["ningbo_val_mapped"] <= rule["ningbo_val_drop_max"],
              "mi_auc_women": c["mi_auc_women"] - ref["mi_auc_women"] >= rule["women_mi_auc_gain_min"],
              "mi_auc_men": ref["mi_auc_men"] - c["mi_auc_men"] <= rule["men_mi_auc_drop_max"]}
    result = _meta(task="ecg12_selection_sex", rule=rule, current=current, candidate=candidate, validation=rows,
                   checks=checks, chosen=candidate if all(checks.values()) else current)
    _write("ecg12_selection_sex", result)
    print(json.dumps({"validation": rows, "checks": checks, "chosen": result["chosen"]}, indent=1), flush=True)
    return result


# ---------------------------------------------------------------- per-site operating points (installation step)
def site_thresholds_chapman(version: str = "v0.3", policy: str = "max_f1", seed: int = 0) -> dict:
    """Simulate installation at a new hospital with Chapman–Shaoxing as the site: thresholds chosen on a
    random half of its ECGs (one ECG per patient), scored on the other half against the PTB-XL thresholds.
    Only statements Chapman labels are set; others keep the model's threshold."""
    from cardiotic_ml.data import chapman
    from cardiotic_ml.ecg12 import site

    recs = chapman.records()
    p, card = predict_statements(chapman.load_all(), chapman.FS, version)
    labels = card["labels"]
    labelled = sorted(set(chapman.RHYTHM_TO_SCP.values()) | set(chapman.CONDITION_TO_SCP.values()))
    y = np.array([[name in r.scp() for name in labels] for r in recs], dtype=np.float32)
    unknown = np.array([[name not in labelled for name in labels]] * len(recs), dtype=np.float32)
    idx = np.random.default_rng(seed).permutation(len(recs))
    cal, ev = idx[: len(idx) // 2], idx[len(idx) // 2:]
    chosen = site.choose(y[cal], p[cal], labels, card["thresholds"], policy=policy, unknown=unknown[cal])
    th_site = site.thresholds({"statements": {k: v for k, v in chosen.items() if v["source"] == "site"}}, card["thresholds"])

    def score(j, th):
        yt, pred = y[ev, j] == 1, p[ev, j] >= th
        return {"sensitivity": float(pred[yt].mean()), "specificity": float((~pred[~yt]).mean()),
                "ppv": float(pred[yt].sum() / max(pred.sum(), 1)), "f1": float(2 * pred[yt].sum() / max(pred.sum() + yt.sum(), 1))}

    rows = {}
    for name in labelled:
        if name not in labels:
            continue
        j = labels.index(name)
        if y[ev, j].sum() < EXTERNAL_MIN_POSITIVES:
            continue
        rows[name] = {"support_eval": int(y[ev, j].sum()), "source": chosen[name]["source"],
                      "threshold_model": float(card["thresholds"][name]), "threshold_site": float(th_site[name]),
                      "model_threshold": score(j, card["thresholds"][name]), "site_threshold": score(j, th_site[name])}
    # what atrial flutter is called instead (evaluation half, site thresholds)
    fl = ev[y[ev, labels.index("AFLT")] == 1]
    called = {c: float(np.mean(p[fl, labels.index(c)] >= th_site[c])) for c in ("AFLT", "AFIB", "SVTAC", "STACH", "SR")}
    result = _meta(task="ecg12_site_thresholds", version=version, site="Chapman–Shaoxing (simulated installation)",
                   policy=policy, seed=seed, n_calibration=int(len(cal)), n_evaluation=int(len(ev)),
                   min_positives=site.MIN_POSITIVES, statements=rows, flutter_called_as=called,
                   site_config={k: v for k, v in chosen.items() if v["source"] == "site"})
    _write(f"ecg12_site_thresholds_{version}", result)
    print(json.dumps({k: (v["model_threshold"]["f1"], v["site_threshold"]["f1"]) for k, v in rows.items()}), flush=True)
    return result


def select_print(candidate: str = "print-v0.1", current: str = "v0.3") -> dict:
    """PRINT_RULE on PTB-XL validation masked as a printout; the test fold (masked) is scored once for the record."""
    if not (REPORTS_DIR / f"ecg12_statements_{candidate}.json").exists():
        train_ecg12(candidate)
    stm, sup = label_space()
    x = ptbxl.load_all_lr()
    idx = {r.ecg_id: i for i, r in enumerate(ptbxl.records())}
    cols = _task_cols(stm)
    out = {}
    for split, folds in (("val", ptbxl.VAL_FOLDS), ("test", ptbxl.TEST_FOLDS)):
        recs = ptbxl.split(folds)
        y = targets(recs, stm)
        xs = x[[idx[r.ecg_id] for r in recs]]
        row = {}
        for v, masked in ((current, False), (current, True), (candidate, True)):
            p, _ = predict_statements(xs, FS_LR, v, print_mask=masked)
            row[f"{v}{' (printout)' if masked else ' (full ECG)'}"] = {k: macro_auc(y, p, c) for k, c in cols.items()}
        out[split] = row
    val = out["val"]
    gain = val[f"{candidate} (printout)"]["all"] - val[f"{current} (printout)"]["all"]
    adopt = gain >= PRINT_RULE["min_gain_all"] and val[f"{candidate} (printout)"]["superclass"] >= PRINT_RULE["min_superclass"]
    result = _meta(task="ecg12_selection_print", rule=PRINT_RULE, results=out, gain_val_all=gain, chosen=candidate if adopt else None)
    _write("ecg12_selection_print", result)
    print(json.dumps({"val": val, "chosen": result["chosen"]}, indent=1), flush=True)
    return result


# ---------------------------------------------------------------- atrial flutter: model outputs + atrial-activity features
# Pre-declared before any result was seen. Development data: the first half of Chapman–Shaoxing (seed 0, the half
# already used for the site-threshold simulation); test: the other half, scored once. Adopt the flutter detector if
# its 5-fold cross-validated F1 for flutter on the development half beats the best F1 of the model's own flutter
# probability (any threshold) on the same half by at least 0.10.
FLUTTER_RULE = {"min_f1_gain": 0.10, "folds": 5}


def flutter_detector(version: str = "v0.3", seed: int = 0) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from cardiotic_ml.data import chapman
    from cardiotic_ml.ecg12 import flutter

    recs = chapman.records()
    x = chapman.load_all()
    p, card = predict_statements(x, chapman.FS, version)
    labels = card["labels"]
    ja, jf = labels.index("AFIB"), labels.index("AFLT")
    feats, keep = [], []
    for i in range(len(recs)):
        f = flutter.features(x[i], chapman.FS)
        keep.append(f is not None)
        feats.append(f if f is not None else np.zeros(len(flutter.NAMES), dtype=np.float32))
    feats, keep = np.array(feats), np.array(keep)
    y = np.array(["AFLT" in r.scp() for r in recs])
    X = np.column_stack([np.log(p[:, jf] + 1e-6), np.log(p[:, ja] + 1e-6), feats])
    idx = np.random.default_rng(seed).permutation(len(recs))
    dev, test = idx[: len(idx) // 2], idx[len(idx) // 2:]
    dev, test = dev[keep[dev]], test[keep[test]]

    def best_f1(yt, score):
        order = np.argsort(-score)
        tp = np.cumsum(yt[order]); fp = np.cumsum(~yt[order])
        f1 = 2 * tp / (tp + fp + yt.sum())
        k = int(np.argmax(f1))
        return float(f1[k]), float(score[order][k])

    def at(yt, score, th):
        pred = score >= th
        return {"sensitivity": float(pred[yt].mean()), "ppv": float(pred[yt].sum() / max(pred.sum(), 1)), "f1": float(2 * (pred & yt).sum() / max(pred.sum() + yt.sum(), 1))}

    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5))
    cv = cross_val_predict(clf, X[dev], y[dev], cv=StratifiedKFold(FLUTTER_RULE["folds"], shuffle=True, random_state=0), method="predict_proba")[:, 1]
    f1_det, th_det = best_f1(y[dev], cv)
    f1_model, th_model = best_f1(y[dev], p[dev, jf])
    adopt = f1_det - f1_model >= FLUTTER_RULE["min_f1_gain"]
    clf.fit(X[dev], y[dev])
    det_test = clf.predict_proba(X[test])[:, 1]
    from sklearn.metrics import roc_auc_score
    result = _meta(task="ecg12_flutter_detector", version=version, rule=FLUTTER_RULE, features=["log p(AFLT)", "log p(AFIB)", *flutter.NAMES],
                   n_dev=int(len(dev)), n_test=int(len(test)), flutter_dev=int(y[dev].sum()), flutter_test=int(y[test].sum()),
                   dev={"detector_cv_f1": f1_det, "model_best_f1": f1_model},
                   adopted=bool(adopt),
                   test={"detector": {"auc": float(roc_auc_score(y[test], det_test)), **at(y[test], det_test, th_det)},
                         "model_alone": {"auc": float(roc_auc_score(y[test], p[test, jf])), **at(y[test], p[test, jf], th_model)},
                         "model_ptbxl_threshold": at(y[test], p[test, jf], card["thresholds"]["AFLT"])},
                   coefficients=dict(zip(["log p(AFLT)", "log p(AFIB)", *flutter.NAMES], map(float, clf[-1].coef_[0]))),
                   scaler={"mean": clf[0].mean_.tolist(), "scale": clf[0].scale_.tolist()}, intercept=float(clf[-1].intercept_[0]), threshold=th_det)
    _write("ecg12_flutter_detector", result)
    print(json.dumps({k: result[k] for k in ("dev", "adopted", "test")}, indent=1), flush=True)
    return result
