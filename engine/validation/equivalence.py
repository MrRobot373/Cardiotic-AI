"""Engine (ONNX Runtime) vs research pipeline (PyTorch): same findings on real recordings?

Writes engine/validation/equivalence.json. Needs the research data (data/raw) and PyTorch, so it runs
in the research environment, not in a deployed engine. Pass criterion: identical discrete outputs
(beat classes, rhythm labels, statements, lead quality, measurements, findings) and probabilities within
PROB_TOL.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROB_TOL = 1e-4


def _cmp12(a: dict, b: dict) -> tuple[bool, float]:
    same = (a["lead_quality"] == b["lead_quality"] and a["measurements"] == b["measurements"]
            and [s["statement"] for s in a["statements"]] == [s["statement"] for s in b["statements"]])
    diff = max([abs(x["probability"] - y["probability"]) for x, y in zip(a["statements"], b["statements"])], default=0.0)
    return same, diff


def _cmp1(a: dict, b: dict) -> tuple[bool, float]:
    same = (a["findings"] == b["findings"] and [x["class"] for x in a["beats"]] == [x["class"] for x in b["beats"]]
            and [x["time_s"] for x in a["beats"]] == [x["time_s"] for x in b["beats"]]
            and [x["rhythm"] for x in a["rhythm_segments"]] == [x["rhythm"] for x in b["rhythm_segments"]]
            and [x["quality"] for x in a["quality_segments"]] == [x["quality"] for x in b["quality_segments"]])
    probs = [abs(x["probability"] - y["probability"]) for k in ("beats", "rhythm_segments", "quality_segments")
             for x, y in zip(a[k], b[k])]
    return same, max(probs, default=0.0)


def main(n12: int = 400) -> dict:
    from cardiotic_engine.api import Engine
    from cardiotic_ml import pipeline
    from cardiotic_ml.data import chapman, mitdb, ptbxl
    from cardiotic_ml.ecg12.analyze import Models12, analyze_12lead

    eng = Engine()
    torch12, torch1 = Models12(), pipeline.load_models()
    out = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine": eng.info(),
           "criterion": f"identical discrete outputs; probabilities within {PROB_TOL}", "sets": {}}
    sets = {"PTB-XL test fold (500 Hz)": [ptbxl.load_signal(r, hr=True) for r in ptbxl.split(ptbxl.TEST_FOLDS)[:n12]]}
    cx = chapman.load_all()
    sets["Chapman–Shaoxing (500 Hz)"] = list(cx[np.linspace(0, len(cx) - 1, n12).astype(int)])
    for name, sigs in sets.items():
        mism, worst, t_e, t_t = 0, 0.0, 0.0, 0.0
        for x in sigs:
            t = time.perf_counter(); a = eng.analyze_ecg12({l: x[i] for i, l in enumerate(ptbxl.LEADS)}, 500)["result"]; t_e += time.perf_counter() - t
            t = time.perf_counter(); b = analyze_12lead(x, 500, torch12); t_t += time.perf_counter() - t
            same, d = _cmp12(a, b)
            mism += not same; worst = max(worst, d)
        out["sets"][name] = {"ecgs": len(sigs), "mismatching": mism, "max_prob_diff": worst,
                             "engine_ms_per_ecg": 1000 * t_e / len(sigs), "pytorch_ms_per_ecg": 1000 * t_t / len(sigs)}
        print(name, out["sets"][name], flush=True)
    mism, worst, rows = 0, 0.0, []
    for rid in mitdb.DS2:
        rec = mitdb.load_record(rid)
        a = eng.analyze_rhythm(rec.signal, rec.fs, lead="MLII")["result"]
        b = pipeline.analyze(rec.signal, rec.fs, torch1)
        same, d = _cmp1(a, b)
        mism += not same; worst = max(worst, d)
        rows.append({"record": rid, "same": same, "beats": len(a["beats"]), "max_prob_diff": d})
    out["sets"]["MIT-BIH DS2, full 30 min records"] = {"records": len(rows), "mismatching": mism, "max_prob_diff": worst,
                                                      "beats": sum(r["beats"] for r in rows), "per_record": rows}
    print("MIT-BIH", {k: v for k, v in out["sets"]["MIT-BIH DS2, full 30 min records"].items() if k != "per_record"}, flush=True)
    out["passed"] = all(s["mismatching"] == 0 and s["max_prob_diff"] <= PROB_TOL for s in out["sets"].values())
    Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=2))
    print("PASSED" if out["passed"] else "FAILED", flush=True)
    return out


if __name__ == "__main__":
    sys.exit(0 if main()["passed"] else 1)
