"""Keyed and anchored audit chain, the command-line tool, the monitor simulator."""

import hashlib
import io
import json
import threading
from contextlib import redirect_stderr, redirect_stdout

import numpy as np
import pytest
from helpers import Client

from cardiotic_server import __main__ as cli
from cardiotic_server import simulator
from cardiotic_server.db import AuditKeyMissing, Database


def _db(tmp_path, name="a.db"):
    return Database(tmp_path / name)


def _rewrite_without_key(db):
    """What an intruder with only the database file can do: change an entry and recompute the chain with plain SHA-256."""
    rows = db.conn().execute("SELECT * FROM audit ORDER BY id").fetchall()
    prev = "0" * 64
    for r in rows:
        action = "Nothing happened" if r["id"] == 2 else r["action"]
        h = hashlib.sha256(json.dumps([prev, r["at"], r["user"], action, r["target"]]).encode()).hexdigest()
        db.conn().execute("UPDATE audit SET action=?, prev_hash=?, hash=? WHERE id=?", (action, prev, h, r["id"]))
        prev = h


def test_chain_is_keyed_so_a_rebuilt_chain_does_not_verify(tmp_path):
    db = _db(tmp_path)
    for i in range(4):
        db.audit("u", f"act{i}", "t")
    assert db.verify_audit()["ok"]
    _rewrite_without_key(db)
    out = db.verify_audit()
    assert out["ok"] is False and out["first_bad_id"] == 1  # even entry 1: it was HMAC-ed, a plain recompute differs


def test_key_file_is_created_private_and_needed_to_verify(tmp_path):
    db = _db(tmp_path)
    db.audit("u", "a", "t")
    key = tmp_path / "a.db.audit.key"
    assert key.exists() and oct(key.stat().st_mode & 0o777) == "0o600"
    db.conn().close()
    key.rename(tmp_path / "moved.key")
    with pytest.raises(AuditKeyMissing):  # starting without the key would make the log unverifiable: refuse
        Database(tmp_path / "a.db")
    (tmp_path / "moved.key").rename(key)
    assert Database(tmp_path / "a.db").verify_audit()["ok"]


def test_key_from_environment_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("CARDIOTIC_AUDIT_KEY", "a long secret kept in the host's secret store")
    db = _db(tmp_path, "e.db")
    db.audit("u", "a", "t")
    assert not (tmp_path / "e.db.audit.key").exists() and db.verify_audit()["ok"]
    monkeypatch.setenv("CARDIOTIC_AUDIT_KEY", "another secret")
    assert Database(tmp_path / "e.db").verify_audit()["ok"] is False  # wrong key: nothing verifies


