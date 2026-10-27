"""Validation numbers for the frontend's "AI models & validation" page, read from the result files
(ml/reports/*.json, engine/validation/equivalence.json) so the page can never drift from them.

    python3 frontend/scripts/build_validation.py      (standard library only)
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "ml" / "reports"


def load(name):
    return json.loads((R / f"{name}.json").read_text())


def pct(v, d=1):
    return f"{100 * v:.{d}f}%"


def main():
    qrs = load("qrs_detection")["methods"]["pantompkins1985"]["all_48"]
    q = load("signal_quality_v0.3")
    e2e = load("end_to_end_pipeline")
    rc = load("rhythm_classification_v0.1")
    afdb = load("rhythm_afdb_test_v0.1")
    mit = load("rhythm_mitdb_test_v0.1")
    s3 = load("ecg12_statements_v0.3")
    ext = load("ecg12_external_chapman_v0.3")
    meas = load("ecg12_measurements_test_v0.2")["agreement"]
    eq = json.loads((ROOT / "engine" / "validation" / "equivalence.json").read_text())
    pc = e2e["test"]["per_class"]
    a12, mu = meas["vs_12sl"], ext["measurements"]["vs_muse"]
    pm = lambda a: f"{a['mean_diff']:+.1f} ± {a['sd_diff']:.1f}"  # noqa: E731
    lab = ext["per_label"]
    models = [
        {"id": "qrs", "name": "Heartbeat detection", "version": "Pan-Tompkins + R-peak refinement", "kind": "Signal processing",
         "task": "Find every heartbeat", "tested_on": "All 48 MIT-BIH Arrhythmia records (EC57-style scoring)",
         "metrics": [["Sensitivity", pct(qrs["sensitivity"])], ["Positive predictivity", pct(qrs["ppv"])], ["Beats", f"{qrs['tp'] + qrs['fn']:,}"]],
         "limits": ["Paced and very noisy records are hardest (record 108: Se 82%)."]},
        {"id": "quality", "name": "Signal quality (M1)", "version": "quality_net v0.3", "kind": "1D-CNN",
         "task": "Good / noisy / unusable, per 2.5 s", "tested_on": "Unseen MIT-BIH patients with calibrated noise; CinC 2017 expert labels",
         "metrics": [["Unusable caught", pct(q["test"]["per_class"]["unusable"]["sensitivity"])],
                     ["Clean ECG rated unusable", pct(q["real_data_test"]["cinc_N"]["unusable"], 2)]],
         "limits": ["Trained on Holter lead II, not 12-lead: rates ~20% of clean 12-lead leads 'noisy'."]},
        {"id": "beats", "name": "Beat classifier (M2)", "version": "beat_net v0.1", "kind": "1D-CNN + RR features",
         "task": "Normal / supraventricular / ventricular / fusion", "tested_on": "22 unseen MIT-BIH patients (inter-patient, end to end)",
         "metrics": [["Ventricular Se / +P", f"{pct(pc['V']['sensitivity'])} / {pct(pc['V']['ppv'])}"], ["Normal Se / +P", f"{pct(pc['N']['sensitivity'])} / {pct(pc['N']['ppv'])}"],
                     ["Beats analysed", pct(e2e["totals"]["matched"] / (e2e["totals"]["matched"] + e2e["totals"]["missed"] + e2e["totals"]["in_unusable_segments"]))]],
         "limits": [f"Supraventricular beats weak (Se {pct(pc['S']['sensitivity'], 0)}); fusion beats not recognised."]},
        {"id": "rhythm", "name": "Rhythm / AF (M3)", "version": "rhythm_net v0.1", "kind": "1D ResNet + RR irregularity",
         "task": "Sinus / AF / other / too noisy, per 30 s", "tested_on": "CinC 2017 test split; fresh MIT-BIH AF Database patients; MIT-BIH test records",
         "metrics": [["AF sensitivity (AFDB)", pct(afdb["af_sensitivity"])], ["AF PPV (AFDB)", pct(afdb["af_ppv"])], ["CinC 2017 F1", pct(rc["test_challenge_f1"])],
                     ["Calibration error", f"{pct(rc['calibration']['ece_before'])} → {pct(rc['calibration']['ece_after'])}"]],
         "limits": [f"Over-calls AF when ectopic beats are frequent (MIT-BIH test PPV {pct(mit['af_ppv'], 0)})."]},
        {"id": "ecg12", "name": "12-lead diagnostic statements (M4)", "version": "ecg12_net v0.3", "kind": "1D ResNet, 71 SCP-ECG statements",
         "task": "Diagnoses and descriptions from a 10 s 12-lead ECG", "tested_on": "PTB-XL test fold (Germany); Chapman–Shaoxing held out (China)",
         "metrics": [["Macro-AUC, all statements", f"{s3['test']['all']['macro_auc']:.3f}"], ["Macro-AUC, diagnostic", f"{s3['test']['diagnostic']['macro_auc']:.3f}"],
                     ["AF AUC (Chapman)", f"{lab['AFIB']['auc']:.3f}"], ["PVC AUC (Chapman)", f"{lab['PVC']['auc']:.3f}"], ["LBBB AUC (Chapman)", f"{lab['CLBBB']['auc']:.3f}"]],
         "limits": [f"Atrial flutter weak (Chapman sensitivity {pct(lab['AFLT']['sensitivity'], 0)}).",
                    f"Women {s3['subgroups']['female']['superclass_macro_auc']:.3f} vs men {s3['subgroups']['male']['superclass_macro_auc']:.3f} (superclass AUC) — under investigation.",
                    "Yes/no thresholds must be set per hospital."]},
        {"id": "measure", "name": "12-lead measurements (M4)", "version": "measurement v0.2", "kind": "Signal processing (median beat)",
         "task": "Heart rate, PR, QRS, QT/QTc, axes", "tested_on": "PTB-XL test fold vs GE 12SL; Chapman–Shaoxing vs GE MUSE",
         "metrics": [["QRS vs GE 12SL (ms)", pm(a12["qrs_ms"])], ["QT vs GE 12SL (ms)", pm(a12["qt_ms"])], ["PR vs GE 12SL (ms)", pm(a12["pr_ms"])],
                     ["QRS vs GE MUSE (ms)", pm(mu["qrs_ms"])], ["QT vs GE MUSE (ms)", pm(mu["qt_ms"])]],
         "limits": ["Compared with other algorithms, not a referee: the CSE database is needed for IEC 60601-2-25."]},
    ]
    sets = eq["sets"]
    out = {"models": models,
           "engine": {"version": eq["engine"]["version"], "models_version": eq["engine"]["models_version"], "passed": eq["passed"],
                      "ecgs": sum(v.get("ecgs", 0) for v in sets.values()),
                      "beats": sum(v.get("beats", 0) for v in sets.values()),
                      "max_prob_diff": max(v["max_prob_diff"] for v in sets.values())},
           "source": "ml/reports/RESULTS.md and engine/validation/equivalence.json"}
    path = ROOT / "frontend" / "public" / "data" / "validation.json"
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
