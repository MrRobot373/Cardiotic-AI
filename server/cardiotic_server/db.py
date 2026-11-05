"""SQLite storage (standard library). One file on the hospital's server; WAL mode; schema versioned."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 5
NOTIFICATIONS_SQL = ("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, at TEXT NOT NULL, recording_id TEXT NOT NULL, level TEXT NOT NULL, "
                     "reason TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', acknowledged_by TEXT, acknowledged_at TEXT, email_status TEXT NOT NULL DEFAULT 'off', "
                     "email_attempts INTEGER NOT NULL DEFAULT 0, email_error TEXT)")
SITE_CONFIGS_SQL = ("CREATE TABLE IF NOT EXISTS site_configs (id INTEGER PRIMARY KEY, uploaded_at TEXT NOT NULL, uploaded_by TEXT NOT NULL, sha256 TEXT NOT NULL, raw TEXT NOT NULL, "
                    "site_id TEXT NOT NULL, config_version TEXT NOT NULL, approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, statements INTEGER NOT NULL, "
                    "activated_at TEXT, activated_by TEXT, deactivated_at TEXT)")
BEAT_LABELS_SQL = ("CREATE TABLE IF NOT EXISTS beat_labels (rec_id TEXT NOT NULL, beat_time REAL NOT NULL, label TEXT NOT NULL, user TEXT NOT NULL, at TEXT NOT NULL, "
                   "PRIMARY KEY (rec_id, beat_time))")
REVIEW_VERSIONS_SQL = ("CREATE TABLE IF NOT EXISTS review_versions (id INTEGER PRIMARY KEY, ecg_id TEXT NOT NULL, version INTEGER NOT NULL, at TEXT NOT NULL, "
                       "user TEXT NOT NULL, action TEXT NOT NULL, snapshot TEXT NOT NULL)")
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
    5: [  # site threshold files kept with their history
        SITE_CONFIGS_SQL,
    ],
    4: [  # Holter beat relabelling
        BEAT_LABELS_SQL,
    ],
    3: [  # password policy, critical-result notifications, review history
        "ALTER TABLE users ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN pw_changed REAL NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN pw_history TEXT NOT NULL DEFAULT '[]'",
        NOTIFICATIONS_SQL,
        REVIEW_VERSIONS_SQL,
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


class AuditKeyMissing(RuntimeError):
    """The database holds keyed audit entries but the key is not available: starting would make the log unverifiable."""


def _load_audit_key(path: str, has_keyed_entries: bool) -> bytes | None:
    """The audit chain's key: $CARDIOTIC_AUDIT_KEY, else the file $CARDIOTIC_AUDIT_KEY_FILE, else <database>.audit.key (created on first use, readable by the service user only).
    Keep it somewhere an intruder who copies the database cannot also read (another volume, the host's secret store)."""
    env = os.environ.get("CARDIOTIC_AUDIT_KEY")
    if env:
        return hashlib.sha256(env.encode()).digest()
    f = os.environ.get("CARDIOTIC_AUDIT_KEY_FILE") or path + ".audit.key"  # the file variable also lets a backup copy be verified with the live key
    if os.path.exists(f):
        return bytes.fromhex(open(f).read().strip())
    if has_keyed_entries:
        raise AuditKeyMissing(f"the audit log is keyed but neither CARDIOTIC_AUDIT_KEY nor {f} exists; restore the key (it is needed to verify the log)")
    key = secrets.token_bytes(32)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key.hex())
    return key


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
        kf = c.execute("SELECT value FROM meta WHERE key='audit_keyed_from'").fetchone()
        self._key = _load_audit_key(self.path, kf is not None)
        if kf is None:  # entries written from now on are keyed; earlier ones stay verifiable with the plain hash
            last = c.execute("SELECT COALESCE(MAX(id), 0) FROM audit").fetchone()[0]
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('audit_keyed_from', ?)", (str(last + 1),))
            kf = c.execute("SELECT value FROM meta WHERE key='audit_keyed_from'").fetchone()
        self._keyed_from = int(kf[0])

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
            prev = c.execute("SELECT id, hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["hash"] if prev else "0" * 64
            nid = (prev["id"] if prev else 0) + 1
            at = now()
            h = self._digest(nid, prev_hash, at, user, action, target)
            c.execute("INSERT INTO audit(id, at, user, action, target, prev_hash, hash) VALUES (?,?,?,?,?,?,?)", (nid, at, user, action, target, prev_hash, h))

    def _digest(self, rid: int, prev_hash: str, at: str, user: str, action: str, target: str) -> str:
        """Entries from audit_keyed_from on are HMAC-SHA256 over the entry and its number with the audit key: someone who only has the
        database file cannot recompute the chain after changing it. Earlier entries (from before keying) use the plain SHA-256."""
        if rid < self._keyed_from:
            return hashlib.sha256(json.dumps([prev_hash, at, user, action, target]).encode()).hexdigest()
        return hmac.new(self._key, json.dumps([rid, prev_hash, at, user, action, target]).encode(), hashlib.sha256).hexdigest()

    def verify_audit(self, anchor: str | None = None) -> dict:
        """Recompute the whole chain. anchor ("<entries>:<hash>", from an earlier `audit-anchor`) additionally proves that nothing up to that
        entry was changed and nothing was cut off the end since it was recorded elsewhere."""
        prev, n = "0" * 64, 0
        at_anchor = None
        want_n, _, want_hash = (anchor or "").partition(":")
        for r in self.conn().execute("SELECT * FROM audit ORDER BY id"):
            h = self._digest(r["id"], prev, r["at"], r["user"], r["action"], r["target"])
            if r["prev_hash"] != prev or r["hash"] != h:
                return {"ok": False, "first_bad_id": r["id"], "checked": n}
            prev, n = h, n + 1
            if anchor and str(n) == want_n:
                at_anchor = h
        out = {"ok": True, "entries": n, "head": prev}
        if anchor:
            if at_anchor is None or not hmac.compare_digest(at_anchor, want_hash):
                return {"ok": False, "checked": n, "anchor": "the log no longer matches the anchor recorded earlier (entries were changed or removed)"}
            out["anchor"] = f"matches the anchor at entry {want_n}"
        return out

    def anchor(self) -> dict:
        """The log's current length and head hash. Record this line somewhere the database's administrators cannot rewrite
        (the hospital's records system, a signed e-mail, a printout); `verify-audit --anchor` later proves nothing before it changed."""
        v = self.verify_audit()
        if not v["ok"]:
            return v
        return {"ok": True, "entries": v["entries"], "head": v["head"], "at": now(), "line": f"{v['entries']}:{v['head']}"}


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
