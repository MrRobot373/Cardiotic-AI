"""What the server keeps and the rules around it: patients, ECG and Holter recordings, reviews and sign-off,
settings. The JSON shapes match what the web app already shows (frontend/src/data/types.ts)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from cardiotic_engine.api import LEADS, Engine, InputError

from .db import Database, now

FS_VIEW = 250
CATALOG_FULL = int(os.environ.get("CARDIOTIC_CATALOG_FULL", "5000"))  # up to this many recordings the worklist loads everything
CATALOG_DAYS = int(os.environ.get("CARDIOTIC_CATALOG_DAYS", "90"))   # beyond it: open recordings plus signed ones this recent
DEFAULT_SITE = {"operatingPoint": "balanced", "thresholdOverrides": {}, "ratesFromMeasurements": False, "autoSendHis": True,
                "siteName": "Department of Cardiology", "showReference": False,
                "signReauth": True, "timeZone": "UTC", "retentionYears": 10, "afMode": "balanced"}
REVIEW_STATUSES = ("new", "in_review", "signed", "repeat")


class Conflict(Exception):
    """The request is valid but not allowed in the current state (409)."""


class Forbidden(Exception):
    """The signed-in user's role may not do this (403)."""


class NotFound(Exception):
    pass


def _b64(x: np.ndarray) -> str:
    return base64.b64encode(np.clip(np.round(x * 1000), -32767, 32767).astype("<i2").tobytes()).decode()


def _z(obj) -> bytes:
    return zlib.compress(json.dumps(obj, default=float).encode(), 6)


def _unz(b: bytes):
    return json.loads(zlib.decompress(b))


