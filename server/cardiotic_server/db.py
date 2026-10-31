"""SQLite storage (standard library). One file on the hospital's server; WAL mode; schema versioned."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2
# Upgrades applied in order to databases created by an older version (each step runs once).
MIGRATIONS = {
    2: [  # single sign-on and two-factor authentication
        "ALTER TABLE users ADD COLUMN source TEXT NOT NULL DEFAULT 'local'",
        "ALTER TABLE users ADD COLUMN totp_secret TEXT",
        "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN totp_last_step INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE sessions ADD COLUMN scope TEXT NOT NULL DEFAULT 'full'",
        "CREATE TABLE IF NOT EXISTS challenges (token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, user_id INTEGER, data TEXT NOT NULL DEFAULT '{}', expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)",
    ],
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('cardiologist','technician','admin')),
  title TEXT NOT NULL DEFAULT '', pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created REAL NOT NULL, last_seen REAL NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS patients (
  id TEXT PRIMARY KEY, mrn TEXT NOT NULL UNIQUE, name TEXT NOT NULL, sex TEXT NOT NULL DEFAULT '' , birth_date TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recordings (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('ecg12','holter')), patient_id TEXT NOT NULL REFERENCES patients(id),
  recorded_at TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', ordered_by TEXT NOT NULL DEFAULT '', device TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL, detail BLOB NOT NULL, signal BLOB, file_sha256 TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS recordings_patient ON recordings(patient_id);
CREATE TABLE IF NOT EXISTS reviews (
  ecg_id TEXT PRIMARY KEY REFERENCES recordings(id), status TEXT NOT NULL DEFAULT 'new', decisions TEXT NOT NULL DEFAULT '{}',
  added TEXT NOT NULL DEFAULT '[]', edits TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '', signed_by TEXT, signed_at TEXT,
  version INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, user TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY, ecg_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at TEXT NOT NULL, sent_at TEXT, next_try REAL NOT NULL DEFAULT 0);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """One connection per thread, one writer at a time (SQLite allows a single writer; the lock keeps
    transactions short and ordered instead of failing with 'database is locked')."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        self.write_lock = threading.RLock()
        c = self.conn()
        fresh = c.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone() is None
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", ("1",))
        version = int(c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
        for v in sorted(MIGRATIONS):
            if v > version:
                with self.tx() as t:
                    for stmt in MIGRATIONS[v]:
                        t.execute(stmt)
                    t.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(v),))
        self.created = fresh

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)  # explicit transactions below
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA synchronous=FULL")
            self._local.c = c
        return c

    def tx(self):
        return _Tx(self)

    def backup(self, dest: str | Path) -> None:
        """A consistent copy while the server runs."""
        out = sqlite3.connect(str(dest))
        try:
            self.conn().backup(out)
        finally:
            out.close()

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default=None):
        r = self.conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_setting(self, key: str, value) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    # ---------------------------------------------------------------- audit (tamper-evident hash chain)
    def audit(self, user: str, action: str, target: str = "", c: sqlite3.Connection | None = None) -> None:
        c = c or self.conn()
        with self.write_lock:
            prev = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["hash"] if prev else "0" * 64
            at = now()
            h = hashlib.sha256(json.dumps([prev_hash, at, user, action, target]).encode()).hexdigest()
            c.execute("INSERT INTO audit(at, user, action, target, prev_hash, hash) VALUES (?,?,?,?,?,?)", (at, user, action, target, prev_hash, h))

    def verify_audit(self) -> dict:
        prev, n = "0" * 64, 0
        for r in self.conn().execute("SELECT * FROM audit ORDER BY id"):
            h = hashlib.sha256(json.dumps([prev, r["at"], r["user"], r["action"], r["target"]]).encode()).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != h:
                return {"ok": False, "first_bad_id": r["id"], "checked": n}
            prev, n = h, n + 1
        return {"ok": True, "entries": n}


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db.write_lock.acquire()
        self.c = self.db.conn()
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, exc_type, exc, tb):
        try:
            self.c.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db.write_lock.release()
        return False
