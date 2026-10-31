"""Inbound HL7 v2 from the hospital system over MLLP: patients (ADT) and ECG orders (ORM).

ADT A01/A04/A05/A08/A28/A31  create or update the patient (the HIS is the authority for name, sex, birth date)
ADT A40                      merge: recordings of the old MRN (MRG-1) move to the surviving MRN (PID-3)
ORM O01 / OMG O19            an ECG order: the next ECG of that patient (within 24 h) gets the ordering
                             doctor and location from the order, if the recording does not carry them

Every message is acknowledged (MSA AA, or AE with the reason); every change is audit-logged.
"""

from __future__ import annotations

import json
import logging
import socketserver
import threading
from datetime import datetime, timedelta, timezone

from .db import now

log = logging.getLogger("cardiotic_server.hl7in")
START, END = b"\x0b", b"\x1c\x0d"
UPDATE_EVENTS = {"A01", "A04", "A05", "A08", "A28", "A31"}


def _unesc(s: str, enc: str = "^~\\&") -> str:
    comp, rep, esc, sub = enc[0], enc[1], enc[2], enc[3]
    out, i = [], 0
    while i < len(s):
        if s[i] == esc:
            j = s.find(esc, i + 1)
            if j > i:
                code = s[i + 1:j]
                out.append({"F": "|", "S": comp, "R": rep, "E": esc, "T": sub, ".br": "\n"}.get(code, ""))
                i = j + 1
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


class Message:
    def __init__(self, text: str):
        lines = [l for l in text.replace("\n", "\r").split("\r") if l.strip()]
        if not lines or not lines[0].startswith("MSH"):
            raise ValueError("not an HL7 v2 message (no MSH segment)")
        self.field_sep = lines[0][3]
        self.enc = lines[0][4:8]
        self.segments: dict[str, list[list[str]]] = {}
        for line in lines:
            parts = line.split(self.field_sep)
            if parts[0] == "MSH":
                parts = ["MSH", self.field_sep] + parts[1:]  # MSH-1 is the separator itself
            self.segments.setdefault(parts[0], []).append(parts)

    def get(self, seg: str, field: int, comp: int = 1, rep: int = 0, idx: int = 0) -> str:
        try:
            v = self.segments[seg][idx][field].split(self.enc[1])[rep].split(self.enc[0])[comp - 1]
        except (KeyError, IndexError):
            return ""
        return _unesc(v, self.enc)

    def mrn(self, seg: str = "PID", field: int = 3) -> str:
        reps = self.segments.get(seg, [[]])[0]
        if len(reps) <= field:
            return ""
        values = reps[field].split(self.enc[1])
        for r in values:  # the repetition typed MR, else the first
            c = r.split(self.enc[0])
            if len(c) > 4 and c[4] == "MR":
                return _unesc(c[0], self.enc)
        return _unesc(values[0].split(self.enc[0])[0], self.enc)

    @property
    def type(self) -> tuple[str, str]:
        return self.get("MSH", 9, 1), self.get("MSH", 9, 2)


def ack(msg: Message | None, code: str, text: str = "") -> bytes:
    ctrl = msg.get("MSH", 10) if msg else ""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    body = f"MSH|^~\\&|CARDIOTIC||{msg.get('MSH', 3) if msg else ''}|{msg.get('MSH', 4) if msg else ''}|{ts}||ACK^{msg.type[1] if msg else ''}^ACK|A{ctrl}|P|2.5.1\rMSA|{code}|{ctrl}|{text[:80].replace('|', '/')}\r"
    return START + body.encode("latin-1", "replace") + END


def _date(v: str) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) >= 8 and v[:8].isdigit() else None


