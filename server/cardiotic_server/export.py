"""Signed reports out to the hospital information system: HL7 v2.5.1 ORU^R01 (over MLLP) and FHIR R4.

Nothing is sent before a cardiologist signs. Sending never blocks signing: a signed report is queued in the
outbox and delivered by a background worker with retries; every attempt is visible in the outbox.

Code systems: measurements use LOINC (heart rate 8867-4, PR 8625-6, QRS 8633-0, QT 8634-8, QTc 8636-3,
QRS axis 8632-2). Interpretation statements use the SCP-ECG statement code as a local code (system
"SCP-ECG"). Each hospital maps these to its own dictionary during integration; the report is sent as text,
not as a PDF (the printable report in the web app is the PDF source).
"""

from __future__ import annotations

import base64
import json
import math
import socket
import threading
import time
import uuid
from datetime import datetime, timezone

from .db import now

MLLP_START, MLLP_END = b"\x0b", b"\x1c\x0d"
MEASUREMENTS = [  # key, LOINC, name, unit
    ("heart_rate_bpm", "8867-4", "Heart rate", "/min"), ("pr_ms", "8625-6", "PR interval", "ms"), ("qrs_ms", "8633-0", "QRS duration", "ms"),
    ("qt_ms", "8634-8", "QT interval", "ms"), ("qtc_bazett_ms", "8636-3", "QTc (Bazett)", "ms"), ("qrs_axis_deg", "8632-2", "QRS axis", "deg")]
UCUM = {"/min": "/min", "ms": "ms", "deg": "deg"}


