"""Critical-result notifications.

When an ECG arrives whose triage is critical (complete heart block, AF/flutter >= 120 bpm, QTc >= 500 ms with a
narrow QRS, rate >= 150 or < 40), a notification is created in the same transaction as the recording. Every
signed-in cardiologist and technician sees it at once (banner, optional sound) until someone acknowledges it;
the acknowledgement is audited. Optionally an e-mail goes to a ward or on-call address through the hospital's
mail server. The e-mail carries no patient name or MRN: only the recording number, location, the reason and a
link, so it is safe on a pager gateway. The triage is a reading-order aid: a notification never replaces the
hospital's own critical-result procedure.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage

from .db import now

log = logging.getLogger("cardiotic_server.notify")
DEFAULT = {"levels": ["critical"], "sound": True, "app_url": "",
           "email": {"enabled": False, "host": "", "port": 587, "security": "starttls", "username": "", "password": "", "sender": "", "to": []}}
MAX_ATTEMPTS = 6


def settings(db) -> dict:
    s = db.get_setting("notify", {})
    return {**DEFAULT, **s, "email": {**DEFAULT["email"], **s.get("email", {})}}


def validate(b: dict, current: dict) -> dict:
    levels = [x for x in b.get("levels", current["levels"]) if x in ("critical", "urgent")]
    e = b.get("email", {}) if isinstance(b.get("email"), dict) else {}
    cur_e = current["email"]
    email = {"enabled": bool(e.get("enabled", cur_e["enabled"])), "host": str(e.get("host", cur_e["host"])).strip(),
             "port": int(e.get("port", cur_e["port"])), "security": str(e.get("security", cur_e["security"])),
             "username": str(e.get("username", cur_e["username"])).strip(),
             "password": cur_e["password"] if e.get("password") in (None, "********") else str(e.get("password")),
             "sender": str(e.get("sender", cur_e["sender"])).strip(),
             "to": [str(x).strip() for x in e.get("to", cur_e["to"]) if str(x).strip()]}
    if email["security"] not in ("starttls", "ssl", "none"):
        raise ValueError("email security must be starttls, ssl or none")
    if not 0 < email["port"] < 65536:
        raise ValueError("email port must be 1-65535")
    if email["enabled"]:
        if not email["host"] or not email["sender"] or not email["to"]:
            raise ValueError("e-mail needs the mail server, a sender address and at least one recipient")
        bad = [a for a in [email["sender"], *email["to"]] if "@" not in a or " " in a]
        if bad:
            raise ValueError(f"not an e-mail address: {bad[0]}")
    url = str(b.get("app_url", current["app_url"])).strip()
    if url and not url.startswith(("https://", "http://")):
        raise ValueError("app_url must start with https://")
    return {"levels": levels, "sound": bool(b.get("sound", current["sound"])), "app_url": url, "email": email}


def public(cfg: dict) -> dict:
    return {**cfg, "email": {**cfg["email"], "password": "********" if cfg["email"]["password"] else ""}}


def create(store, c, recording_id: str, tri: dict, location: str) -> int | None:
    """Inside the recording's transaction: a notification when the triage level is one the site notifies on."""
    cfg = settings(store.db)
    if tri["priority"] not in cfg["levels"]:
        return None
    cur = c.execute("INSERT INTO notifications(at, recording_id, level, reason, location, email_status) VALUES (?,?,?,?,?,?)",
                    (now(), recording_id, tri["priority"], tri["reason"], location or "", "pending" if cfg["email"]["enabled"] else "off"))
    store.db.audit("Cardiotic AI", f"{tri['priority'].capitalize()} result notification raised", f"{recording_id}: {tri['reason']}", c)
    return cur.lastrowid


