"""cardiotic-server serve | init | create-user | set-password | backup | verify-audit"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cardiotic-server")
    ap.add_argument("--db", default=os.environ.get("CARDIOTIC_DB", "cardiotic.db"), help="SQLite database file (default $CARDIOTIC_DB or ./cardiotic.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8720)
    s.add_argument("--static", default=os.environ.get("CARDIOTIC_STATIC"), help="folder with the built web app (frontend/dist)")
    s.add_argument("--site-config", default=os.environ.get("CARDIOTIC_SITE_CONFIG"), help="signed-off per-site operating-point file")
    u = sub.add_parser("create-user")
    u.add_argument("username"); u.add_argument("name"); u.add_argument("role", choices=["cardiologist", "technician", "admin"]); u.add_argument("--title", default="")
    p = sub.add_parser("set-password"); p.add_argument("username")
    b = sub.add_parser("backup"); b.add_argument("dest")
    sub.add_parser("verify-audit")
    sub.add_parser("init")
    ls = sub.add_parser("live-simulator", help="stream a recording to Live Assist like a monitor gateway")
    ls.add_argument("--url", required=True); ls.add_argument("--token", required=True); ls.add_argument("--file", required=True, help="any ECG file the engine reads; the first lead (or II) is streamed")
    ls.add_argument("--speed", type=float, default=1.0); ls.add_argument("--vitals", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from . import auth
    from .db import Database

    if args.cmd == "serve":
        from cardiotic_engine.api import Engine, SiteConfigError
        from cardiotic_engine.registry import IntegrityError
        from .app import make_app
        try:
            engine = Engine(site_config=args.site_config)
        except IntegrityError as e:
            print(f"MODEL INTEGRITY CHECK FAILED: {e}", file=sys.stderr)
            return 3
        except SiteConfigError as e:
            print(f"SITE CONFIGURATION REFUSED: {e}", file=sys.stderr)
            return 4
        httpd, _, _ = make_app(args.db, args.static, engine, args.host, args.port)
        logging.getLogger("cardiotic_server").info("listening on http://%s:%d (database %s)", args.host, args.port, args.db)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if args.cmd == "live-simulator":
        from cardiotic_engine.ingest import parse
        from . import simulator
        ecg = parse(open(args.file, "rb").read())
        lead = "II" if "II" in ecg.leads else next(iter(ecg.leads))
        print(f"streaming lead {lead} at {ecg.fs:g} Hz to {args.url} (Ctrl-C to stop)")
        try:
            simulator.stream(args.url, args.token, ecg.leads[lead], ecg.fs, args.speed, vitals=args.vitals)
        except KeyboardInterrupt:
            pass
        return 0
    db = Database(args.db)
    try:
        return _run(args, db, auth)
    except ValueError as e:  # a refused password, an unknown user…: say why, no traceback
        print(f"error: {e}", file=sys.stderr)
        return 2


def _run(args, db, auth) -> int:
    if args.cmd == "init":
        print(f"database ready: {Path(args.db).resolve()}")
    elif args.cmd == "create-user":
        pw = os.environ.get("CARDIOTIC_NEW_PASSWORD") or getpass.getpass("Password: ")
        auth.create_user(db, args.username, args.name, args.role, pw, args.title)
        db.audit("cli", "Created user", f"{args.username} ({args.role})")
        print("created", args.username)
    elif args.cmd == "set-password":
        pw = os.environ.get("CARDIOTIC_NEW_PASSWORD") or getpass.getpass("New password: ")
        auth.set_password(db, args.username, pw)
        db.audit("cli", "Reset password", args.username)
        print("password changed; the user's sessions were ended")
    elif args.cmd == "backup":
        db.backup(args.dest)
        print("backup written to", args.dest)
    elif args.cmd == "verify-audit":
        r = db.verify_audit()
        print(r)
        return 0 if r["ok"] else 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