# ------------------------------------------------------------------ what the report says
def report_content(store, rid: str, c=None, allow_draft: bool = False) -> dict:
    """Everything a signed report needs, from the stored analysis and the cardiologist's review.
    `c`: the connection to read through (the signing transaction passes its own, so it sees the signature)."""
    c = c or store.db.conn()
    rec = c.execute("SELECT * FROM recordings WHERE id=? AND kind='ecg12'", (rid,)).fetchone()
    if rec is None:
        raise KeyError(rid)
    row = c.execute("SELECT * FROM reviews WHERE ecg_id=?", (rid,)).fetchone()
    rv = store._review(row)
    if rv["status"] != "signed" and not allow_draft:
        raise ValueError("only signed reports are exported")
    summary, detail = json.loads(rec["summary"]), _unz(rec["detail"])
    pat = c.execute("SELECT * FROM patients WHERE id=?", (rec["patient_id"],)).fetchone()
    m = dict(detail["analysis"]["result"]["measurements"])
    for k, v in rv["edits"].items():
        if not k.startswith("cal."):
            m[k] = v
    if "qt_ms" in rv["edits"] and m.get("qt_ms") and m.get("rr_ms"):
        m["qtc_bazett_ms"] = m["qt_ms"] / math.sqrt(m["rr_ms"] / 1000)
    names = store.names()
    ai = [s["statement"] for s in detail["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    final = [s for s in ai if rv["decisions"].get(s) != "rejected"] + [s for s in rv["added"] if s not in ai]
    eng = detail["analysis"]["engine"]
    return {"device": summary.get("device", ""), "id": rid, "patient": {"id": pat["id"], "mrn": pat["mrn"], "name": pat["name"], "sex": pat["sex"], "birth_date": pat["birth_date"]},
            "recorded_at": summary["recorded_at"], "ordered_by": summary["ordered_by"], "location": summary["location"],
            "measurements": {k: (round(m[k], 1) if m.get(k) is not None else None) for k, *_ in MEASUREMENTS}, "edited": sorted(k for k in rv["edits"] if not k.startswith("cal.")),
            "statements": [{"code": s, "text": _cap(names.get(s, s))} for s in final], "note": rv["note"], "signed_by": rv["signedBy"], "signed_at": rv["signedAt"],
            "software": f"{eng['engine']} {eng['version']} (models {eng['models_version']})", "site": store.site()["siteName"]}


def _cap(t: str) -> str:
    return t[:1].upper() + t[1:]


def _unz(b):
    import zlib
    return json.loads(zlib.decompress(b))


def report_text(rep: dict) -> str:
    lines = [f"12-lead ECG report — {rep['site']}", f"Patient: {rep['patient']['name']} (MRN {rep['patient']['mrn']})", f"Recorded: {rep['recorded_at']}"]
    lines += ["Interpretation:"] + [f"  {i + 1}. {s['text']}" for i, s in enumerate(rep["statements"])] if rep["statements"] else ["Interpretation: no abnormality stated."]
    if rep["note"]:
        lines += [f"Comment: {rep['note']}"]
    lines += [f"Signed by {rep['signed_by']} on {rep['signed_at']}.", f"Pre-read by {rep['software']}; interpretation confirmed by the signing physician."]
    return "\n".join(lines)


# ------------------------------------------------------------------ HL7 v2.5.1 ORU^R01
def _esc(s) -> str:
    s = "" if s is None else str(s)
    return (s.replace("\\", "\\E\\").replace("|", "\\F\\").replace("^", "\\S\\").replace("&", "\\T\\").replace("~", "\\R\\").replace("\r\n", "\\.br\\").replace("\n", "\\.br\\"))


def _ts(iso: str | None) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return d.strftime("%Y%m%d%H%M%S")


def report_pdf(store, rid: str, c=None, allow_draft: bool = False) -> bytes:
    from . import pdf
    c = c or store.db.conn()
    rep = report_content(store, rid, c, allow_draft)
    detail = _unz(c.execute("SELECT detail FROM recordings WHERE id=?", (rid,)).fetchone()["detail"])
    return pdf.ecg_report(rep, detail["leads"], detail["fs"], draft=rep["signed_by"] is None)


def hl7_oru(rep: dict, sending_app: str = "CARDIOTIC", sending_facility: str = "", receiving_app: str = "HIS", receiving_facility: str = "", message_id: str | None = None,
            pdf_bytes: bytes | None = None) -> str:
    p = rep["patient"]
    family, _, given = (p["name"].rpartition(" ")[2], "", p["name"].rpartition(" ")[0]) if " " in p["name"] else (p["name"], "", "")
    mid = message_id or uuid.uuid4().hex[:20].upper()
    seg = [f"MSH|^~\\&|{_esc(sending_app)}|{_esc(sending_facility)}|{_esc(receiving_app)}|{_esc(receiving_facility)}|{datetime.now(timezone.utc):%Y%m%d%H%M%S}||ORU^R01^ORU_R01|{mid}|P|2.5.1|||AL|NE",
           f"PID|1||{_esc(p['mrn'])}^^^{_esc(sending_facility)}^MR||{_esc(family)}^{_esc(given)}||{(p['birth_date'] or '').replace('-', '')}|{_esc(p['sex'])}",
           f"OBR|1||{_esc(rep['id'])}^{_esc(sending_app)}|11524-6^EKG study^LN|||{_ts(rep['recorded_at'])}|||||||||{_esc(rep['ordered_by'])}||||||{_ts(rep['signed_at'])}|||F"]
    n = 0
    for key, loinc, name, unit in MEASUREMENTS:
        v = rep["measurements"].get(key)
        if v is None:
            continue
        n += 1
        seg.append(f"OBX|{n}|NM|{loinc}^{_esc(name)}^LN||{v:g}|{UCUM[unit]}^{_esc(unit)}^UCUM|||||F")
    for s in rep["statements"]:
        n += 1
        seg.append(f"OBX|{n}|CWE|ECG-STMT^ECG statement^L||{_esc(s['code'])}^{_esc(s['text'])}^SCP-ECG||||||F")
    n += 1
    seg.append(f"OBX|{n}|FT|ECG-REPORT^ECG report text^L||{_esc(report_text(rep))}||||||F|||{_ts(rep['signed_at'])}||{_esc(rep['signed_by'])}")
    if pdf_bytes:  # the signed report document itself, as HL7 encapsulated data
        n += 1
        seg.append(f"OBX|{n}|ED|ECG-PDF^ECG report PDF^L||^AP^PDF^Base64^{base64.b64encode(pdf_bytes).decode()}||||||F")
    return "\r".join(seg) + "\r"


def parse_ack(raw: bytes) -> tuple[bool, str]:
    """(accepted, text) from an HL7 ACK: MSA-1 AA/CA accepted, AE/AR/CE/CR rejected."""
    msg = raw.strip(MLLP_START + MLLP_END + b"\r\n").decode("latin-1", "replace")
    for line in msg.replace("\n", "\r").split("\r"):
        if line.startswith("MSA|"):
            f = line.split("|")
            code = f[1] if len(f) > 1 else ""
            return code in ("AA", "CA"), f"{code} {f[3] if len(f) > 3 else ''}".strip()
    return False, "no MSA segment in the reply"


def send_mllp(host: str, port: int, message: str, timeout: float = 10.0) -> tuple[bool, str]:
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(MLLP_START + message.encode("latin-1", "replace") + MLLP_END)
        buf = b""
        while not buf.endswith(MLLP_END):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    return parse_ack(buf)


# ------------------------------------------------------------------ FHIR R4
def fhir_bundle(rep: dict, pdf_bytes: bytes | None = None) -> dict:
    p = rep["patient"]
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    period = rep["recorded_at"]
    entries, obs_refs = [], []
    patient = {"resourceType": "Patient", "identifier": [{"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]}, "value": p["mrn"]}],
               "name": [{"text": p["name"]}]}
    if p["sex"] in ("M", "F"):
        patient["gender"] = "male" if p["sex"] == "M" else "female"
    if p["birth_date"]:
        patient["birthDate"] = p["birth_date"]
    entries.append({"fullUrl": f"urn:uuid:{pid}", "resource": patient,
                    "request": {"method": "POST", "url": "Patient", "ifNoneExist": f"identifier={p['mrn']}"}})
    for key, loinc, name, unit in MEASUREMENTS:
        v = rep["measurements"].get(key)
        if v is None:
            continue
        oid = str(uuid.uuid4())
        obs_refs.append({"reference": f"urn:uuid:{oid}", "display": name})
        entries.append({"fullUrl": f"urn:uuid:{oid}", "request": {"method": "POST", "url": "Observation"}, "resource": {
            "resourceType": "Observation", "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "procedure"}]}],
            "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": name}], "text": name},
            "subject": {"reference": f"urn:uuid:{pid}"}, "effectiveDateTime": period,
            "valueQuantity": {"value": v, "unit": unit, "system": "http://unitsofmeasure.org", "code": UCUM[unit]}}})
    report = {"resourceType": "DiagnosticReport", "status": "final",
              "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "EC", "display": "Electrocardiac (e.g. EKG, EEG, Echo, Holter)"}]}],
              "code": {"coding": [{"system": "http://loinc.org", "code": "11524-6", "display": "EKG study"}], "text": "12-lead ECG"},
              "subject": {"reference": f"urn:uuid:{pid}"}, "effectiveDateTime": period, "issued": rep["signed_at"],
              "performer": [{"display": rep["signed_by"]}], "resultsInterpreter": [{"display": rep["signed_by"]}],
              "identifier": [{"system": "urn:cardiotic:report", "value": rep["id"]}],
              "result": obs_refs, "conclusion": report_text(rep),
              **({"presentedForm": [{"contentType": "application/pdf", "title": f"ECG report {rep['id']}", "data": base64.b64encode(pdf_bytes).decode()}]} if pdf_bytes else {}),
              "conclusionCode": [{"coding": [{"system": "urn:cardiotic:scp-ecg", "code": s["code"], "display": s["text"]}], "text": s["text"]} for s in rep["statements"]]}
    entries.append({"fullUrl": f"urn:uuid:{rid}", "resource": report, "request": {"method": "POST", "url": "DiagnosticReport"}})
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


# ------------------------------------------------------------------ outbox
def enqueue(store, c, rid: str) -> None:
    """Called inside the signing transaction: the message is built now (what was signed is what is sent)."""
    rep = report_content(store, rid, c)
    his = store.db.get_setting("his", {})
    msg = hl7_oru(rep, sending_facility=rep["site"][:20], receiving_facility=his.get("facility", ""), receiving_app=his.get("application", "HIS"),
                  pdf_bytes=report_pdf(store, rid, c) if his.get("attach_pdf", True) else None)
    c.execute("INSERT INTO outbox(ecg_id, kind, payload, created_at) VALUES (?,?,?,?)", (rid, "hl7-oru", msg, now()))


class Worker(threading.Thread):
    """Delivers queued messages to the HIS over MLLP: retry with growing waits, never more than once per message at a time."""

    def __init__(self, store, interval: float = 5.0):
        super().__init__(daemon=True, name="his-outbox")
        self.store, self.interval, self._stop_evt = store, interval, threading.Event()

    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.wait(self.interval):
            try:
                self.deliver_due()
            except Exception:  # the worker must outlive one bad message
                import logging
                logging.getLogger("cardiotic_server").exception("outbox delivery failed")

    def deliver_due(self) -> int:
        his = self.store.db.get_setting("his", {})
        if not his.get("enabled") or not his.get("host"):
            return 0
        sent = 0
        for r in self.store.db.conn().execute("SELECT * FROM outbox WHERE status='pending' AND next_try<=? ORDER BY id LIMIT 20", (time.time(),)).fetchall():
            try:
                ok, text = send_mllp(his["host"], int(his.get("port", 2575)), r["payload"])
                err = None if ok else f"HIS rejected the message: {text}"
            except OSError as e:
                ok, err = False, f"cannot reach the HIS: {e}"
            with self.store.db.tx() as c:
                if ok:
                    c.execute("UPDATE outbox SET status='sent', sent_at=?, attempts=attempts+1, last_error=NULL WHERE id=?", (now(), r["id"]))
                    self.store.db.audit("system", "Report sent to HIS", f"{r['ecg_id']} (HL7 ORU^R01 acknowledged)", c)
                    sent += 1
                else:
                    tries = r["attempts"] + 1
                    c.execute("UPDATE outbox SET attempts=?, last_error=?, next_try=?, status=? WHERE id=?",
                              (tries, err, time.time() + min(3600, 30 * 2 ** tries), "failed" if tries >= 12 else "pending", r["id"]))
        return sent
