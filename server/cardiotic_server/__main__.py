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
    db = Database(args.db)
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
