"""Command line: `python -m cardiotic_ml.cli <command>`.

  download        fetch MIT-BIH (mitdb) and NSTDB noise records from PhysioNet into data/raw
  eval-qrs        score QRS detectors on all 48 MIT-BIH records (EC57-style)
  train-quality   train + test the signal-quality model (--version v0.1 | v0.2)
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
    q = sub.add_parser("train-quality"); q.add_argument("--version", default="v0.3", choices=["v0.1", "v0.2", "v0.3"])
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
    elif args.cmd == "report":
        from cardiotic_ml.report import write_results
        print(write_results())


if __name__ == "__main__":
    main()
