"""AF operating points: can the shipped rhythm model (v0.1) offer a transparent sensitivity / false-alarm trade-off?

The rhythm model gives each 30 s window a probability of atrial fibrillation (AF). Today a window is called AF when AF
has the highest probability (`argmax`). RESULTS.md §4 shows that this over-calls AF in recordings with frequent ectopic
beats. Instead of retraining (four attempts were rejected), this experiment chooses how the *same* probabilities are
turned into a yes/no, per use case, on validation data only, and reports test data once.

PRE-DECLARED RULE (written before any test-split result was computed; windows are pooled over AFDB-val and MIT-BIH-val):
  REVIEW    ("fewer false alarms"): the lowest threshold t on p(AF) with val PPV >= 0.90 and val sensitivity >= 0.90.
            Offered only if its val false-AF windows are at most 50% of argmax's and its val sensitivity is at most
            5 points below argmax's.
  SCREENING ("do not miss AF"): the highest threshold t with val sensitivity >= 0.99.
            Offered only if its val sensitivity is at least 2 points above argmax's and its val PPV is >= 0.50.
  An offered mode is shipped as an option the site can choose; the default stays argmax ("balanced"). The measured test
  numbers of every mode are shown with the option. A mode that is not offered is not shipped.

AMENDMENT (made after the first run, and recorded in the result file): REVIEW was declared as "the lowest threshold", which
selects the end of the feasible interval with the MOST false alarms and contradicts its stated purpose. The first run followed the
text literally ("review_as_declared" in the result: not offered, because it failed the offering test) and its test numbers were
printed before the mistake was noticed. The corrected rule picks the HIGHEST threshold with val PPV >= 0.90 and val sensitivity >= 0.90
(fewest false alarms among those that keep the sensitivity); everything else is unchanged and the threshold is still chosen on validation data only.
"""

from __future__ import annotations

import json

import numpy as np
import torch

from cardiotic_ml import calibration as cal
from cardiotic_ml.data import afdb, mitdb
from cardiotic_ml.experiments import _meta, _write
from cardiotic_ml.experiments_rhythm import (MITDB_SPLITS, _afdb_prepared, _afdb_window_rhythms, _beat_model, load_rhythm_model)
from cardiotic_ml.rhythm import dataset as rd
from cardiotic_ml.data.cinc2017 import LABELS
from cardiotic_ml.train_utils import predict_logits

RULE = __doc__.split("PRE-DECLARED RULE")[1].split('"""')[0].strip()
A = LABELS.index("A")


def collect(version: str, split: str) -> dict:
    """Per 30 s window: p(AF), truth (1 AF, 0 non-AF; mixed windows skipped), dataset and record."""
    model, temperature, card = load_rhythm_model(version)
    bm = _beat_model()
    uses_ect = card.get("recipe", {}).get("ectopy_features")
    P, Y, D, R = [], [], [], []
    for rid in afdb.split()[split]:
        x, beats, ect = _afdb_prepared(rid, bm)
        w, r, starts = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect if uses_ect else None)
        p = cal.softmax(predict_logits(model, (torch.from_numpy(w), torch.from_numpy(r))), temperature)
        for pa, rh in zip(p, _afdb_window_rhythms(rid, starts)):
            if rh == ["(AFIB"] or (rh and "(AFIB" not in rh):
                P.append(pa); Y.append(int(rh == ["(AFIB"])); D.append("afdb"); R.append(rid)
    for rid in MITDB_SPLITS[split]:
        rec = mitdb.load_record(rid)
        x, beats, ect = rd.prepare(rec.signal, rec.fs, bm)
        w, r, starts = rd.windows(x, beats, stride_s=rd.WIN_S, ectopic=ect if uses_ect else None)
        spans = rd.mitdb_rhythm_spans(rid, len(rec.signal))
        p = cal.softmax(predict_logits(model, (torch.from_numpy(w), torch.from_numpy(r))), temperature)
        for st, pa in zip(starts, p):
            a, b = int(st * rec.fs), int((st + rd.WIN_S) * rec.fs)
            overlap = [lab for s0, e0, lab in spans if s0 < b and e0 > a]
            is_af = overlap == ["(AFIB"]
            if not is_af and "(AFIB" in overlap:
                continue
            P.append(pa); Y.append(int(is_af)); D.append("mitdb"); R.append(str(rid))
    return {"p": np.array(P), "y": np.array(Y), "dataset": np.array(D), "record": np.array(R)}