def open_items(db, limit: int = 50) -> list[dict]:
    rows = db.conn().execute("SELECT id, at, recording_id, level, reason, location FROM notifications WHERE acknowledged_at IS NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def recent(db, limit: int = 100) -> list[dict]:
    rows = db.conn().execute("SELECT id, at, recording_id, level, reason, location, acknowledged_by, acknowledged_at, email_status, email_error FROM notifications ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def acknowledge(db, user: dict, nid: int) -> None:
    with db.tx() as c:
        r = c.execute("SELECT recording_id, acknowledged_at FROM notifications WHERE id=?", (nid,)).fetchone()
        if r is None:
            raise KeyError(nid)
        if r["acknowledged_at"]:
            return
        c.execute("UPDATE notifications SET acknowledged_by=?, acknowledged_at=? WHERE id=?", (user["name"], now(), nid))
        db.audit(user["name"], "Acknowledged critical result notification", r["recording_id"], c)


def compose(cfg: dict, n: dict, site: str) -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = f"[Cardiotic AI] {n['level'].upper()} ECG {n['recording_id']}" + (f" - {n['location']}" if n["location"] else "")
    m["From"], m["To"] = cfg["email"]["sender"], ", ".join(cfg["email"]["to"])
    link = f"{cfg['app_url'].rstrip('/')}/ecg/{n['recording_id']}" if cfg["app_url"] else "open Cardiotic AI"
    m.set_content(
        f"{site}\n\nA {n['level']} ECG is waiting to be read.\n\nRecording: {n['recording_id']}\nLocation: {n['location'] or '-'}\n"
        f"Reason (AI triage): {n['reason']}\nArrived: {n['at']} UTC\n\n{link}\n\n"
        "The triage is a reading-order aid, not a diagnosis. Follow the hospital's critical-result procedure.\n"
        "This message deliberately carries no patient name or number.\n")
    return m


def send_email(cfg: dict, msg: EmailMessage, timeout: float = 15.0) -> None:
    e = cfg["email"]
    if e["security"] == "ssl":
        s = smtplib.SMTP_SSL(e["host"], e["port"], timeout=timeout, context=ssl.create_default_context())
    else:
        s = smtplib.SMTP(e["host"], e["port"], timeout=timeout)
    with s:
        if e["security"] == "starttls":
            s.starttls(context=ssl.create_default_context())
        if e["username"]:
            s.login(e["username"], e["password"])
        s.send_message(msg)


class Mailer(threading.Thread):
    """Sends pending notification e-mails; retries with growing waits (1, 2, 4… minutes), at most MAX_ATTEMPTS."""

    def __init__(self, store, interval: float = 5.0, sender=send_email):
        super().__init__(daemon=True, name="notify-mailer")
        self.store, self.interval, self.sender = store, interval, sender
        self._stop_evt = threading.Event()
        self._next: dict[int, float] = {}

    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.wait(self.interval):
            try:
                self.run_once()
            except Exception:
                log.exception("notification mailer failed")

    def run_once(self) -> int:
        db = self.store.db
        cfg = settings(db)
        rows = db.conn().execute("SELECT * FROM notifications WHERE email_status='pending' ORDER BY id LIMIT 20").fetchall()
        sent = 0
        for r in rows:
            if not cfg["email"]["enabled"]:
                with db.tx() as c:
                    c.execute("UPDATE notifications SET email_status='off' WHERE id=?", (r["id"],))
                continue
            if self._next.get(r["id"], 0) > time.time():
                continue
            try:
                self.sender(cfg, compose(cfg, dict(r), self.store.site()["siteName"]))
            except Exception as e:  # noqa: BLE001 - any mail failure is recorded and retried
                attempts = r["email_attempts"] + 1
                status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
                self._next[r["id"]] = time.time() + 60 * 2 ** (attempts - 1)
                with db.tx() as c:
                    c.execute("UPDATE notifications SET email_attempts=?, email_error=?, email_status=? WHERE id=?", (attempts, str(e)[:300], status, r["id"]))
                    if status == "failed":
                        db.audit("Cardiotic AI", "Notification e-mail failed", f"{r['recording_id']}: {str(e)[:100]}", c)
                continue
            with db.tx() as c:
                c.execute("UPDATE notifications SET email_status='sent', email_attempts=email_attempts+1, email_error=NULL WHERE id=?", (r["id"],))
                db.audit("Cardiotic AI", "Notification e-mail sent", r["recording_id"], c)
            self._next.pop(r["id"], None)
            sent += 1
        return sent