def test_database_from_before_keying_keeps_verifying_and_continues_keyed(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    db = Database(path)
    db.conn().execute("DELETE FROM meta WHERE key='audit_keyed_from'")  # as a database created by an earlier version
    db.conn().execute("DELETE FROM audit")
    prev = "0" * 64
    for i in range(1, 4):  # three plain-SHA-256 entries, written the old way
        h = hashlib.sha256(json.dumps([prev, f"2026-01-0{i}T00:00:00+00:00", "u", f"old{i}", "t"]).encode()).hexdigest()
        db.conn().execute("INSERT INTO audit(id, at, user, action, target, prev_hash, hash) VALUES (?,?,?,?,?,?,?)", (i, f"2026-01-0{i}T00:00:00+00:00", "u", f"old{i}", "t", prev, h))
        prev = h
    db.conn().close()
    (tmp_path / "old.db.audit.key").unlink()
    db2 = Database(path)
    assert db2.verify_audit()["entries"] == 3
    db2.audit("u", "new", "t")
    out = db2.verify_audit()
    assert out["ok"] and out["entries"] == 4
    assert db2.conn().execute("SELECT value FROM meta WHERE key='audit_keyed_from'").fetchone()[0] == "4"
    sqlite3.connect(path).execute("UPDATE audit SET action='changed' WHERE id=1").connection.commit()
    assert Database(path).verify_audit()["first_bad_id"] == 1  # the old part is still protected


def test_anchor_proves_nothing_was_changed_or_cut_off(tmp_path):
    db = _db(tmp_path)
    for i in range(5):
        db.audit("u", f"act{i}", "t")
    line = db.anchor()["line"]
    assert db.verify_audit(line)["anchor"].startswith("matches")
    db.audit("u", "later", "t")
    assert db.verify_audit(line)["ok"]  # growing is fine
    db.conn().execute("DELETE FROM audit WHERE id>=4")  # cutting the end off: the chain itself is still valid
    assert db.verify_audit()["ok"] and db.verify_audit(line)["ok"] is False
    assert db.verify_audit("5:" + "0" * 64)["ok"] is False


def test_audit_anchor_endpoint_is_admin_only(server):
    from test_server import client
    a = client(server, "kdesai")
    out = a.call("GET", "/api/audit/anchor", expect=200)[1]
    assert out["entries"] >= 1 and len(out["head"]) == 64
    assert a.call("GET", "/api/audit/verify?anchor=" + out["line"], expect=200)[1]["ok"]
    assert client(server, "arao").call("GET", "/api/audit/anchor")[0] == 403


# ------------------------------------------------------------------ command line
def _run(db, *args, env=None, monkeypatch=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(["--db", str(db), *args])
    return code, out.getvalue(), err.getvalue()


def test_cli_init_users_backup_and_audit(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    assert _run(db, "init")[0] == 0
    monkeypatch.setenv("CARDIOTIC_NEW_PASSWORD", "A-long-first-password-1")
    code, out, _ = _run(db, "create-user", "arao", "Dr. Ananya Rao", "cardiologist", "--title", "Consultant")
    assert code == 0 and "created arao" in out
    code, _, err = _run(db, "create-user", "arao", "Dr. Again", "cardiologist")
    assert code == 2 and "already exists" in err
    monkeypatch.setenv("CARDIOTIC_NEW_PASSWORD", "short")
    assert _run(db, "set-password", "arao")[0] == 2
    monkeypatch.setenv("CARDIOTIC_NEW_PASSWORD", "A-second-long-password-2")
    assert _run(db, "set-password", "arao")[0] == 0
    code, out, _ = _run(db, "verify-audit")
    assert code == 0 and "'ok': True" in out
    code, line, _ = _run(db, "audit-anchor")
    assert code == 0 and line.strip().split(":")[0].isdigit()
    assert _run(db, "verify-audit", "--anchor", line.strip())[0] == 0
    code, out, _ = _run(db, "backup", str(tmp_path / "copy.db"))
    assert code == 0 and (tmp_path / "copy.db").exists() and "audit key is NOT in the backup" in out
    code, _, err = _run(tmp_path / "copy.db", "verify-audit")  # a copy has no key next to it: said plainly, not a traceback
    assert code == 6 and "audit log is keyed" in err
    monkeypatch.setenv("CARDIOTIC_AUDIT_KEY_FILE", str(tmp_path / "c.db.audit.key"))
    assert _run(tmp_path / "copy.db", "verify-audit")[0] == 0  # with the live key the copy verifies (what backup.sh does)
    monkeypatch.delenv("CARDIOTIC_AUDIT_KEY_FILE")
    import sqlite3
    sqlite3.connect(db).execute("UPDATE audit SET action='x' WHERE id=1").connection.commit()
    assert _run(db, "verify-audit")[0] == 5  # tampering: a non-zero exit code for monitoring


def test_cli_refuses_to_start_with_a_changed_model(tmp_path, monkeypatch):
    import cardiotic_engine.api as api
    from cardiotic_engine.registry import IntegrityError
    monkeypatch.setattr(api, "Engine", lambda **k: (_ for _ in ()).throw(IntegrityError("model file changed")))
    code, _, err = _run(tmp_path / "s.db", "serve", "--port", "0")
    assert code == 3 and "MODEL INTEGRITY CHECK FAILED" in err


def test_cli_refuses_a_bad_site_config(tmp_path, monkeypatch):
    import cardiotic_engine.api as api
    monkeypatch.setattr(api, "Engine", lambda **k: (_ for _ in ()).throw(api.SiteConfigError("not signed off")))
    code, _, err = _run(tmp_path / "s.db", "serve", "--port", "0", "--site-config", "/nope.json")
    assert code == 4 and "SITE CONFIGURATION REFUSED" in err


# ------------------------------------------------------------------ simulator
def test_simulator_streams_chunks_with_the_device_token(server):
    from test_server import client
    a = client(server, "kdesai")
    token = a.call("POST", "/api/live/beds", {"bed": "T1", "unit": "ICU"}, expect=201)[1]["device_token"]
    stop = threading.Event()
    seen = []
    real = simulator.urllib.request.urlopen

    def spy(req, timeout=10):
        seen.append((req.full_url, req.headers.get("X-device-token"), json.loads(req.data)))
        stop.set()
        return real(req, timeout=timeout)

    simulator.urllib.request.urlopen = spy
    try:
        sig = np.sin(np.linspace(0, 40, 2000))
        simulator.stream(server.base, token, sig, 500, speed=1000, chunk_s=1.0, vitals=True, stop=stop)
    finally:
        simulator.urllib.request.urlopen = real
    url, tok, payload = seen[0]
    assert url.endswith("/api/live/ingest") and tok == token and payload["fs"] == 500 and len(payload["samples"]) == 500 and 95 <= payload["vitals"]["spo2"] <= 99
    assert a.call("GET", "/api/live", expect=200)


def test_simulator_stops_at_the_end_when_not_looping(server):
    from test_server import client
    token = client(server, "kdesai").call("POST", "/api/live/beds", {"bed": "T2", "unit": "ICU"}, expect=201)[1]["device_token"]
    simulator.stream(server.base, token, np.zeros(1000), 500, speed=1000, chunk_s=1.0, loop=False)  # two chunks, then returns
