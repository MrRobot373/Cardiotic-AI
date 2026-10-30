"""Command line: `python -m cardiotic_ml.cli <command>`.

  download        fetch MIT-BIH (mitdb) and NSTDB noise records from PhysioNet into data/raw
  eval-qrs        score QRS detectors on all 48 MIT-BIH records (EC57-style)
  train-quality   train + test the signal-quality model (--version v0.1 | v0.2)
  select-quality  train v0.4 / v0.5 if needed and choose a 12-lead-ready quality model on validation
  quality-real    add CinC 2017 real-data checks to an existing quality report (--version)
  train-rhythm    train + test the rhythm model on CinC 2017 (also fits its calibration)
  eval-rhythm-mitdb  AF test of a rhythm model on MIT-BIH (--version, --split val|test|all)
  eval-rhythm-afdb   AF test on MIT-BIH AF Database patients (--version, --split val|test)
  select-rhythm      apply the pre-declared selection rule to candidate rhythm versions (validation only)
  make-rhythm-gate   choose the AF ectopy gate (rhythm v0.3) on MIT-BIH validation records
  rhythm-cinc-val    add CinC validation scores to an older rhythm report (--version)
  calibrate-beats    fit the beat model's calibration temperature on its validation patients
  train-beats     train + test the beat classifier (inter-patient DS1 -> DS2)
  eval-pipeline   run the full pipeline on all 22 DS2 test records and score it end to end
  analyze         run the full pipeline on one MIT-BIH record and save JSON (+ optional plot)
  train-ecg12     train + test the 12-lead statement model on PTB-XL (folds 1-8 / 9 / 10)
  tune-ecg12-measure  choose 12-lead measurement thresholds on PTB-XL training folds (vs GE 12SL)
  eval-ecg12-measure  12-lead interval agreement vs GE 12SL and Uni-G (--version, --split val|test)
  eval-ecg12-external  12-lead statements and measurements on Chapman–Shaoxing (external test, --version)
  eval-ecg12-rules  measurement rules (bradycardia, tachycardia, 1st-degree AV block, long QT) vs the statement model
  ecg12-sex-gap   where the women / men gap comes from (validation fold only, --version)
  select-ecg12-sex  train v0.4 (women's MI weighted) if needed and apply the pre-declared sex-gap rule
  site-thresholds  simulate installation: thresholds from half of Chapman, scored on the other half
  select-ecg12    apply the pre-declared v0.1 / v0.2 rule (validation data only)
  analyze-12lead  run the 12-lead pipeline on one PTB-XL ECG (--ecg-id) and save JSON (+ optional plot)
  export-engine   export the adopted models to ONNX for the engine (checked against PyTorch) + manifest
  report          regenerate ml/reports/RESULTS.md from the JSON results
"""

