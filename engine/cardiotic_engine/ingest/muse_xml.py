"""GE MUSE XML (RestingECG): base64 16-bit little-endian samples per lead. MUSE usually stores 8 leads
(I, II, V1–V6); the engine derives III, aVR, aVL and aVF."""

from __future__ import annotations

import base64
import binascii
import xml.etree.ElementTree as ET

import numpy as np

from .common import IngestError, finish, norm_lead, unit_factor


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    c = next((c for c in el.iter() if _local(c.tag) == name), None)
    return (c.text or "").strip() if c is not None and c.text else None


def read(data: bytes, fs: float | None = None, units: str | None = None):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise IngestError(f"muse: not valid XML ({e})") from None
    waves = [w for w in root.iter() if _local(w.tag) == "Waveform"]
    wave = next((w for w in waves if (_text(w, "WaveformType") or "").lower() == "rhythm"), waves[0] if waves else None)
    if wave is None:
        raise IngestError("muse: no Waveform element")
    if fs is None:
        base = _text(wave, "SampleBase")
        if not base:
            raise IngestError("muse: no SampleBase; pass fs")
        fs = float(base) * 10 ** float(_text(wave, "SampleExponent") or 0)
    leads = {}
    for ld in (e for e in wave.iter() if _local(e.tag) == "LeadData"):
        name = norm_lead(_text(ld, "LeadID") or "")
        b64 = _text(ld, "WaveFormData")
        if not name or not b64:
            continue
        try:
            raw = base64.b64decode("".join(b64.split()), validate=True)
        except binascii.Error:
            raise IngestError(f"muse: lead {name} is not valid base64") from None
        if len(raw) % 2:
            raise IngestError(f"muse: lead {name} has an odd number of bytes")
        per_bit = float(_text(ld, "LeadAmplitudeUnitsPerBit") or 1.0)
        leads[name] = np.frombuffer(raw, dtype="<i2").astype(np.float64) * per_bit * unit_factor(_text(ld, "LeadAmplitudeUnits") or units or "MICROVOLTS")
    pat = {}
    pid = _text(root, "PatientID")
    if pid:
        pat["id"] = pid
    last, first = _text(root, "PatientLastName"), _text(root, "PatientFirstName")
    if last or first:
        pat["name"] = " ".join(x for x in (first, last) if x)
    sex = (_text(root, "Gender") or "").upper()[:1]
    if sex in ("M", "F"):
        pat["sex"] = sex
    dob = _text(root, "DateofBirth")
    if dob and len(dob.split("-")) == 3:
        mm, dd, yy = dob.split("-")  # MUSE writes MM-DD-YYYY
        pat["birth_date"] = f"{yy}-{mm}-{dd}"
    d, t = _text(root, "AcquisitionDate"), _text(root, "AcquisitionTime")
    rec = None
    if d and t and len(d.split("-")) == 3:
        mm, dd, yy = d.split("-")
        rec = f"{yy}-{mm}-{dd}T{t}"
    return finish(fs, leads, "ge-muse-xml", patient=pat, recorded_at=rec, device=_text(root, "SoftwareVersion") or _text(root, "ModelDescription"))