def score(d: dict, said: np.ndarray) -> dict:
    y = d["y"].astype(bool)
    tp, fn, fp, tn = int((said & y).sum()), int((~said & y).sum()), int((said & ~y).sum()), int((~said & ~y).sum())
    out = {"af_windows": tp + fn, "non_af_windows": fp + tn, "false_af_windows": fp, "missed_af_windows": fn,
           "sensitivity": tp / max(tp + fn, 1), "ppv": tp / max(tp + fp, 1), "specificity": tn / max(tn + fp, 1)}
    per = {}
    for ds in ("afdb", "mitdb"):
        m = d["dataset"] == ds
        yy, ss = y[m], said[m]
        per[ds] = {"sensitivity": float((ss & yy).sum() / max(yy.sum(), 1)), "false_af_windows": int((ss & ~yy).sum()), "ppv": float((ss & yy).sum() / max(ss.sum(), 1))}
    return out | {"by_dataset": per}


def choose(val: dict, review_pick: str = "highest") -> dict:
    pa, y = val["p"][:, A], val["y"].astype(bool)
    base = score(val, val["p"].argmax(1) == A)
    grid = np.unique(np.round(pa, 4))
    chosen = {"balanced (argmax)": {"threshold": None, "val": base, "offered": True, "why": "default: AF when AF is the most probable class"}}
    ok = [t for t in grid if (lambda s: s["ppv"] >= 0.90 and s["sensitivity"] >= 0.90)(score(val, pa >= t))]
    if ok:
        t = float(max(ok) if review_pick == "highest" else min(ok)); s = score(val, pa >= t)
        offered = s["false_af_windows"] <= 0.5 * base["false_af_windows"] and s["sensitivity"] >= base["sensitivity"] - 0.05
        chosen["review"] = {"threshold": t, "val": s, "offered": bool(offered), "why": "val PPV >= 0.90 and sensitivity >= 0.90" + ("" if offered else "; failed the offering test")}
    else:
        chosen["review"] = {"threshold": None, "val": None, "offered": False, "why": "no threshold reaches val PPV >= 0.90 with sensitivity >= 0.90"}
    ok = [t for t in grid if score(val, pa >= t)["sensitivity"] >= 0.99]
    if ok:
        t = float(max(ok)); s = score(val, pa >= t)
        offered = s["sensitivity"] >= base["sensitivity"] + 0.02 and s["ppv"] >= 0.50
        chosen["screening"] = {"threshold": t, "val": s, "offered": bool(offered), "why": "val sensitivity >= 0.99" + ("" if offered else "; failed the offering test")}
    else:
        chosen["screening"] = {"threshold": None, "val": None, "offered": False, "why": "no threshold reaches val sensitivity 0.99"}
    return chosen


def run(version: str = "v0.1") -> dict:
    val, test = collect(version, "val"), collect(version, "test")
    modes = choose(val)
    literal = choose(val, review_pick="lowest")["review"]  # the rule exactly as first declared, kept on record
    for name, m in [*modes.items(), ("review_as_declared", literal)]:  # the test split is looked at only after the choice is fixed
        said = test["p"].argmax(1) == A if m["threshold"] is None else test["p"][:, A] >= m["threshold"]
        m["test"] = score(test, said)
    modes["review_as_declared"] = literal
    result = _meta(task="af_operating_points", version=version, rule=RULE, val_windows=int(len(val["y"])), test_windows=int(len(test["y"])), modes=modes)
    _write(f"rhythm_af_operating_points_{version}", result)
    for name, m in modes.items():
        t = m["test"]
        print(f"{name:20} val sens {(m['val'] or {}).get('sensitivity', float('nan')):.3f} PPV {(m['val'] or {}).get('ppv', float('nan')):.3f} | offered={m['offered']!s:5} thr={m['threshold']}  TEST sens {t['sensitivity']:.3f}  PPV {t['ppv']:.3f}  false-AF windows {t['false_af_windows']}  missed {t['missed_af_windows']}", flush=True)
    return result


if __name__ == "__main__":
    run()
