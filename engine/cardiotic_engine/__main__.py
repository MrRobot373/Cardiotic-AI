"""python -m cardiotic_engine verify | serve [--host H --port P] | analyze FILE.json [--kind ecg12|rhythm]"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cardiotic_engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="check every model file against the manifest")
    s = sub.add_parser("serve", help="run the HTTP service")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8710)
    a = sub.add_parser("analyze", help="analyse one request file (same JSON as the HTTP API)")
    a.add_argument("file")
    a.add_argument("--kind", choices=["ecg12", "rhythm"], default="ecg12")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from cardiotic_engine.registry import IntegrityError, verify

    try:
        if args.cmd == "verify":
            print(json.dumps(verify(), indent=2))
            return 0
        from cardiotic_engine.api import Engine, InputError
        from cardiotic_engine.server import _json_default, serve

        if args.cmd == "serve":
            serve(args.host, args.port).serve_forever()
            return 0
        req = json.load(open(args.file))
        eng = Engine()
        try:
            out = (eng.analyze_ecg12(req.get("leads"), req.get("fs"), req.get("units", "mV")) if args.kind == "ecg12"
                   else eng.analyze_rhythm(req.get("signal"), req.get("fs"), req.get("units", "mV"), req.get("lead")))
        except InputError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2, default=_json_default))
        return 0
    except IntegrityError as e:
        print(f"MODEL INTEGRITY CHECK FAILED: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
