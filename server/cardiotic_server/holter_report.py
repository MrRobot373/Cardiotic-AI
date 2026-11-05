"""Holter reports: content from the stored analysis, the cardiologist's beat relabels and note; PDF, HL7 ORU^R01
and FHIR R4 like the 12-lead report, so a signed Holter report reaches the HIS the same way.

Beat relabelling: a cardiologist can change the class the AI gave a beat (normal / supraventricular / ventricular /
fusion). Relabels are kept per beat (table beat_labels) and change the counts and burdens in the report; the audit
log records every change. A signed report cannot be relabelled until it is amended.

Codes: heart rate uses LOINC 8867-4. The study is coded 18754-2 (Holter ECG study) - to be confirmed against the hospital's
own order catalogue during integration; beat counts use local codes (system CARDIOTIC) because LOINC has no codes for them.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

CLASSES = ("N", "S", "V", "F")
CLASS_NAMES = {"N": "Normal", "S": "Supraventricular ectopic", "V": "Ventricular ectopic", "F": "Fusion"}
LOCAL_CODES = {"N": "BEATS-N", "S": "BEATS-S", "V": "BEATS-V", "F": "BEATS-F"}


def relabels(c, rid: str) -> dict[float, str]:
    return {r["beat_time"]: r["label"] for r in c.execute("SELECT beat_time, label FROM beat_labels WHERE rec_id=?", (rid,))}


def counts(detail: dict, labels: dict[float, str]) -> dict:
    """Beat counts after the cardiologist's relabels: {"N","S","V","F","changed","total"}."""
    out = {k: 0 for k in CLASSES}
    changed = 0
    for b in detail["analysis"]["result"]["beats"]:
        t = round(float(b["time_s"]), 3)
        lab = labels.get(t, b["class"])
        out[lab if lab in out else "N"] += 1
        changed += lab != b["class"]
    out["total"] = sum(out[k] for k in CLASSES)
    out["changed"] = changed
    return out


def content(store, rid: str, c=None, allow_draft: bool = False) -> dict:
    from .export import _cap, _unz
    c = c or store.db.conn()
    rec = c.execute("SELECT * FROM recordings WHERE id=? AND kind='holter'", (rid,)).fetchone()
    if rec is None:
        raise KeyError(rid)
    rv = store._review(c.execute("SELECT * FROM reviews WHERE ecg_id=?", (rid,)).fetchone())
    if rv["status"] != "signed" and not allow_draft:
        raise ValueError("only signed reports are exported")
    summary, detail = json.loads(rec["summary"]), _unz(rec["detail"])
    pat = c.execute("SELECT * FROM patients WHERE id=?", (rec["patient_id"],)).fetchone()
    cnt = counts(detail, relabels(c, rid))
    m = detail["analysis"]["result"]["measurements"]
    eng = detail["analysis"]["engine"]
    total = max(cnt["total"], 1)
    hours = summary["duration_s"] / 3600
    return {"kind": "holter", "id": rid, "device": summary.get("device", ""), "patient": {"id": pat["id"], "mrn": pat["mrn"], "name": pat["name"], "sex": pat["sex"], "birth_date": pat["birth_date"]},
            "recorded_at": summary["recorded_at"], "ordered_by": summary["ordered_by"], "location": rec["location"] or "", "duration_s": summary["duration_s"], "lead": summary["lead"],
            "heart_rate_bpm": round(m["heart_rate_bpm"], 1), "rr_min_s": round(m["rr_min_s"], 2), "rr_max_s": round(m["rr_max_s"], 2), "usable_fraction": round(m["usable_fraction"], 2),
            "counts": cnt, "v_burden_pct": round(100 * cnt["V"] / total, 2), "s_burden_pct": round(100 * cnt["S"] / total, 2),
            "v_per_hour": round(cnt["V"] / hours, 1) if hours else None, "s_per_hour": round(cnt["S"] / hours, 1) if hours else None,
            "findings": [_cap(f) for f in summary["findings"]], "note": rv["note"], "signed_by": rv["signedBy"], "signed_at": rv["signedAt"],
            "software": f"{eng['engine']} {eng['version']} (models {eng['models_version']})", "site": store.site()["siteName"]}


