"""python -m cardiotic_engine verify | serve [--host H --port P] | analyze FILE.json [--kind ecg12|rhythm] | site-config ..."""

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
    sc = sub.add_parser("site-config", help="draft a per-site operating-point file from the site's labelled ECGs (installation)")
    sc.add_argument("--dir", required=True, help="folder with the ECG files")
    sc.add_argument("--labels", required=True, help="CSV: file,statements (SCP-ECG codes separated by ;)")
    sc.add_argument("--site-id", required=True)
    sc.add_argument("--config-version", default="1")
    sc.add_argument("--policy", choices=["max_f1", "sensitivity"], default="max_f1")
    sc.add_argument("--target-sensitivity", type=float, default=0.9)
    sc.add_argument("--min-positives", type=int)
    sc.add_argument("--out", required=True)
    for p in (s, a):
        p.add_argument("--site-config", help="per-site operating-point file (default: $CARDIOTIC_SITE_CONFIG)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from cardiotic_engine.api import SiteConfigError
    from cardiotic_engine.registry import IntegrityError, verify

    try:
        if args.cmd == "verify":
            print(json.dumps(verify(), indent=2))
            return 0
        from cardiotic_engine.api import Engine, InputError
        from cardiotic_engine.server import _json_default, serve

        if args.cmd == "serve":
            serve(args.host, args.port, Engine(site_config=args.site_config)).serve_forever()
            return 0
        if args.cmd == "site-config":
            from cardiotic_engine import siteconfig
            try:
                cfg, rep = siteconfig.draft(args.dir, args.labels, args.site_id, args.config_version, args.policy, args.target_sensitivity, args.min_positives)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            siteconfig.write(cfg, rep, args.out)
            print(f"draft written to {args.out} ({len(cfg['statements'])} statements set from {rep['ecgs_used']} ECGs); the cardiology lead must review the report and fill in approved_by / approved_at")
            return 0
        req = json.load(open(args.file))
        eng = Engine(site_config=args.site_config)
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
    except SiteConfigError as e:  # refuse to start with a configuration for other models or not signed off
        print(f"SITE CONFIGURATION REFUSED: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
