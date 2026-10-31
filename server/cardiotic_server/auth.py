"""Accounts and sessions: scrypt password hashes, lockout after repeated failures, idle and absolute session timeouts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

from .db import Database, now

ROLES = ("cardiologist", "technician", "admin")
MIN_PASSWORD = 10
MAX_FAILS, LOCK_SECONDS = 5, 300
IDLE_SECONDS = int(os.environ.get("CARDIOTIC_IDLE_MINUTES", "15")) * 60
ABSOLUTE_SECONDS = int(os.environ.get("CARDIOTIC_SESSION_HOURS", "12")) * 3600
_N, _R, _P = 2 ** 14, 8, 1


class AuthError(Exception):
    """Wrong credentials, locked account, or no valid session. The message is safe to show."""


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("not-a-real-password")  # unknown users cost the same time as wrong passwords


def check_password_policy(password: str, username: str = "") -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must have at least {MIN_PASSWORD} characters")
    if username and username.lower() in password.lower():
        raise ValueError("password must not contain the user name")
    if len(set(password)) < 4:
        raise ValueError("password is too repetitive")


def create_user(db: Database, username: str, name: str, role: str, password: str, title: str = "") -> int:
    username = username.strip().lower()
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not username or not name.strip():
        raise ValueError("user name and full name are required")
    check_password_policy(password, username)
    with db.tx() as c:
        try:
            cur = c.execute("INSERT INTO users(username, name, role, title, pw_hash, created_at) VALUES (?,?,?,?,?,?)",
                            (username, name.strip(), role, title.strip(), hash_password(password), now()))
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError(f"user name {username!r} already exists") from None
            raise
        return cur.lastrowid


def login(db: Database, username: str, password: str) -> tuple[str, dict]:
    """Returns (session token, user). Same error for unknown user, wrong password and locked account."""
    username = (username or "").strip().lower()
    c = db.conn()
    u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    t = time.time()
    ok = verify_password(password or "", u["pw_hash"] if u else _DUMMY)
    if u is None or not u["active"] or u["locked_until"] > t:
        db.audit(username or "?", "Sign-in refused", "locked or unknown account")
        raise AuthError("Wrong user name or password, or the account is locked")
    if not ok:
        with db.tx() as c:
            fails = u["failed"] + 1
            c.execute("UPDATE users SET failed=?, locked_until=? WHERE id=?", (fails % MAX_FAILS if fails >= MAX_FAILS else fails, t + LOCK_SECONDS if fails >= MAX_FAILS else 0, u["id"]))
            db.audit(username, "Sign-in failed", f"attempt {fails}", c)
        raise AuthError("Wrong user name or password, or the account is locked")
    token = secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute("UPDATE users SET failed=0, locked_until=0 WHERE id=?", (u["id"],))
        c.execute("INSERT INTO sessions(token_hash, user_id, created, last_seen, expires) VALUES (?,?,?,?,?)",
                  (_th(token), u["id"], t, t, t + ABSOLUTE_SECONDS))
        db.audit(u["name"], "Signed in", u["title"] or u["role"], c)
    return token, public(u)


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public(u) -> dict:
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"], "title": u["title"]}


def session_user(db: Database, token: str | None) -> dict:
    if not token:
        raise AuthError("Sign in required")
    t = time.time()
    c = db.conn()
    r = c.execute("SELECT s.*, u.username, u.name, u.role, u.title, u.active, u.id AS uid FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", (_th(token),)).fetchone()
    if r is None or not r["active"] or r["expires"] < t or r["last_seen"] + IDLE_SECONDS < t:
        if r is not None:
            with db.tx() as w:
                w.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))
        raise AuthError("Session expired: sign in again")
    if t - r["last_seen"] > 30:  # keep writes rare
        with db.tx() as w:
            w.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (t, _th(token)))
    return {"id": r["uid"], "username": r["username"], "name": r["name"], "role": r["role"], "title": r["title"]}


def logout(db: Database, token: str | None, user: dict | None = None) -> None:
    if token:
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))
            if user:
                db.audit(user["name"], "Signed out", "", c)


def set_password(db: Database, username: str, password: str) -> None:
    check_password_policy(password, username)
    with db.tx() as c:
        cur = c.execute("UPDATE users SET pw_hash=?, failed=0, locked_until=0 WHERE username=?", (hash_password(password), username.strip().lower()))
        if cur.rowcount == 0:
            raise ValueError("no such user")
        c.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=?)", (username.strip().lower(),))
