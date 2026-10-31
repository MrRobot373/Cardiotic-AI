"""Long recordings are analysed in 30-minute sections with a minute of overlap. Does that change the result?
Compares one-pass analysis with sectioned analysis on 2 h built from real MIT-BIH records, and measures a 24 h
recording's time and memory. Writes ml/reports/holter_chunking.json. Run: python3 engine/validation/holter_chunking.py"""

import json, resource, time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from cardiotic_engine.api import Engine
from cardiotic_ml import pipeline
from cardiotic_ml.data import mitdb

eng = Engine()
m = eng._m.single
out = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "two_hour_comparisons": []}
for ids, note in (((221,) * 4, "one patient (record 221, repeated)"), ((203,) * 4, "one patient (record 203, repeated)"), ((201, 203, 210, 219), "four different patients joined")):
    x = np.concatenate([mitdb.load_record(r).signal for r in ids]).astype(np.float32)
    a = pipeline.analyze(x, 360, m)
    b = pipeline.analyze_long(x, 360, m)
    ta = np.array([q["time_s"] for q in a["beats"]]); tb = np.array([q["time_s"] for q in b["beats"]])
    j = np.clip(np.searchsorted(tb, ta), 1, len(tb) - 1)
    pick = np.where(abs(tb[j] - ta) < abs(tb[j - 1] - ta), j, j - 1)
    close = abs(tb[pick] - ta) < 0.05
    cls_same = np.mean([b["beats"][int(k)]["class"] == a["beats"][i]["class"] for i, k in enumerate(pick) if close[i]])
    ra = {r["start_s"]: r["rhythm"] for r in a["rhythm_segments"]}; rb = {r["start_s"]: r["rhythm"] for r in b["rhythm_segments"]}
    common = set(ra) & set(rb)
    out["two_hour_comparisons"].append({"data": note, "hours": len(x) / 360 / 3600, "beats": [len(ta), len(tb)], "beats_same_position": float(close.mean()),
                                         "beats_same_class": float(cls_same), "rhythm_windows_same": float(np.mean([ra[k] == rb[k] for k in common])),
                                         "heart_rate": [a["measurements"]["heart_rate_bpm"], b["measurements"]["heart_rate_bpm"]]})
x = np.tile(mitdb.load_record(221).signal, 49)[: 24 * 3600 * 360].astype(np.float32)
t = time.time()
r = eng.analyze_rhythm(x, 360, "mV", "MLII")
out["recording_24h"] = {"seconds": time.time() - t, "beats": len(r["result"]["beats"]), "peak_memory_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                        "single_pass_peak_memory_mb_measured_before": 2839, "note": "30-minute sections; peak memory measured in this process"}
Path(__file__).resolve().parents[2].joinpath("ml/reports/holter_chunking.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
