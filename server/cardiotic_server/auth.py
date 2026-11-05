"""Accounts and sessions: scrypt password hashes, lockout after repeated failures, idle and absolute session timeouts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from .db import Database, now

ROLES = ("cardiologist", "technician", "admin")
MIN_PASSWORD = 10
MAX_FAILS, LOCK_SECONDS = 5, 300
HISTORY = 5  # a new password may not be any of the last five
REAUTH_OIDC_SECONDS = 600  # identity-provider accounts: signing needs a sign-in this recent
IDLE_SECONDS = int(os.environ.get("CARDIOTIC_IDLE_MINUTES", "15")) * 60
ABSOLUTE_SECONDS = int(os.environ.get("CARDIOTIC_SESSION_HOURS", "12")) * 3600
_N, _R, _P = 2 ** 14, 8, 1


class AuthError(Exception):
    """Wrong credentials, locked account, or no valid session. The message is safe to show."""


class ReauthError(Exception):
    """Signing needs the person to confirm who they are (403, the session stays open). The message is safe to show."""


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


def create_user(db: Database, username: str, name: str, role: str, password: str, title: str = "", must_change: bool = False) -> int:
    """must_change: the person chooses their own password at first sign-in (accounts an administrator creates)."""
    username = username.strip().lower()
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not username or not name.strip():
        raise ValueError("user name and full name are required")
    check_password_policy(password, username)
    with db.tx() as c:
        try:
            cur = c.execute("INSERT INTO users(username, name, role, title, pw_hash, created_at, must_change, pw_changed) VALUES (?,?,?,?,?,?,?,?)",
                            (username, name.strip(), role, title.strip(), hash_password(password), now(), 1 if must_change else 0, time.time()))
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError(f"user name {username!r} already exists") from None
            raise
        return cur.lastrowid


def _auth_cfg(db: Database) -> dict:
    return db.get_setting("auth", {})


def _upsert_external(db: Database, info: dict, source: str):
    """A directory or identity-provider user: created on first sign-in, name / title / role refreshed every time."""
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (info["username"],)).fetchone()
        if u is not None and u["source"] == "local":
            raise AuthError("This user name belongs to a local account; ask the administrator")
        if u is None:
            c.execute("INSERT INTO users(username, name, role, title, pw_hash, created_at, source) VALUES (?,?,?,?,?,?,?)",
                      (info["username"], info["name"], info["role"], info.get("title", ""), "!" + source, now(), source))
            db.audit(info["name"], "Account created on first sign-in", f"{source}: {info['role']}", c)
        elif (u["name"], u["role"], u["title"]) != (info["name"], info["role"], info.get("title", "")):
            c.execute("UPDATE users SET name=?, role=?, title=? WHERE id=?", (info["name"], info["role"], info.get("title", ""), u["id"]))
            if u["role"] != info["role"]:
                db.audit(info["name"], "Role changed by directory", f"{u['role']} -> {info['role']}", c)
    return db.conn().execute("SELECT * FROM users WHERE username=?", (info["username"],)).fetchone()


def _session(db: Database, u, scope: str = "full", how: str = "") -> tuple[str, dict]:
    token, t = secrets.token_urlsafe(32), time.time()
    with db.tx() as c:
        c.execute("UPDATE users SET failed=0, locked_until=0 WHERE id=?", (u["id"],))
        c.execute("INSERT INTO sessions(token_hash, user_id, created, last_seen, expires, scope) VALUES (?,?,?,?,?,?)",
                  (_th(token), u["id"], t, t, t + ABSOLUTE_SECONDS, scope))
        db.audit(u["name"], "Signed in" + (f" ({how})" if how else ""), u["title"] or u["role"], c)
    return token, {**public(u), "enrol_2fa": scope == "enrol", "change_password": scope == "password"}


def _fail(db: Database, u, username: str, what: str = "Sign-in failed") -> None:
    if u is None:
        db.audit(username or "?", "Sign-in refused", "unknown account")
    else:
        t = time.time()
        with db.tx() as c:
            fails = u["failed"] + 1
            c.execute("UPDATE users SET failed=?, locked_until=? WHERE id=?", (fails % MAX_FAILS if fails >= MAX_FAILS else fails, t + LOCK_SECONDS if fails >= MAX_FAILS else 0, u["id"]))
            db.audit(username, what, f"attempt {fails}", c)
    raise AuthError("Wrong user name or password, or the account is locked")


def login(db: Database, username: str, password: str, ldap_options: dict | None = None) -> dict:
    """Password step. Returns {"token", "user"} for a session, or {"totp_required": True, "challenge"} when a
    two-factor code is needed next. Same error for unknown user, wrong password and locked account.
    Local accounts check their own password; directory accounts (and unknown names, when LDAP is on) bind to LDAP."""
    from . import sso

    username = (username or "").strip().lower()
    cfg = _auth_cfg(db)
    c = db.conn()
    u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    t = time.time()
    if u is not None and (not u["active"] or u["locked_until"] > t):
        verify_password(password or "", _DUMMY)
        db.audit(username, "Sign-in refused", "locked or deactivated account")
        raise AuthError("Wrong user name or password, or the account is locked")
    if (u is None or u["source"] == "ldap") and cfg.get("ldap", {}).get("enabled"):
        try:
            info = sso.ldap_authenticate(cfg["ldap"], username, password or "", **(ldap_options or {}))
        except Exception as e:  # directory unreachable: say so, it is not the user's fault
            import logging
            logging.getLogger("cardiotic_server").warning("LDAP sign-in failed: %s", e)
            raise AuthError("The hospital directory cannot be reached; try again or ask IT") from None
        if info is None:
            _fail(db, u, username)
        u = _upsert_external(db, info, "ldap")
        how = "directory"
    else:
        ok = verify_password(password or "", u["pw_hash"] if u is not None and u["source"] == "local" else _DUMMY)
        if u is None or u["source"] != "local" or not ok:
            _fail(db, u, username)
        how = ""
    if u["totp_enabled"]:
        challenge = secrets.token_urlsafe(32)
        with db.tx() as w:
            w.execute("INSERT INTO challenges(token_hash, kind, user_id, expires) VALUES (?,?,?,?)", (_th(challenge), "totp", u["id"], t + 300))
        return {"totp_required": True, "challenge": challenge}
    token, user = _session(db, u, _scope_after_password(cfg, u), how)
    return {"token": token, "user": user}


def password_expired(cfg: dict, u) -> bool:
    days = int(cfg.get("password_max_days", 0) or 0)
    return bool(days) and u["source"] == "local" and u["pw_changed"] > 0 and time.time() - u["pw_changed"] > days * 86400


def _scope_after_password(cfg: dict, u) -> str:
    """'password': the person must choose a new password first; 'enrol': two-factor set-up is required first."""
    if u["source"] == "local" and (u["must_change"] or password_expired(cfg, u)):
        return "password"
    return "enrol" if cfg.get("require_2fa") and not u["totp_enabled"] else "full"


def login_totp(db: Database, challenge: str, code: str) -> dict:
    from . import sso

    c = db.conn()
    ch = c.execute("SELECT * FROM challenges WHERE token_hash=? AND kind='totp'", (_th(challenge or ""),)).fetchone()
    if ch is None or ch["expires"] < time.time() or ch["attempts"] >= 5:
        raise AuthError("The sign-in expired; enter your password again")
    u = c.execute("SELECT * FROM users WHERE id=?", (ch["user_id"],)).fetchone()
    step = sso.totp_verify(u["totp_secret"], code, u["totp_last_step"])
    if step is None:
        with db.tx() as w:
            w.execute("UPDATE challenges SET attempts=attempts+1 WHERE token_hash=?", (ch["token_hash"],))
        _fail(db, u, u["username"], "Two-factor code wrong")
    with db.tx() as w:
        w.execute("DELETE FROM challenges WHERE token_hash=?", (ch["token_hash"],))
        w.execute("UPDATE users SET totp_last_step=? WHERE id=?", (step, u["id"]))
    token, user = _session(db, u, _scope_after_password(_auth_cfg(db), u), "two-factor")
    return {"token": token, "user": user}


def totp_setup(db: Database, user: dict, issuer: str) -> dict:
    from . import sso

    secret = sso.new_totp_secret()
    with db.tx() as c:
        if c.execute("SELECT totp_enabled, source FROM users WHERE id=?", (user["id"],)).fetchone()["source"] == "oidc":
            raise ValueError("accounts that sign in through the identity provider use its two-factor sign-in")
        c.execute("UPDATE users SET totp_secret=?, totp_enabled=0 WHERE id=?", (secret, user["id"]))
    return {"secret": secret, "uri": sso.totp_uri(secret, user["username"], issuer)}


def totp_enable(db: Database, user: dict, code: str, token: str) -> None:
    from . import sso

    u = db.conn().execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if not u["totp_secret"]:
        raise ValueError("start the set-up first")
    step = sso.totp_verify(u["totp_secret"], code, u["totp_last_step"])
    if step is None:
        raise ValueError("that code is not right; check the time on the phone and try the next code")
    with db.tx() as c:
        c.execute("UPDATE users SET totp_enabled=1, totp_last_step=? WHERE id=?", (step, u["id"]))
        c.execute("UPDATE sessions SET scope='full' WHERE token_hash=?", (_th(token),))
        db.audit(u["name"], "Two-factor sign-in turned on", "", c)


def oidc_session(db: Database, info: dict) -> tuple[str, dict]:
    u = _upsert_external(db, info, "oidc")
    if not u["active"]:
        raise AuthError("This account is deactivated")
    return _session(db, u, "full", "identity provider")


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public(u) -> dict:
    keys = u.keys() if hasattr(u, "keys") else u
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"], "title": u["title"],
            "two_factor": bool(u["totp_enabled"]) if "totp_enabled" in keys else False, "source": u["source"] if "source" in keys else "local"}


def session_user(db: Database, token: str | None) -> dict:
    if not token:
        raise AuthError("Sign in required")
    t = time.time()
    c = db.conn()
    r = c.execute("SELECT s.*, u.username, u.name, u.role, u.title, u.active, u.id AS uid, u.totp_enabled, u.source FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", (_th(token),)).fetchone()
    if r is None or not r["active"] or r["expires"] < t or r["last_seen"] + IDLE_SECONDS < t:
        if r is not None:
            with db.tx() as w:
                w.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))
        raise AuthError("Session expired: sign in again")
    if t - r["last_seen"] > 30:  # keep writes rare
        with db.tx() as w:
            w.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (t, _th(token)))
    return {"id": r["uid"], "username": r["username"], "name": r["name"], "role": r["role"], "title": r["title"],
            "two_factor": bool(r["totp_enabled"]), "source": r["source"], "scope": r["scope"], "session_created": r["created"]}


def logout(db: Database, token: str | None, user: dict | None = None) -> None:
    if token:
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))
            if user:
                db.audit(user["name"], "Signed out", "", c)


def _check_history(u, password: str) -> None:
    for old in [u["pw_hash"], *json.loads(u["pw_history"] or "[]")]:
        if verify_password(password, old):
            raise ValueError(f"choose a password you have not used before (the last {HISTORY} are remembered)")


def _store_password(c, u, password: str, must_change: bool) -> None:
    hist = ([u["pw_hash"]] + json.loads(u["pw_history"] or "[]"))[:HISTORY] if u["pw_hash"] and not u["pw_hash"].startswith("!") else []
    c.execute("UPDATE users SET pw_hash=?, pw_history=?, pw_changed=?, must_change=?, failed=0, locked_until=0 WHERE id=?",
              (hash_password(password), json.dumps(hist), time.time(), 1 if must_change else 0, u["id"]))


def set_password(db: Database, username: str, password: str, must_change: bool = False) -> None:
    """An administrator's reset (must_change=True: the person chooses a new one at next sign-in) or the command line."""
    check_password_policy(password, username)
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE username=? AND source='local'", (username.strip().lower(),)).fetchone()
        if u is None:
            raise ValueError("no such local user (directory and identity-provider accounts change their password there)")
        _store_password(c, u, password, must_change)
        c.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))


