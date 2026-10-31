"""End to end: PTB-XL TEST-fold ECGs -> the product's PDF report -> digitiser -> printout model. Compares statement
accuracy (macro-AUC) for the original masked ECG, the vector PDF and a 200 dpi scan, and the heart rate against the
original. Writes ml/reports/printout_end_to_end.json. Test fold, scored once. Needs research data and pdftoppm.
Run: python3 engine/validation/printout_end_to_end.py [N]"""
import base64, json, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from sklearn.metrics import roc_auc_score
from cardiotic_engine.api import Engine
from cardiotic_engine.ingest import LEADS, parse
from cardiotic_ml import dsp
from cardiotic_ml.data import ptbxl
from cardiotic_ml.ecg12 import analyze as A, printlayout as PL
from cardiotic_server import pdf

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
eng = Engine(); mods = eng._m.ecg12
labels = mods.print_card["labels"]
recs = ptbxl.split(ptbxl.TEST_FOLDS)[:N]
P = {"original, masked": [], "vector PDF": [], "scan, 200 dpi": []}
Y, hr = [], {"vector PDF": [], "scan, 200 dpi": []}
fails = 0
for r in recs:
    x = ptbxl.load_signal(r, hr=True)
    view = dsp.bandpass(x, 500, "diagnostic")
    y = np.zeros(len(labels))
    for c in r.codes:
        if c in labels: y[labels.index(c)] = 1
    for s_ in ptbxl.superclasses(r): y[labels.index("SUPER_" + s_)] = 1
    b64 = {l: base64.b64encode(np.clip(np.round(view[i] * 1000), -32767, 32767).astype("<i2").tobytes()).decode() for i, l in enumerate(LEADS)}
    rep = {"id": "E1", "site": "S", "patient": {"name": "T", "mrn": "1", "sex": "", "birth_date": None}, "recorded_at": "2026-01-01T00:00", "location": "", "device": "", "ordered_by": "",
           "measurements": {}, "edited": [], "statements": [], "note": "", "signed_by": "D", "signed_at": "x", "software": "x"}
    data = pdf.ecg_report(rep, b64, 500, draft=False)
    with tempfile.TemporaryDirectory() as d:
        Path(d, "r.pdf").write_bytes(data)
        subprocess.run(["pdftoppm", "-r", "200", "-png", f"{d}/r.pdf", f"{d}/p"], check=True)
        png = Path(d, "p-1.png").read_bytes()
    try:
        got = {}
        for kind, blob in (("vector PDF", data), ("scan, 200 dpi", png)):
            e = parse(blob)
            xs = np.stack([e.leads[l] for l in LEADS]).astype(np.float32)
            got[kind] = A.probabilities(xs, 500, mods, net=mods.print_net, card=mods.print_card, print_mask=True)
            out = A.analyze_printout(xs, 500, mods, e.layout, e.windows)
            ref = A.analyze_printout(PL.mask(x).astype(np.float32), 500, mods, "print-3x4", PL.windows(x.shape[1]))
            if out["measurements"].get("ok") and ref["measurements"].get("ok"):
                hr[kind].append(out["measurements"]["heart_rate_bpm"] - ref["measurements"]["heart_rate_bpm"])
    except Exception:
        fails += 1
        continue
    P["original, masked"].append(A.probabilities(x, 500, mods, net=mods.print_net, card=mods.print_card, print_mask=True))
    for k, v in got.items(): P[k].append(v)
    Y.append(y)
Y = np.array(Y)
sup = [labels.index("SUPER_" + s_) for s_ in ptbxl.SUPERCLASSES]
def mauc(Pr, cols): return float(np.mean([roc_auc_score(Y[:, j], Pr[:, j]) for j in cols if 0 < Y[:, j].sum() < len(Y)]))
allc = list(range(len(labels)))
out = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "split": "PTB-XL test fold 10", "ecgs": int(len(Y)), "failed": fails,
       "macro_auc": {k: {"all": mauc(np.array(v), allc), "superclass": mauc(np.array(v), sup)} for k, v in P.items()},
       "heart_rate_difference_vs_original_bpm": {k: {"mean": float(np.mean(v)), "sd": float(np.std(v)), "within_5bpm": float(np.mean(np.abs(v) <= 5))} for k, v in hr.items() if v}}
Path(__file__).resolve().parents[2].joinpath("ml/reports/printout_end_to_end.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
