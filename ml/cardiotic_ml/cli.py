"""Command line: `python -m cardiotic_ml.cli <command>`.

  download        fetch MIT-BIH (mitdb) and NSTDB noise records from PhysioNet into data/raw
  eval-qrs        score QRS detectors on all 48 MIT-BIH records (EC57-style)
  train-quality   train + test the signal-quality model
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
    q = sub.add_parser("train-quality"); q.add_argument("--epochs", type=int, default=10)
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
        train_quality(epochs=args.epochs)
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
        print(json.dumps({"measurements": result["measurements"], "findings": result["findings"]}, indent=2))
        if args.plot:
            pipeline.plot_strip(sig, rec.fs, result, 0.0, min(10.0, args.seconds), args.plot)
    elif args.cmd == "report":
        from cardiotic_ml.report import write_results
        print(write_results())


if __name__ == "__main__":
    main()
