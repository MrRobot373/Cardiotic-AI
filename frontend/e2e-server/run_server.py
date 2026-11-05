"""Start a Cardiotic server for the end-to-end test: fresh database, three users, the built web app, sample ECG files."""

import os
import sys
import tempfile
import threading
from pathlib import Path

import logging

import numpy as np

logging.basicConfig(level=logging.INFO)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "tests"))
import ingest_writers as w  # noqa: E402
from cardiotic_engine.api import Engine  # noqa: E402
from cardiotic_server import auth  # noqa: E402
from cardiotic_server.app import make_app  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from make_files import make  # noqa: E402

make()

db = Path(tempfile.mkdtemp()) / "e2e.db"
httpd, store, _ = make_app(db, ROOT / "frontend" / "dist", Engine(), "127.0.0.1", int(os.environ.get("PORT", "8721")))
pw = "correct horse battery"
for u, n, r, t in (("arao", "Dr. Ananya Rao", "cardiologist", "Consultant cardiologist"), ("rsawant", "Rohit Sawant", "technician", "ECG technician"), ("kdesai", "Kiran Desai", "admin", "IT administrator")):
    auth.create_user(store.db, u, n, r, pw, t)
store.update_site({"role": "admin", "name": "setup"}, {"siteName": "Pulse Care"})
# the critical-result banner is exercised with one notification in this throw-away database (creation on upload is covered by the server tests)
with store.db.tx() as c:
    c.execute("INSERT INTO notifications(at, recording_id, level, reason, location) VALUES (?,?,?,?,?)",
              ("2026-01-01T00:00:00+00:00", "E900001", "critical", "Complete heart block suggested", "Ward 4"))
print("ready", flush=True)
httpd.serve_forever()