class Store:
    def __init__(self, db: Database, engine: Engine):
        self.db, self.engine = db, engine

    # ---------------------------------------------------------------- settings
    def site(self) -> dict:
        return {**DEFAULT_SITE, **self.db.get_setting("site", {})}

    def update_site(self, user: dict, patch: dict) -> dict:
        if user["role"] not in ("admin", "cardiologist"):
            raise Forbidden("only the cardiology lead or an administrator can change site settings")
        unknown = set(patch) - set(DEFAULT_SITE)
        if unknown:
            raise ValueError(f"unknown settings {sorted(unknown)}")
        if "operatingPoint" in patch and patch["operatingPoint"] not in ("sensitive", "balanced", "specific"):
            raise ValueError("operatingPoint must be sensitive, balanced or specific")
        if "siteName" in patch and not str(patch["siteName"]).strip():
            raise ValueError("siteName must not be empty")
        if "signReauth" in patch and user["role"] != "admin" and not patch["signReauth"]:
            raise Forbidden("only an administrator can turn off password confirmation at signing")
        if "afMode" in patch and str(patch["afMode"]) not in self.engine.af_modes():
            raise ValueError(f"afMode must be one of {sorted(self.engine.af_modes())}")
        if "retentionYears" in patch:
            if user["role"] != "admin":
                raise Forbidden("only an administrator can change the retention period")
            if not isinstance(patch["retentionYears"], (int, float)) or not 0 <= patch["retentionYears"] <= 100:
                raise ValueError("retentionYears must be a number of years between 0 and 100")
        if "timeZone" in patch:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(str(patch["timeZone"]))
            except Exception:
                raise ValueError(f"unknown time zone {patch['timeZone']!r} (use a name like Asia/Kolkata or America/New_York)") from None
        site = {**self.site(), **patch}
        if "afMode" in patch:
            self.engine.set_af_mode(site["afMode"])
        self.db.set_setting("site", site)
        self.db.audit(user["name"], "Changed site settings", ", ".join(sorted(patch)))
        return site

    # ---------------------------------------------------------------- patients
    def patient_row(self, r) -> dict:
        return {"id": r["id"], "name": r["name"], "mrn": r["mrn"], "sex": r["sex"], "age": _age(r["birth_date"]),
                "age_90_plus": (_age(r["birth_date"]) or 0) >= 90, "birth_date": r["birth_date"], "origin": ""}

    def upsert_patient(self, c, mrn: str, name: str = "", sex: str = "", birth_date: str | None = None) -> str:
        r = c.execute("SELECT id, name, sex, birth_date FROM patients WHERE mrn=?", (mrn,)).fetchone()
        if r:  # a known patient keeps the hospital's record; the file only fills what is empty
            if (not r["birth_date"] and birth_date) or (not r["sex"] and sex):
                c.execute("UPDATE patients SET birth_date=COALESCE(birth_date, ?), sex=CASE WHEN sex='' THEN ? ELSE sex END WHERE id=?", (birth_date, sex, r["id"]))
            return r["id"]
        pid = f"P{c.execute('SELECT COUNT(*) FROM patients').fetchone()[0] + 1:05d}"
        c.execute("INSERT INTO patients(id, mrn, name, sex, birth_date, created_at) VALUES (?,?,?,?,?,?)", (pid, mrn, name or "Unidentified patient", sex, birth_date, now()))
        return pid

    def create_patient(self, user: dict, mrn: str, name: str, sex: str = "", birth_date: str | None = None) -> dict:
        if user["role"] == "admin":
            raise Forbidden("administrators do not register patients; the HIS does")
        mrn, name = (mrn or "").strip(), (name or "").strip()
        if not mrn or not name:
            raise ValueError("MRN and name are required")
        if sex not in ("", "M", "F"):
            raise ValueError("sex must be M or F")
        if birth_date:
            date.fromisoformat(birth_date)
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM patients WHERE mrn=?", (mrn,)).fetchone():
                raise Conflict(f"a patient with MRN {mrn} already exists")
            pid = self.upsert_patient(c, mrn, name, sex, birth_date)
            self.db.audit(user["name"], "Created patient", mrn, c)
        return self.patient_row(self.db.conn().execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone())

    # ---------------------------------------------------------------- upload -> analyse -> store
    def add_file(self, user: dict, data: bytes, filename: str = "", fs: float | None = None, units: str | None = None, mrn: str | None = None,
                 location: str = "", ordered_by: str = "") -> dict:
        if user["role"] not in ("technician", "cardiologist"):
            raise Forbidden("only technicians and cardiologists can upload ECGs")
        parsed = self.engine.read_file(data, fs=fs, units=units)  # InputError (400) for anything it cannot read
        # the same ECG exported twice (new file envelope, same samples) is the same recording: identify it by its samples
        h = hashlib.sha256(f"{parsed.fs:g}".encode())
        for name, v in parsed.leads.items():
            h.update(name.encode() + np.round(v * 1000).astype("<i4").tobytes())
        digest = h.hexdigest()
        existing = self.db.conn().execute("SELECT id FROM recordings WHERE file_sha256=?", (digest,)).fetchone()
        if existing:
            raise Conflict(f"this ECG was already uploaded as {existing['id']}")
        out = self.engine.analyze_parsed(parsed)
        src = out["source_file"]
        patient = src.get("patient", {})
        mrn = (mrn or patient.get("id") or "").strip()
        if not mrn:
            mrn = f"UNMATCHED-{digest[:8].upper()}"
        if not location or not ordered_by:  # an ECG order from the HIS for this patient fills what the recording does not carry
            from .hl7in import order_for
            o = order_for(self, mrn)
            if o:
                location, ordered_by = location or o["location"], ordered_by or o["doctor"]
        if out["analysis"] == "ecg12":
            rec = self._store_ecg12(user, out, parsed, filename, digest, mrn, patient, location, ordered_by, src)
        else:
            rec = self._store_holter(user, out, parsed, filename, digest, mrn, patient, location, ordered_by, src)
        return rec

    def _new_id(self, c, prefix: str) -> str:
        n = c.execute("SELECT COUNT(*) FROM recordings WHERE kind=?", ("ecg12" if prefix == "E" else "holter",)).fetchone()[0] + 1
        return f"{prefix}{n:06d}"

    def _store_ecg12(self, user, out, parsed, filename, digest, mrn, patient, location, ordered_by, src) -> dict:
        from cardiotic_ml import dsp
        from cardiotic_ml.ecg12 import measure

        sig = np.stack([parsed.leads[l] if l in parsed.leads else _derive(parsed.leads, l) for l in LEADS]).astype(np.float32)[:, : int(10 * parsed.fs)]
        view = dsp.resample(dsp.bandpass(sig, parsed.fs, "diagnostic"), parsed.fs, FS_VIEW)
        mb = measure.median_beat(sig, parsed.fs) if parsed.layout == "recording" else None  # a printout has no simultaneous 10 s leads
        median = None
        if mb is not None:
            beat = dsp.resample(mb.beat, parsed.fs, FS_VIEW)
            median = {"fs": FS_VIEW, "r": int(round(mb.r * FS_VIEW / parsed.fs)), "n_beats": mb.n_used, "leads": {l: _b64(beat[i]) for i, l in enumerate(LEADS)},
                      "r_peaks_s": [round(float(p) / parsed.fs, 3) for p in mb.r_peaks], "in_median": [bool(u) for u in mb.used], "detection_lead": mb.detect_lead}
        with self.db.tx() as c:
            pid = self.upsert_patient(c, mrn, patient.get("name", ""), patient.get("sex", ""), patient.get("birth_date"))
            eid = self._new_id(c, "E")
            r = out["result"]
            when = src.get("recorded_at") or datetime.now().isoformat(timespec="minutes")
            detail = {"id": eid, "fs": FS_VIEW, "leads": {l: _b64(view[i]) for i, l in enumerate(LEADS)}, "median": median,
                      "analysis": {k: out[k] for k in ("engine", "input_notes", "processing_ms", "result")}}
            summary = {"layout": parsed.layout, "id": eid, "patient_id": pid, "recorded_at": when[:16], "location": location, "ordered_by": ordered_by, "device": src.get("device") or "",
                       "source": {"dataset": src["format"], "record": filename or digest[:12], "licence": "", "role": "uploaded file"},
                       "reference_statements": [],
                       "statements": [{k: s[k] for k in ("statement", "probability", "confidence")} for s in r["statements"]],
                       "measurements": {k: v for k, v in r["measurements"].items() if k.endswith(("_ms", "_bpm", "_deg")) or k == "ok"},
                       "unusable_leads": [l for l, q in r["lead_quality"].items() if q == "unusable"],
                       "noisy_leads": [l for l, q in r["lead_quality"].items() if q == "noisy"],
                       "notes": r["notes"] + out["input_notes"]}
            from .triage import triage
            summary["triage"] = triage(summary["statements"], summary["measurements"], STATEMENT_NAMES)
            c.execute("INSERT INTO recordings(id, kind, patient_id, recorded_at, location, ordered_by, device, summary, detail, file_sha256, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (eid, "ecg12", pid, summary["recorded_at"], location, ordered_by, summary["device"], json.dumps(summary, default=float), _z(detail), digest, user["name"], now()))
            c.execute("INSERT INTO reviews(ecg_id) VALUES (?)", (eid,))
            self.db.audit(user["name"], "Uploaded ECG", f"{eid} ({src['format']})", c)
            if not summary["unusable_leads"] or len(summary["unusable_leads"]) < 6:  # an unreadable tracing is not a result to alert on
                from . import notify
                notify.create(self, c, eid, summary["triage"], location)
        return summary

    def _store_holter(self, user, out, parsed, filename, digest, mrn, patient, location, ordered_by, src) -> dict:
        name, sig = next(iter(parsed.leads.items()))
        r = out["result"]
        with self.db.tx() as c:
            pid = self.upsert_patient(c, mrn, patient.get("name", ""), patient.get("sex", ""), patient.get("birth_date"))
            hid = self._new_id(c, "H")
            when = src.get("recorded_at") or datetime.now().isoformat(timespec="minutes")
            detail = {"id": hid, "fs": parsed.fs, "n_samples": len(sig), "analysis": {k: out[k] for k in ("engine", "input_notes", "processing_ms", "result")}, "reference_beats": []}
            summary = {"id": hid, "patient_id": pid, "recorded_at": when[:16], "duration_s": len(sig) / parsed.fs, "lead": name, "fs": parsed.fs,
                       "source": {"dataset": src["format"], "record": filename or digest[:12], "licence": "", "role": "uploaded file"},
                       "device": src.get("device") or "", "ordered_by": ordered_by, "findings": r["findings"], "measurements": r["measurements"]}
            c.execute("INSERT INTO recordings(id, kind, patient_id, recorded_at, location, ordered_by, device, summary, detail, signal, file_sha256, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (hid, "holter", pid, summary["recorded_at"], location, ordered_by, summary["device"], json.dumps(summary, default=float), _z(detail),
                       np.clip(np.round(sig * 1000), -32767, 32767).astype("<i2").tobytes(), digest, user["name"], now()))
            c.execute("INSERT INTO reviews(ecg_id) VALUES (?)", (hid,))
            self.db.audit(user["name"], "Uploaded Holter recording", f"{hid} ({src['format']})", c)
        return summary

    def names(self) -> dict[str, str]:
        return STATEMENT_NAMES

    # ---------------------------------------------------------------- reading
    def catalog(self, include: list[str] | None = None) -> dict:
        """Everything for the worklist. Up to CATALOG_FULL recordings that is the whole archive; beyond that, every recording that
        is not signed yet plus the signed ones of the last CATALOG_DAYS days, and `truncated` is true (older ones: /api/search). `include`: recording numbers to add anyway (a search result being opened)."""
        c = self.db.conn()
        total = c.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        truncated = total > CATALOG_FULL
        if truncated:
            since = (datetime.now() - timedelta(days=CATALOG_DAYS)).strftime("%Y-%m-%dT%H:%M")
            extra = [i for i in (include or [])[:50] if isinstance(i, str) and i[:1] in "EH" and i[1:].isdigit()]
            rows = c.execute("SELECT r.kind, r.summary, r.patient_id FROM recordings r JOIN reviews v ON v.ecg_id=r.id WHERE v.status!='signed' OR r.recorded_at >= ? OR r.id IN (%s) ORDER BY r.recorded_at" % ",".join("?" * len(extra)), (since, *extra)).fetchall()
            keep = {r["patient_id"] for r in rows}
            patients = [self.patient_row(r) for r in c.execute("SELECT * FROM patients ORDER BY id") if r["id"] in keep]
        else:
            rows = c.execute("SELECT kind, summary FROM recordings ORDER BY recorded_at").fetchall()
            patients = [self.patient_row(r) for r in c.execute("SELECT * FROM patients ORDER BY id")]
        ecgs, holters = [], []
        for r in rows:
            (ecgs if r["kind"] == "ecg12" else holters).append(json.loads(r["summary"]))
        desc = {}
        for e in ecgs:
            for s in e["statements"]:
                desc.setdefault(s["statement"], STATEMENT_NAMES.get(s["statement"], s["statement"]))
        return {"generated": now(), "engine": self.engine.info(), "patients": patients, "ecgs": ecgs, "holters": holters,
                "statement_descriptions": desc, "disclaimer": "", "truncated": truncated, "total_recordings": total}

    def recording(self, rid: str, kind: str) -> dict:
        r = self.db.conn().execute("SELECT detail FROM recordings WHERE id=? AND kind=?", (rid, kind)).fetchone()
        if not r:
            raise NotFound(rid)
        return _unz(r["detail"])

    def holter_signal(self, rid: str) -> bytes:
        r = self.db.conn().execute("SELECT signal FROM recordings WHERE id=? AND kind='holter'", (rid,)).fetchone()
        if not r or r["signal"] is None:
            raise NotFound(rid)
        return r["signal"]

    # ---------------------------------------------------------------- reviews
    def _review(self, r) -> dict:
        return {"status": r["status"], "decisions": json.loads(r["decisions"]), "added": json.loads(r["added"]), "edits": json.loads(r["edits"]),
                "note": r["note"], "signedBy": r["signed_by"], "signedAt": r["signed_at"], "version": r["version"]}

    def reviews(self) -> dict:
        return {r["ecg_id"]: self._review(r) for r in self.db.conn().execute("SELECT * FROM reviews")}

    def review(self, rid: str) -> dict:
        r = self.db.conn().execute("SELECT * FROM reviews WHERE ecg_id=?", (rid,)).fetchone()
        if not r:
            raise NotFound(rid)
        return self._review(r)

    def update_review(self, user: dict, rid: str, patch: dict, version: int | None = None, action: str | None = None) -> dict:
        """Reading decisions belong to the cardiologist; a technician may only send for reading or request a repeat."""
        allowed = set(patch) - {"version"}
        if user["role"] == "admin":
            raise Forbidden("administrators cannot change reviews")
        if user["role"] == "technician" and (allowed - {"status", "note"} or patch.get("status") not in (None, "in_review", "repeat", "new")):
            raise Forbidden("technicians can send an ECG for reading or request a repeat; decisions are the cardiologist's")
        if not allowed <= {"status", "decisions", "added", "edits", "note"}:
            raise ValueError(f"unknown review fields {sorted(allowed - {'status', 'decisions', 'added', 'edits', 'note'})}")
        if patch.get("status") == "signed":
            raise ValueError("use the sign action to sign")
        if "status" in patch and patch["status"] not in REVIEW_STATUSES:
            raise ValueError(f"status must be one of {REVIEW_STATUSES}")
        _check_review_fields(patch)
        with self.db.tx() as c:
            cur = c.execute("SELECT * FROM reviews WHERE ecg_id=?", (rid,)).fetchone()
            if not cur:
                raise NotFound(rid)
            if version is not None and version != cur["version"]:
                raise Conflict("this ECG was changed by someone else; reload it")
            amending = cur["status"] == "signed"
            if amending and not (user["role"] == "cardiologist" and patch.get("status") == "in_review" and set(patch) <= {"status"}):
                raise Conflict("this report is signed; a cardiologist must amend it first")
            sets, vals = ["version=version+1"], []
            for k in ("status", "note"):
                if k in patch:
                    sets.append(f"{k}=?")
                    vals.append(patch[k])
            for k in ("decisions", "added", "edits"):
                if k in patch:
                    sets.append(f"{k}=?")
                    vals.append(json.dumps(patch[k]))
            if amending:
                sets += ["signed_by=NULL", "signed_at=NULL"]
            c.execute(f"UPDATE reviews SET {', '.join(sets)} WHERE ecg_id=?", (*vals, rid))
            what = action or ("Re-opened signed report (amendment)" if amending else "Updated review")
            self.db.audit(user["name"], what, rid, c)
            self._snapshot(c, rid, user, what)
        return self.review(rid)

    def _snapshot(self, c, rid: str, user: dict, action: str) -> None:
        """Every saved state of a review is kept (review_versions): an amendment can show exactly what changed."""
        r = c.execute("SELECT * FROM reviews WHERE ecg_id=?", (rid,)).fetchone()
        c.execute("INSERT INTO review_versions(ecg_id, version, at, user, action, snapshot) VALUES (?,?,?,?,?,?)",
                  (rid, r["version"], now(), user["name"], action, json.dumps(self._review(r))))

    def history(self, rid: str) -> list[dict]:
        if not self.db.conn().execute("SELECT 1 FROM reviews WHERE ecg_id=?", (rid,)).fetchone():
            raise NotFound(rid)
        rows = self.db.conn().execute("SELECT version, at, user, action, snapshot FROM review_versions WHERE ecg_id=? ORDER BY id", (rid,)).fetchall()
        out, prev = [], None
        for r in rows:
            snap = json.loads(r["snapshot"])
            out.append({"version": r["version"], "at": r["at"], "user": r["user"], "action": r["action"], "review": snap, "changes": _diff(prev, snap)})
            prev = snap
        return out

    def sign(self, user: dict, rid: str, note: str | None = None, version: int | None = None, how: str = "") -> dict:
        if user["role"] != "cardiologist":
            raise Forbidden("only a cardiologist can sign")
        with self.db.tx() as c:
            cur = c.execute("SELECT * FROM reviews WHERE ecg_id=?", (rid,)).fetchone()
            rec = c.execute("SELECT kind, detail FROM recordings WHERE id=?", (rid,)).fetchone()
            if not cur or not rec:
                raise NotFound(rid)
            if version is not None and version != cur["version"]:
                raise Conflict("this ECG was changed by someone else; reload it")
            if cur["status"] == "signed":
                raise Conflict("already signed")
            if rec["kind"] == "ecg12":
                findings = [s["statement"] for s in _unz(rec["detail"])["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
                decisions = json.loads(cur["decisions"])
                undecided = [s for s in findings if s not in decisions]
                if undecided:
                    raise Conflict(f"decide on every AI finding before signing ({len(undecided)} left: {', '.join(undecided[:5])})")
            c.execute("UPDATE reviews SET status='signed', signed_by=?, signed_at=?, note=COALESCE(?, note), version=version+1 WHERE ecg_id=?", (user["name"], now(), note, rid))
            self.db.audit(user["name"], "Signed ECG report" if rec["kind"] == "ecg12" else "Signed Holter report", rid + (f" (confirmed by {how})" if how else ""), c)
            self._snapshot(c, rid, user, "Signed")
            self.enqueue_export(c, rid, rec["kind"])
        return self.review(rid)

    def enqueue_export(self, c, rid: str, kind: str) -> None:
        """Hook for the HIS outbox (export.py); signing never waits for the HIS."""
        from . import export

        if self.site().get("autoSendHis"):
            export.enqueue(self, c, rid)

    # ---------------------------------------------------------------- Holter beat relabelling
    def beat_labels(self, rid: str) -> dict:
        from . import holter_report
        c = self.db.conn()
        if not c.execute("SELECT 1 FROM recordings WHERE id=? AND kind='holter'", (rid,)).fetchone():
            raise NotFound(rid)
        lab = holter_report.relabels(c, rid)
        counts = holter_report.counts(_unz(c.execute("SELECT detail FROM recordings WHERE id=?", (rid,)).fetchone()["detail"]), lab)
        return {"labels": {f"{t:.3f}": v for t, v in lab.items()}, "counts": counts}

    def relabel_beat(self, user: dict, rid: str, time_s: float, label: str | None) -> dict:
        from . import holter_report
        if user["role"] != "cardiologist":
            raise Forbidden("only a cardiologist can relabel beats")
        if label is not None and label not in holter_report.CLASSES:
            raise ValueError(f"label must be one of {list(holter_report.CLASSES)} or null")
        t = round(float(time_s), 3)
        with self.db.tx() as c:
            rec = c.execute("SELECT detail FROM recordings WHERE id=? AND kind='holter'", (rid,)).fetchone()
            if not rec:
                raise NotFound(rid)
            if c.execute("SELECT status FROM reviews WHERE ecg_id=?", (rid,)).fetchone()["status"] == "signed":
                raise Conflict("this report is signed; a cardiologist must amend it first")
            beats = {round(float(b["time_s"]), 3): b["class"] for b in _unz(rec["detail"])["analysis"]["result"]["beats"]}
            if t not in beats:
                raise ValueError(f"no beat at {t} s in this recording")
            if label is None or label == beats[t]:
                c.execute("DELETE FROM beat_labels WHERE rec_id=? AND beat_time=?", (rid, t))
            else:
                c.execute("INSERT INTO beat_labels(rec_id, beat_time, label, user, at) VALUES (?,?,?,?,?) ON CONFLICT(rec_id, beat_time) DO UPDATE SET label=excluded.label, user=excluded.user, at=excluded.at",
                          (rid, t, label, user["name"], now()))
            c.execute("UPDATE reviews SET version=version+1 WHERE ecg_id=?", (rid,))
            self.db.audit(user["name"], "Relabelled Holter beat", f"{rid} at {t:.3f} s: {beats[t]} -> {label or beats[t]}", c)
        return self.beat_labels(rid)

    # ---------------------------------------------------------------- assigning an unmatched recording
    def assign_patient(self, user: dict, rid: str, mrn: str) -> dict:
        if user["role"] not in ("technician", "cardiologist"):
            raise Forbidden("only technicians and cardiologists can match ECGs to patients")
        with self.db.tx() as c:
            rec = c.execute("SELECT summary FROM recordings WHERE id=?", (rid,)).fetchone()
            p = c.execute("SELECT id FROM patients WHERE mrn=?", (mrn.strip(),)).fetchone()
            if not rec:
                raise NotFound(rid)
            if not p:
                raise NotFound(f"patient {mrn}")
            if c.execute("SELECT status FROM reviews WHERE ecg_id=?", (rid,)).fetchone()["status"] == "signed":
                raise Conflict("a signed report cannot be moved to another patient")
            s = json.loads(rec["summary"])
            s["patient_id"] = p["id"]
            c.execute("UPDATE recordings SET patient_id=?, summary=? WHERE id=?", (p["id"], json.dumps(s), rid))
            self.db.audit(user["name"], "Matched recording to patient", f"{rid} -> {mrn}", c)
        return s


def _diff(a: dict | None, b: dict) -> list[str]:
    """Readable list of what changed between two saved review states."""
    if a is None:
        return ["first saved state"]
    out = []
    if a["status"] != b["status"]:
        out.append(f"status {a['status']} -> {b['status']}")
    for k in sorted(set(a["decisions"]) | set(b["decisions"])):
        if a["decisions"].get(k) != b["decisions"].get(k):
            out.append(f"{STATEMENT_NAMES.get(k, k)}: {a['decisions'].get(k) or 'undecided'} -> {b['decisions'].get(k) or 'undecided'}")
    for k in sorted(set(b["added"]) - set(a["added"])):
        out.append(f"added finding {STATEMENT_NAMES.get(k, k)}")
    for k in sorted(set(a["added"]) - set(b["added"])):
        out.append(f"removed finding {STATEMENT_NAMES.get(k, k)}")
    for k in sorted(set(a["edits"]) | set(b["edits"])):
        if a["edits"].get(k) != b["edits"].get(k):
            out.append(f"measurement {k}: {a['edits'].get(k)} -> {b['edits'].get(k)}")
    if a["note"] != b["note"]:
        out.append("note changed")
    if a["signedBy"] != b["signedBy"]:
        out.append(f"signed by {b['signedBy']}" if b["signedBy"] else f"signature of {a['signedBy']} removed (amendment)")
    return out


def _derive(leads: dict, name: str) -> np.ndarray:
    i, ii = leads["I"], leads["II"]
    return {"III": ii - i, "AVR": -(i + ii) / 2, "AVL": i - ii / 2, "AVF": ii - i / 2}[name]


def _age(birth: str | None) -> int | None:
    if not birth:
        return None
    try:
        b = date.fromisoformat(birth[:10])
    except ValueError:
        return None
    t = date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def _check_review_fields(patch: dict) -> None:
    if "decisions" in patch and not (isinstance(patch["decisions"], dict) and all(v in ("accepted", "rejected") for v in patch["decisions"].values())):
        raise ValueError("decisions must map a statement to 'accepted' or 'rejected'")
    if "added" in patch and not (isinstance(patch["added"], list) and all(isinstance(x, str) for x in patch["added"])):
        raise ValueError("added must be a list of statement codes")
    if "edits" in patch and not (isinstance(patch["edits"], dict) and all(v is None or isinstance(v, (int, float)) for v in patch["edits"].values())):
        raise ValueError("edits must map a measurement point to a number or null")
    if "note" in patch and (not isinstance(patch["note"], str) or len(patch["note"]) > 4000):
        raise ValueError("note must be text of at most 4000 characters")


STATEMENT_NAMES: dict[str, str] = json.loads((Path(__file__).parent / "statements.json").read_text())
