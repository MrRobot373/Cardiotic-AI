"""Finding, exporting and erasing patient records.

search          paginated find by MRN, name or recording number (the catalog only carries the recent / open part
                of a very large archive; see Store.catalog)
export_patient  everything held about one patient as a ZIP: patient data, each recording's analysis summary, review
                history, the report PDF and HL7 (signed ones), for a data-subject access request. Administrator only; audited.
erase_patient   removes the patient and everything attached (recordings, reviews and their history, beat labels, queued
                HIS messages, notifications). Refused while any signed report is younger than the site's retention
                period (setting retentionYears, default 10) and while a message for the patient is still queued for the HIS.
                The audit log is append-only and hash-chained, so it keeps its earlier entries (they carry record numbers and
                MRNs, not names); the erasure itself is logged with the internal patient id only.
expired         recordings older than the retention period that may be erased (dry-run listing for the hospital to review)
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

from .db import now


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(store, q: str = "", kind: str = "", status: str = "", limit: int = 50, offset: int = 0) -> dict:
    limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
    where, args = [], []
    q = (q or "").strip()
    if q:
        where.append("(p.mrn LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\' OR r.id LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 3
    if kind in ("ecg12", "holter"):
        where.append("r.kind=?")
        args.append(kind)
    if status in ("new", "in_review", "signed", "repeat"):
        where.append("v.status=?")
        args.append(status)
    sql = " FROM recordings r JOIN patients p ON p.id=r.patient_id JOIN reviews v ON v.ecg_id=r.id" + (" WHERE " + " AND ".join(where) if where else "")
    c = store.db.conn()
    total = c.execute("SELECT COUNT(*)" + sql, args).fetchone()[0]
    rows = c.execute("SELECT r.id, r.kind, r.recorded_at, r.location, p.id AS patient_id, p.mrn, p.name, v.status, v.signed_by, v.signed_at" + sql + " ORDER BY r.recorded_at DESC, r.id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return {"total": total, "offset": offset, "limit": limit, "items": [dict(r) for r in rows]}


def _patient(c, pid: str):
    p = c.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if p is None:
        from .store import NotFound
        raise NotFound(pid)
    return p


def export_patient(store, admin: dict, pid: str) -> bytes:
    from . import export
    c = store.db.conn()
    p = _patient(c, pid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        recs = c.execute("SELECT * FROM recordings WHERE patient_id=? ORDER BY recorded_at", (pid,)).fetchall()
        z.writestr("patient.json", json.dumps({k: p[k] for k in p.keys()}, indent=2))
        index = []
        for r in recs:
            rid = r["id"]
            rv = c.execute("SELECT * FROM reviews WHERE ecg_id=?", (rid,)).fetchone()
            hist = store.history(rid)
            z.writestr(f"{rid}/summary.json", json.dumps(json.loads(r["summary"]), indent=2))
            z.writestr(f"{rid}/review.json", json.dumps(store._review(rv), indent=2))
            z.writestr(f"{rid}/review-history.json", json.dumps(hist, indent=2))
            signed = rv["status"] == "signed"
            z.writestr(f"{rid}/report{'' if signed else '-DRAFT'}.pdf", export.report_pdf(store, rid, allow_draft=True))
            index.append({"id": rid, "kind": r["kind"], "recorded_at": r["recorded_at"], "status": rv["status"]})
        z.writestr("index.json", json.dumps({"exported_at": now(), "patient_id": pid, "recordings": index}, indent=2))
    store.db.audit(admin["name"], "Exported patient data", f"{pid} ({len(recs)} recordings)")
    return buf.getvalue()


def retention_years(store) -> float:
    return float(store.site().get("retentionYears", 10))


def _blockers(store, c, pid: str) -> list[str]:
    out = []
    keep_until = datetime.now(timezone.utc) - timedelta(days=365.25 * retention_years(store))
    for r in c.execute("SELECT r.id, v.signed_at, v.status, r.created_at FROM recordings r JOIN reviews v ON v.ecg_id=r.id WHERE r.patient_id=?", (pid,)):
        when = r["signed_at"] or r["created_at"]
        try:
            d = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            d = datetime.now(timezone.utc)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if d > keep_until:
            out.append(f"{r['id']} is within the {retention_years(store):g}-year retention period")
        if c.execute("SELECT 1 FROM outbox WHERE ecg_id=? AND status!='sent'", (r["id"],)).fetchone():
            out.append(f"{r['id']} still has a message waiting for the HIS")
    return out


def erase_patient(store, admin: dict, pid: str, confirm_mrn: str) -> dict:
    from .store import Conflict
    with store.db.tx() as c:
        p = _patient(c, pid)
        if (confirm_mrn or "").strip() != p["mrn"]:
            raise ValueError("type the patient's MRN to confirm the erasure")
        blockers = _blockers(store, c, pid)
        if blockers:
            raise Conflict("cannot erase yet: " + "; ".join(blockers[:5]) + ("..." if len(blockers) > 5 else ""))
        ids = [r["id"] for r in c.execute("SELECT id FROM recordings WHERE patient_id=?", (pid,))]
        for rid in ids:
            for t, col in (("outbox", "ecg_id"), ("review_versions", "ecg_id"), ("reviews", "ecg_id"), ("beat_labels", "rec_id"), ("notifications", "recording_id")):
                c.execute(f"DELETE FROM {t} WHERE {col}=?", (rid,))
        c.execute("DELETE FROM recordings WHERE patient_id=?", (pid,))
        c.execute("DELETE FROM patients WHERE id=?", (pid,))
        store.db.audit(admin["name"], "Erased patient record", f"{pid}: {len(ids)} recordings", c)
    return {"erased": pid, "recordings": len(ids)}


def expired(store) -> list[dict]:
    """Recordings whose signed report is older than the retention period (dry run: nothing is deleted)."""
    c = store.db.conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365.25 * retention_years(store))).isoformat()
    rows = c.execute("SELECT r.id, r.patient_id, p.mrn, v.signed_at FROM recordings r JOIN reviews v ON v.ecg_id=r.id JOIN patients p ON p.id=r.patient_id "
                     "WHERE v.status='signed' AND v.signed_at < ? ORDER BY v.signed_at", (cutoff,)).fetchall()
    return [dict(r) for r in rows]