def text(rep: dict) -> str:
    c = rep["counts"]
    lines = [f"Holter report - {rep['site']}", f"Patient: {rep['patient']['name']} (MRN {rep['patient']['mrn']})",
             f"Recorded: {rep['recorded_at']}, {rep['duration_s'] / 3600:.1f} h, lead {rep['lead']}",
             f"Mean rate {rep['heart_rate_bpm']:g} bpm; shortest RR {rep['rr_min_s']:g} s, longest RR {rep['rr_max_s']:g} s.",
             f"Beats {c['total']}: normal {c['N']}, supraventricular {c['S']} ({rep['s_burden_pct']:g}%), ventricular {c['V']} ({rep['v_burden_pct']:g}%), fusion {c['F']}."
             + (f" {c['changed']} beats relabelled by the cardiologist." if c["changed"] else ""), "Findings:"]
    lines += [f"  {i + 1}. {f}" for i, f in enumerate(rep["findings"])] or ["  none stated"]
    if rep["note"]:
        lines.append(f"Comment: {rep['note']}")
    lines += [f"Signed by {rep['signed_by']} on {rep['signed_at']}.", f"Pre-read by {rep['software']}; interpretation confirmed by the signing physician."]
    return "\n".join(lines)


def hl7(rep: dict, sending_app="CARDIOTIC", sending_facility="", receiving_app="HIS", receiving_facility="", pdf_bytes: bytes | None = None) -> str:
    from .export import _esc, _ts
    p = rep["patient"]
    family, given = (p["name"].rpartition(" ")[2], p["name"].rpartition(" ")[0]) if " " in p["name"] else (p["name"], "")
    seg = [f"MSH|^~\\&|{_esc(sending_app)}|{_esc(sending_facility)}|{_esc(receiving_app)}|{_esc(receiving_facility)}|{datetime.now(timezone.utc):%Y%m%d%H%M%S}||ORU^R01^ORU_R01|{uuid.uuid4().hex[:20].upper()}|P|2.5.1|||AL|NE",
           f"PID|1||{_esc(p['mrn'])}^^^{_esc(sending_facility)}^MR||{_esc(family)}^{_esc(given)}||{(p['birth_date'] or '').replace('-', '')}|{_esc(p['sex'])}",
           f"OBR|1||{_esc(rep['id'])}^{_esc(sending_app)}|18754-2^Holter ECG study^LN|||{_ts(rep['recorded_at'])}|||||||||{_esc(rep['ordered_by'])}||||||{_ts(rep['signed_at'])}|||F"]
    n = 1
    seg.append(f"OBX|{n}|NM|8867-4^Mean heart rate^LN||{rep['heart_rate_bpm']:g}|/min^/min^UCUM|||||F")
    for k in CLASSES:
        n += 1
        seg.append(f"OBX|{n}|NM|{LOCAL_CODES[k]}^{_esc(CLASS_NAMES[k])} beats^CARDIOTIC||{rep['counts'][k]}|{{beats}}^beats^UCUM|||||F")
    for f in rep["findings"]:
        n += 1
        seg.append(f"OBX|{n}|TX|HOLTER-FINDING^Holter finding^CARDIOTIC||{_esc(f)}||||||F")
    n += 1
    seg.append(f"OBX|{n}|FT|HOLTER-REPORT^Holter report text^CARDIOTIC||{_esc(text(rep))}||||||F|||{_ts(rep['signed_at'])}||{_esc(rep['signed_by'])}")
    if pdf_bytes:
        n += 1
        seg.append(f"OBX|{n}|ED|HOLTER-PDF^Holter report PDF^CARDIOTIC||^AP^PDF^Base64^{base64.b64encode(pdf_bytes).decode()}||||||F")
    return "\r".join(seg) + "\r"