def change_own_password(db: Database, user: dict, current: str, new: str, token: str) -> None:
    """The signed-in person changes their own password: the current one is checked, old ones are refused,
    their other sessions end, this one becomes a full session (or two-factor set-up, if the hospital requires it)."""
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if u["source"] != "local":
        raise ValueError("this account's password is managed by the hospital directory or identity provider")
    if not verify_password(current or "", u["pw_hash"]):
        raise ReauthError("the current password is not right")
    check_password_policy(new, u["username"])
    _check_history(u, new)
    with db.tx() as c:
        _store_password(c, u, new, False)
        u2 = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
        c.execute("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (u["id"], _th(token)))
        c.execute("UPDATE sessions SET scope=? WHERE token_hash=?", (_scope_after_password(_auth_cfg(db), u2), _th(token)))
        db.audit(u["name"], "Changed own password", "", c)


def reauthenticate(db: Database, user: dict, password: str = "", code: str = "", ldap_options: dict | None = None) -> str:
    """Confirm that the signed-in person is the one at the keyboard now (before a signature). Returns how.
    A two-factor code works for anyone who has one; otherwise local and directory accounts give their password,
    and identity-provider accounts need a sign-in in the last 10 minutes. Wrong answers count towards the lockout."""
    from . import sso

    u = db.conn().execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if code and u["totp_enabled"]:
        step = sso.totp_verify(u["totp_secret"], code, u["totp_last_step"])
        if step is not None:
            with db.tx() as c:
                c.execute("UPDATE users SET totp_last_step=?, failed=0 WHERE id=?", (step, u["id"]))
            return "two-factor code"
        _reauth_fail(db, u, "two-factor code")
    if u["source"] == "oidc":
        if time.time() - float(user.get("session_created") or 0) <= REAUTH_OIDC_SECONDS:
            return "recent identity-provider sign-in"
        raise ReauthError("sign out and sign in again through the identity provider to sign reports (or use your two-factor code)")
    if not password:
        raise ReauthError("enter your password to sign")
    if u["source"] == "ldap":
        cfg = _auth_cfg(db).get("ldap", {})
        try:
            ok = sso.ldap_authenticate(cfg, u["username"], password, **(ldap_options or {})) is not None
        except Exception:
            raise ReauthError("the hospital directory cannot be reached; try again") from None
    else:
        ok = verify_password(password, u["pw_hash"])
    if not ok:
        _reauth_fail(db, u, "password")
    with db.tx() as c:
        c.execute("UPDATE users SET failed=0 WHERE id=?", (u["id"],))
    return "password"


def _reauth_fail(db: Database, u, what: str) -> None:
    t = time.time()
    fails = u["failed"] + 1
    with db.tx() as c:
        if fails >= MAX_FAILS:  # same lockout as sign-in: the account is locked and every session ends
            c.execute("UPDATE users SET failed=0, locked_until=? WHERE id=?", (t + LOCK_SECONDS, u["id"]))
            c.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
        else:
            c.execute("UPDATE users SET failed=? WHERE id=?", (fails, u["id"]))
        db.audit(u["name"], "Signature confirmation failed", f"{what}, attempt {fails}", c)
    if fails >= MAX_FAILS:
        raise AuthError("Too many wrong attempts: the account is locked for 5 minutes")
    raise ReauthError(f"that {what} is not right")