from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cardiotic-ml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    sub.add_parser("eval-qrs")
    sub.add_parser("eval-pipeline")
    q = sub.add_parser("train-quality"); q.add_argument("--version", default="v0.3", choices=["v0.1", "v0.2", "v0.3", "v0.4", "v0.5"])
    sub.add_parser("select-quality")
    sub.add_parser("select-quality-v06")
    sub.add_parser("select-ecg12-sex")
    stc = sub.add_parser("site-thresholds"); stc.add_argument("--version", default="v0.3"); stc.add_argument("--policy", default="max_f1")
    qr = sub.add_parser("quality-real"); qr.add_argument("--version", default="v0.1")
    tr = sub.add_parser("train-rhythm"); tr.add_argument("--version", default="v0.4", choices=["v0.1", "v0.2", "v0.4", "v0.5"])
    ea = sub.add_parser("eval-rhythm-afdb"); ea.add_argument("--version", default="v0.1"); ea.add_argument("--split", default="val", choices=["val", "test"])
    sub.add_parser("select-rhythm")
    er = sub.add_parser("eval-rhythm-mitdb"); er.add_argument("--version", default="v0.2"); er.add_argument("--split", default="test", choices=["val", "test", "all"])
    cv = sub.add_parser("rhythm-cinc-val"); cv.add_argument("--version", default="v0.1")
    sub.add_parser("make-rhythm-gate")
    sub.add_parser("calibrate-beats")
    b = sub.add_parser("train-beats"); b.add_argument("--version", default="v0.2", choices=["v0.1", "v0.2"])
    a = sub.add_parser("analyze")
    a.add_argument("--record", type=int, required=True)
    a.add_argument("--start", type=float, default=0.0, help="seconds")
    a.add_argument("--seconds", type=float, default=60.0)
    a.add_argument("--out", default="analysis.json")
    a.add_argument("--plot", default=None)
    e12 = sub.add_parser("train-ecg12"); e12.add_argument("--version", default="v0.3", choices=["v0.1", "v0.2", "v0.3", "v0.4", "v0.5"])
    tm = sub.add_parser("tune-ecg12-measure"); tm.add_argument("--version", default="v0.2")
    em = sub.add_parser("eval-ecg12-measure"); em.add_argument("--version", default="v0.2"); em.add_argument("--split", default="val", choices=["val", "test"])
    ex = sub.add_parser("eval-ecg12-external"); ex.add_argument("--version", default="v0.1")
    sub.add_parser("eval-ecg12-rules")
    sub.add_parser("select-ecg12")
    sg = sub.add_parser("ecg12-sex-gap"); sg.add_argument("--version", default="v0.3")
    a12 = sub.add_parser("analyze-12lead"); a12.add_argument("--ecg-id", type=int, required=True)
    a12.add_argument("--out", default="analysis_12lead.json"); a12.add_argument("--plot", default=None)
    sub.add_parser("export-engine")
    sub.add_parser("report")
    args = ap.parse_args(argv)

    if args.cmd == "download":
        import wfdb
        from cardiotic_ml.paths import MITDB_DIR, NSTDB_DIR
        wfdb.dl_database("mitdb", dl_dir=str(MITDB_DIR))
        wfdb.dl_database("nstdb", dl_dir=str(NSTDB_DIR), records=["bw", "em", "ma"])
    elif args.cmd == "eval-qrs":
        from cardiotic_ml.experiments import eval_qrs
        eval_qrs()
    elif args.cmd == "eval-pipeline":
        from cardiotic_ml.experiments import eval_pipeline
        eval_pipeline()
    elif args.cmd == "train-quality":
        from cardiotic_ml.experiments import train_quality
        train_quality(version=args.version)
    elif args.cmd == "ecg12-sex-gap":
        from cardiotic_ml.experiments_ecg12 import sex_gap_analysis
        sex_gap_analysis(args.version)
    elif args.cmd == "select-ecg12-sex":
        from cardiotic_ml.experiments_ecg12 import select_sex_weighted
        select_sex_weighted()
    elif args.cmd == "site-thresholds":
        from cardiotic_ml.experiments_ecg12 import site_thresholds_chapman
        site_thresholds_chapman(args.version, args.policy)
    elif args.cmd == "select-quality":
        from cardiotic_ml.experiments import select_quality_12
        select_quality_12()
    elif args.cmd == "select-quality-v06":
        from cardiotic_ml.experiments import select_quality_12
        select_quality_12(candidates=("v0.6",), name="quality_selection_v06")
    elif args.cmd == "quality-real":
        from cardiotic_ml.experiments import quality_real_data_for
        quality_real_data_for(args.version)
    elif args.cmd == "train-rhythm":
        from cardiotic_ml.experiments_rhythm import train_rhythm
        train_rhythm(version=args.version)
    elif args.cmd == "eval-rhythm-afdb":
        from cardiotic_ml.experiments_rhythm import eval_rhythm_afdb
        eval_rhythm_afdb(version=args.version, split=args.split)
    elif args.cmd == "select-rhythm":
        from cardiotic_ml.experiments_rhythm import select_rhythm
        select_rhythm()
    elif args.cmd == "make-rhythm-gate":
        from cardiotic_ml.experiments_rhythm import make_rhythm_gate
        make_rhythm_gate()
    elif args.cmd == "rhythm-cinc-val":
        from cardiotic_ml.experiments_rhythm import cinc_val_for
        cinc_val_for(args.version)
    elif args.cmd == "eval-rhythm-mitdb":
        from cardiotic_ml.experiments_rhythm import eval_rhythm_mitdb
        eval_rhythm_mitdb(version=args.version, split=args.split)
    elif args.cmd == "calibrate-beats":
        from cardiotic_ml.experiments_rhythm import calibrate_beats
        calibrate_beats()
    elif args.cmd == "train-beats":
        from cardiotic_ml.experiments import train_beats
        train_beats(version=args.version)
    elif args.cmd == "analyze":
        from cardiotic_ml import pipeline
        from cardiotic_ml.data import mitdb
        rec = mitdb.load_record(args.record)
        a0, a1 = int(args.start * rec.fs), int((args.start + args.seconds) * rec.fs)
        sig = rec.signal[a0:a1]
        result = pipeline.analyze(sig, rec.fs, pipeline.load_models())
        result["source"] = {"database": "mitdb", "record": args.record, "start_s": args.start, "seconds": args.seconds}
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
        print(json.dumps({"measurements": result["measurements"], "rhythm_segments": [
            {k: s[k] for k in ("start_s", "rhythm", "confidence")} for s in result["rhythm_segments"]],
            "findings": result["findings"]}, indent=2))
        if args.plot:
            pipeline.plot_strip(sig, rec.fs, result, 0.0, min(10.0, args.seconds), args.plot)
    elif args.cmd == "train-ecg12":
        from cardiotic_ml.experiments_ecg12 import train_ecg12
        train_ecg12(args.version)
    elif args.cmd == "tune-ecg12-measure":
        from cardiotic_ml.experiments_ecg12 import tune_measurements
        tune_measurements(args.version)
    elif args.cmd == "eval-ecg12-measure":
        from cardiotic_ml.experiments_ecg12 import eval_measurements
        eval_measurements(args.version, args.split)
    elif args.cmd == "eval-ecg12-external":
        from cardiotic_ml.experiments_ecg12 import eval_external_chapman
        eval_external_chapman(args.version)
    elif args.cmd == "eval-ecg12-rules":
        from cardiotic_ml.experiments_ecg12 import eval_rules
        eval_rules()
    elif args.cmd == "select-ecg12":
        from cardiotic_ml.experiments_ecg12 import select_ecg12
        select_ecg12()
    elif args.cmd == "analyze-12lead":
        from cardiotic_ml.data import ptbxl
        from cardiotic_ml.ecg12.analyze import Models12, analyze_12lead, plot_12lead
        rec = next(r for r in ptbxl.records() if r.ecg_id == args.ecg_id)
        sig = ptbxl.load_signal(rec, hr=True)
        res = analyze_12lead(sig, 500, Models12())
        res["source"] = {"dataset": "PTB-XL 1.0.3", "ecg_id": rec.ecg_id, "fold": rec.fold,
                         "cardiologist_statements": rec.codes}
        with open(args.out, "w") as f:
            json.dump(res, f, indent=2, default=float)
        if args.plot:
            plot_12lead(sig, 500, res, args.plot, title=f"(PTB-XL ECG {rec.ecg_id}, test fold)" if rec.fold == 10 else f"(PTB-XL ECG {rec.ecg_id})")
        print(json.dumps({"measurements": {k: v for k, v in res["measurements"].items() if k.endswith(("ms", "bpm", "deg"))},
                          "statements": [s["statement"] for s in res["statements"]], "notes": res["notes"]}, default=float))
    elif args.cmd == "export-engine":
        from cardiotic_ml.export import export_engine
        export_engine()
    elif args.cmd == "report":
        from cardiotic_ml.report import write_results
        print(write_results())


if __name__ == "__main__":
    main()
