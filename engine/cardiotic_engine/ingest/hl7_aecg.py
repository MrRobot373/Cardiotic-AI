"""HL7 v3 annotated ECG (FDA XML, also Philips SierraECG exports): SLIST_PQ digit sequences per lead."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np

from .common import IngestError, finish, norm_lead, unit_factor


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, *path):
    for name in path:
        el = next((c for c in el.iter() if _local(c.tag) == name), None)
        if el is None:
            return None
    return el


def read(data: bytes, fs: float | None = None, units: str | None = None):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise IngestError(f"aecg: not valid XML ({e})") from None
    best: dict[str, np.ndarray] = {}
    inc_s = None
    for ss in (e for e in root.iter() if _local(e.tag) == "sequenceSet"):
        leads, inc = {}, None
        for seq in (e for e in ss.iter() if _local(e.tag) == "sequence"):
            code_el = next((c for c in seq if _local(c.tag) == "code"), None)
            val = next((c for c in seq if _local(c.tag) == "value"), None)
            if code_el is None or val is None:
                continue
            code = code_el.get("code", "")
            if "TIME" in code:
                incr = next((c for c in val.iter() if _local(c.tag) == "increment"), None)
                if incr is not None and incr.get("value"):
                    inc = float(incr.get("value")) * {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6}.get((incr.get("unit") or "s").lower(), 1.0)
                continue
            name = norm_lead(code)
            digits = next((c for c in val.iter() if _local(c.tag) == "digits"), None)
            if not name or digits is None or not (digits.text or "").strip():
                continue
            scale = next((c for c in val if _local(c.tag) == "scale"), None)
            origin = next((c for c in val if _local(c.tag) == "origin"), None)
            sc = float(scale.get("value", "1")) if scale is not None else 1.0
            og = float(origin.get("value", "0")) if origin is not None else 0.0
            f = unit_factor((scale if scale is not None else origin).get("unit") if (scale is not None or origin is not None) else None, units or "uV")
            d = np.array(digits.text.split(), dtype=np.float64)
            leads[name] = (og + sc * d) * f
        if leads and (not best or len(next(iter(leads.values()))) > len(next(iter(best.values())))):
            best, inc_s = leads, inc  # the longest sequence set is the rhythm strip, not a representative beat
    if not best:
        raise IngestError("aecg: no lead sequences found")
    if fs is None:
        if not inc_s:
            raise IngestError("aecg: no time increment in the file; pass fs")
        fs = 1.0 / inc_s
    pat = {}
    pid = _find(root, "trialSubject", "id")
    if pid is None:
        pid = _find(root, "subject", "id")
    if pid is not None and pid.get("extension"):
        pat["id"] = pid.get("extension")
    sex = _find(root, "administrativeGenderCode")
    if sex is not None and sex.get("code") in ("M", "F"):
        pat["sex"] = sex.get("code")
    birth = _find(root, "subjectDemographicPerson", "birthTime")
    if birth is not None and birth.get("value"):
        b = birth.get("value")
        pat["birth_date"] = f"{b[:4]}-{b[4:6]}-{b[6:8]}" if len(b) >= 8 else b
    low = _find(root, "effectiveTime", "low")
    t = low.get("value") if low is not None else None
    rec = f"{t[:4]}-{t[4:6]}-{t[6:8]}T{t[8:10]}:{t[10:12]}:{t[12:14]}" if t and len(t) >= 14 else None
    return finish(fs, best, "hl7-aecg", patient=pat, recorded_at=rec)