def handle(store, text: str) -> tuple[Message | None, str, str]:
    """Apply one message. Returns (message, ack code, text)."""
    try:
        msg = Message(text)
    except ValueError as e:
        return None, "AR", str(e)
    kind, event = msg.type
    actor = f"HIS ({msg.get('MSH', 3) or 'HL7'})"
    if kind == "ADT" and event in UPDATE_EVENTS:
        mrn = msg.mrn()
        if not mrn:
            return msg, "AE", "PID-3 (patient identifier) is empty"
        family, given = msg.get("PID", 5, 1), msg.get("PID", 5, 2)
        name = " ".join(x for x in (given, family) if x) or "Unidentified patient"
        sex = msg.get("PID", 8)[:1].upper()
        sex = sex if sex in ("M", "F") else ""
        birth = _date(msg.get("PID", 7))
        with store.db.tx() as c:
            r = c.execute("SELECT id FROM patients WHERE mrn=?", (mrn,)).fetchone()
            if r:
                c.execute("UPDATE patients SET name=?, sex=?, birth_date=? WHERE id=?", (name, sex, birth, r["id"]))
                store.db.audit(actor, "Updated patient from HIS", f"{mrn} (ADT {event})", c)
            else:
                store.upsert_patient(c, mrn, name, sex, birth)
                store.db.audit(actor, "Registered patient from HIS", f"{mrn} (ADT {event})", c)
        return msg, "AA", ""
    if kind == "ADT" and event == "A40":
        keep, old = msg.mrn(), msg.mrn("MRG", 1)
        if not keep or not old:
            return msg, "AE", "A40 needs PID-3 and MRG-1"
        with store.db.tx() as c:
            src = c.execute("SELECT id FROM patients WHERE mrn=?", (old,)).fetchone()
            if src is None:
                return msg, "AA", "nothing to merge"
            dst = c.execute("SELECT id FROM patients WHERE mrn=?", (keep,)).fetchone()
            if dst is None:  # the old record simply gets the new number
                c.execute("UPDATE patients SET mrn=? WHERE id=?", (keep, src["id"]))
            else:
                for rec in c.execute("SELECT id, summary FROM recordings WHERE patient_id=?", (src["id"],)).fetchall():
                    s = json.loads(rec["summary"])
                    s["patient_id"] = dst["id"]
                    c.execute("UPDATE recordings SET patient_id=?, summary=? WHERE id=?", (dst["id"], json.dumps(s), rec["id"]))
                c.execute("DELETE FROM patients WHERE id=?", (src["id"],))
            store.db.audit(actor, "Merged patients from HIS", f"{old} -> {keep}", c)
        return msg, "AA", ""
    if (kind, event) in (("ORM", "O01"), ("OMG", "O19")):
        mrn = msg.mrn()
        if not mrn:
            return msg, "AE", "PID-3 (patient identifier) is empty"
        doctor = " ".join(x for x in (msg.get("ORC", 12, 6) or msg.get("OBR", 16, 6), msg.get("ORC", 12, 3) or msg.get("OBR", 16, 3), msg.get("ORC", 12, 2) or msg.get("OBR", 16, 2)) if x)
        location = msg.get("PV1", 3, 1) or msg.get("ORC", 13, 1)
        orders = store.db.get_setting("orders", [])
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        orders = [o for o in orders if o["at"] > cutoff]
        orders.append({"mrn": mrn, "doctor": doctor, "location": location, "order": msg.get("ORC", 2) or msg.get("OBR", 2), "at": now()})
        store.db.set_setting("orders", orders[-500:])
        store.db.audit(actor, "ECG order received", f"{mrn} {msg.get('ORC', 2)}")
        return msg, "AA", ""
    return msg, "AR", f"message type {kind}^{event} is not handled"


def order_for(store, mrn: str) -> dict | None:
    """The newest open order for this patient (used when an ECG arrives), removed once used."""
    orders = store.db.get_setting("orders", [])
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    match = [o for o in orders if o["mrn"] == mrn and o["at"] > cutoff]
    if not match:
        return None
    o = match[-1]
    store.db.set_setting("orders", [x for x in orders if x is not o])
    return o


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        buf = b""
        self.request.settimeout(60)
        while True:
            try:
                chunk = self.request.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while START in buf and END in buf:
                s = buf.index(START)
                e = buf.index(END, s)
                text = buf[s + 1:e].decode("latin-1", "replace")
                buf = buf[e + len(END):]
                try:
                    msg, code, info = handle(self.server.store, text)
                except Exception:
                    log.exception("HL7 message failed")
                    msg, code, info = None, "AE", "internal error"
                st = self.server.store.db.get_setting("feed_status", {})
                s_ = st.get("HIS (ADT/orders)", {"received": 0, "failed": 0})
                if code == "AA":
                    s_["received"] += 1
                    s_["last_received"] = now()
                else:
                    s_["failed"] += 1
                    s_["last_error"], s_["last_error_at"] = info, now()
                st["HIS (ADT/orders)"] = s_
                self.server.store.db.set_setting("feed_status", st)
                self.request.sendall(ack(msg, code, info))


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Listener:
    def __init__(self, store):
        self.store, self.server, self.config = store, None, None

    def apply(self, cfg: dict) -> None:
        if cfg == self.config and (self.server is not None) == bool(cfg.get("enabled")):
            return
        self.stop()
        self.config = dict(cfg)
        if cfg.get("enabled"):
            self.server = _Server((cfg.get("host", "0.0.0.0"), int(cfg.get("port", 2576))), _Handler)
            self.server.store = self.store
            threading.Thread(target=self.server.serve_forever, daemon=True, name="hl7-in").start()
            log.info("HL7 listener on port %s", cfg.get("port", 2576))

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