def fhir(rep: dict, pdf_bytes: bytes | None = None) -> dict:
    p = rep["patient"]
    pid, rid, hr = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    patient = {"resourceType": "Patient", "identifier": [{"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]}, "value": p["mrn"]}], "name": [{"text": p["name"]}]}
    if p["sex"] in ("M", "F"):
        patient["gender"] = "male" if p["sex"] == "M" else "female"
    if p["birth_date"]:
        patient["birthDate"] = p["birth_date"]
    obs = lambda oid, code, text_, qty: {"fullUrl": f"urn:uuid:{oid}", "request": {"method": "POST", "url": "Observation"}, "resource": {  # noqa: E731
        "resourceType": "Observation", "status": "final", "code": {"coding": [code], "text": text_}, "subject": {"reference": f"urn:uuid:{pid}"}, "effectiveDateTime": rep["recorded_at"], "valueQuantity": qty}}
    entries = [{"fullUrl": f"urn:uuid:{pid}", "resource": patient, "request": {"method": "POST", "url": "Patient", "ifNoneExist": f"identifier={p['mrn']}"}},
               obs(hr, {"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}, "Mean heart rate", {"value": rep["heart_rate_bpm"], "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"})]
    refs = [{"reference": f"urn:uuid:{hr}"}]
    for k in CLASSES:
        oid = str(uuid.uuid4())
        refs.append({"reference": f"urn:uuid:{oid}"})
        entries.append(obs(oid, {"system": "urn:cardiotic", "code": LOCAL_CODES[k], "display": f"{CLASS_NAMES[k]} beats"}, f"{CLASS_NAMES[k]} beats", {"value": rep["counts"][k], "unit": "beats", "system": "http://unitsofmeasure.org", "code": "{beats}"}))
    report = {"resourceType": "DiagnosticReport", "status": "final",
              "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "EC", "display": "Electrocardiac (e.g. EKG, EEG, Echo, Holter)"}]}],
              "code": {"coding": [{"system": "http://loinc.org", "code": "18754-2", "display": "Holter ECG study"}], "text": "Holter ECG"},
              "subject": {"reference": f"urn:uuid:{pid}"}, "effectiveDateTime": rep["recorded_at"], "issued": rep["signed_at"], "performer": [{"display": rep["signed_by"]}],
              "resultsInterpreter": [{"display": rep["signed_by"]}], "identifier": [{"system": "urn:cardiotic:report", "value": rep["id"]}], "result": refs, "conclusion": text(rep),
              **({"presentedForm": [{"contentType": "application/pdf", "title": f"Holter report {rep['id']}", "data": base64.b64encode(pdf_bytes).decode()}]} if pdf_bytes else {})}
    entries.append({"fullUrl": f"urn:uuid:{rid}", "resource": report, "request": {"method": "POST", "url": "DiagnosticReport"}})
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def pdf_bytes(rep: dict, draft: bool) -> bytes:
    from . import pdf
    from .pdf import H, MM, W, Page
    pg = Page()
    left, top = 12 * MM, H - 12 * MM
    pg.text(left, top - 4, rep["site"], 14, bold=True)
    pg.text(left, top - 16, "Holter ECG report \xb7 Cardiotic AI assisted", 8, gray=0.4)
    pg.text(W - 92 * MM, top - 4, "DRAFT - NOT SIGNED" if draft else "FINAL REPORT", 11, bold=True, gray=0.6 if draft else 0.0)
    pg.text(W - 92 * MM, top - 16, f"Report {rep['id']}", 8, gray=0.4)
    pg.line(left, top - 21, W - left, top - 21, 0.5, (0.8, 0.8, 0.8))
    p = rep["patient"]
    sex = {"M": "Male", "F": "Female"}.get(p["sex"], "")
    cols = [("Patient", p["name"], f"MRN {p['mrn']}" + (f" \xb7 born {p['birth_date']}" if p["birth_date"] else "") + (f" \xb7 {sex}" if sex else "")),
            ("Recorded", rep["recorded_at"].replace("T", " "), f"{rep['duration_s'] / 3600:.1f} h \xb7 lead {rep['lead']} \xb7 {rep.get('device') or ''}".rstrip(" \xb7")),
            ("Ordered by", rep.get("ordered_by") or "-", f"{round(100 * rep['usable_fraction'])}% of the signal usable")]
    for i, (k, v, sub) in enumerate(cols):
        x = left + i * 92 * MM
        pg.text(x, top - 30, k, 7, gray=0.45)
        pg.text(x, top - 40, v, 10, bold=True)
        pg.text(x, top - 50, sub, 7.5, gray=0.3)
    c = rep["counts"]
    boxes = [("Mean rate", f"{rep['heart_rate_bpm']:g} bpm"), ("Shortest RR", f"{rep['rr_min_s']:g} s"), ("Longest RR", f"{rep['rr_max_s']:g} s"),
             ("Beats analysed", f"{c['total']:,}"), ("Ventricular", f"{c['V']:,} ({rep['v_burden_pct']:g}%)"), ("Supraventricular", f"{c['S']:,} ({rep['s_burden_pct']:g}%)")]
    bw = (W - 2 * left) / len(boxes)
    for i, (k, v) in enumerate(boxes):
        x = left + i * bw
        pg.rect(x + 1, top - 78, bw - 2, 20)
        pg.text(x + 5, top - 66, k, 6.5, gray=0.45)
        pg.text(x + 5, top - 75, v, 9.5, bold=True)
    y = top - 96
    pg.text(left, y, "BEAT CLASSES", 7, bold=True, gray=0.45)
    y -= 12
    total = max(c["total"], 1)
    for k in CLASSES:
        pg.text(left + 2, y, f"{CLASS_NAMES[k]}", 9)
        pg.text(left + 60 * MM, y, f"{c[k]:,}", 9, bold=True)
        pg.rect(left + 85 * MM, y - 1, 90 * MM, 7, stroke=(0.85, 0.85, 0.85))
        pg.ops.append(f"0.35 0.45 0.65 rg {left + 85 * MM:.2f} {y - 1:.2f} {90 * MM * c[k] / total:.2f} 7 re f")
        y -= 12
    if c["changed"]:
        pg.text(left + 2, y, f"{c['changed']} beat(s) relabelled by the cardiologist; the counts above include the changes.", 7.5, gray=0.35)
        y -= 12
    y -= 6
    pg.text(left, y, "FINDINGS", 7, bold=True, gray=0.45)
    y -= 12
    for i, f in enumerate(rep["findings"][:9] or ["none stated"]):
        pg.text(left + 2, y, f"{i + 1}. {f}"[:150], 9, bold=True)
        y -= 11
    if rep.get("note"):
        pg.text(left, y - 4, "COMMENT", 7, bold=True, gray=0.45)
        pg.text(left + 2, y - 15, rep["note"][:170], 8.5)
    sx = W - left - 80 * MM
    pg.rect(sx, 24 * MM, 80 * MM, 22 * MM)
    pg.text(sx + 6, 24 * MM + 52, "Awaiting signature" if draft else "Electronically signed by", 7, gray=0.45)
    pg.text(sx + 6, 24 * MM + 38, "-" if draft else rep["signed_by"], 10, bold=True)
    pg.text(sx + 6, 24 * MM + 26, "Not valid until signed by a cardiologist" if draft else str(rep["signed_at"]).replace("T", " ")[:19], 7.5)
    pg.line(left, 14 * MM, W - left, 14 * MM, 0.4, (0.8, 0.8, 0.8))
    pg.text(left, 10 * MM, f"Pre-read by {rep['software']}; interpretation confirmed by the signing physician.", 6.5, gray=0.45)
    if draft:
        pg.ops.append("q 0.92 g BT /F2 90 Tf 0.866 0.5 -0.5 0.866 260 150 Tm (DRAFT) Tj ET Q")
    return pdf.build([pg], f"Holter report {rep['id']}")
