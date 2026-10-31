"""Philips PageWriter / TraceMaster XML (restingecgdata, SierraECG / PhilipsECG 1.03–1.04.02).

The waveform is base64; either uncompressed 16-bit or XLI-compressed (LZW + second-difference coding).
XLI decoding uses `sierraecg` (MIT licence, Christopher Watford), the open-source reference decoder.
Philips stores leads III, aVR, aVL and aVF as residuals from their values computed from I and II; they are
reconstructed the same way the reference reader does.
"""

from __future__ import annotations

import base64
import binascii
import math
import xml.etree.ElementTree as ET

import numpy as np

from .common import IngestError, finish, norm_lead

STD12 = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, name):
    return next((c for c in el.iter() if _local(c.tag) == name), None)


def _text(el, name, default=None):
    c = _find(el, name) if el is not None else None
    return (c.text or "").strip() if c is not None and c.text and c.text.strip() else default


def reconstruct_limb_leads(raw: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Philips residual coding of the derived limb leads (as the reference reader does it)."""
    i, ii = raw["I"].astype(np.int64), raw["II"].astype(np.int64)
    out = dict(raw)
    iii = ii - i - raw["III"].astype(np.int64)
    out["III"] = iii
    out["aVR"] = -raw["aVR"].astype(np.int64) - np.floor((i + ii) / 2).astype(np.int64)
    out["aVL"] = np.floor((i - iii) / 2).astype(np.int64) - raw["aVL"].astype(np.int64)
    out["aVF"] = np.floor((ii + iii) / 2).astype(np.int64) - raw["aVF"].astype(np.int64)
    return out


def read(data: bytes, fs: float | None = None, units: str | None = None):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise IngestError(f"philips: not valid XML ({e})") from None
    sig = _find(root, "signalcharacteristics")
    pw = _find(root, "parsedwaveforms")
    if sig is None or pw is None:
        raise IngestError("philips: no signalcharacteristics / parsedwaveforms (this export has no waveform)")
    rate = float(_text(sig, "samplingrate", "0") or 0)
    if fs is None and rate <= 0:
        raise IngestError("philips: no sampling rate")
    fs = fs or rate
    labels = (pw.get("leadlabels") or "").split()
    n = int(pw.get("numberofleads") or len(labels) or int(_text(sig, "numberchannelsallocated", "12")))
    if not labels:
        acq = _text(sig, "acquisitiontype", "STD-12")
        if acq not in ("STD-12", "10-WIRE"):
            raise IngestError(f"philips: acquisition type {acq} is not a standard 12-lead recording")
        labels = STD12[:n]
    labels = labels[:n]
    if (pw.get("dataencoding") or "Base64") != "Base64":
        raise IngestError(f"philips: waveform encoding {pw.get('dataencoding')} is not supported")
    try:
        blob = base64.b64decode("".join((pw.text or "").split()), validate=True)
    except binascii.Error:
        raise IngestError("philips: waveform is not valid base64") from None
    method = pw.get("compressmethod") or pw.get("compression") or "Uncompressed"
    duration_ms = float(pw.get("durationperchannel") or 0)
    if method == "XLI":
        from sierraecg.xli import xli_decode
        try:
            chans = xli_decode(blob, labels)
        except Exception as e:  # malformed compressed data
            raise IngestError(f"philips: XLI data could not be decoded ({type(e).__name__})") from None
    elif method == "Uncompressed":
        count = int(round(duration_ms * fs / 1000)) if duration_ms else len(blob) // 2 // n
        allv = np.frombuffer(blob[: 2 * count * n], dtype="<i2")
        chans = [allv[k * count:(k + 1) * count] for k in range(n)]
    else:
        raise IngestError(f"philips: waveform compression {method} is not supported")
    if len(chans) < len(labels):
        raise IngestError(f"philips: {len(chans)} waveform channels for {len(labels)} leads")
    raw = {lab: np.asarray(ch, dtype=np.int64) for lab, ch in zip(labels, chans)}
    if duration_ms:
        keep = int(round(duration_ms * fs / 1000))
        raw = {k: v[:keep] for k, v in raw.items()}
    if method == "XLI" and all(k in raw for k in ("I", "II", "III", "aVR", "aVL", "aVF")):
        raw = reconstruct_limb_leads(raw)
    res = _text(sig, "signalresolution") or _text(sig, "resolution")
    notes = []
    if res is None:
        notes.append("amplitude resolution not stated in the file; 5 µV per unit assumed (Philips default)")
    uv = float(res or 5)
    leads = {}
    for lab, v in raw.items():
        name = norm_lead(lab)
        if name and name not in leads:
            leads[name] = v.astype(np.float64) * uv / 1000.0
    pat = {}
    pid = _text(root, "patientid")
    if pid:
        pat["id"] = pid
    gp = _find(root, "generalpatientdata")
    first, last = _text(gp, "firstname"), _text(gp, "lastname")
    if first or last:
        pat["name"] = " ".join(x for x in (first, last) if x)
    sex = (_text(gp, "sex", "") or "")[:1].upper()
    if sex in ("M", "F"):
        pat["sex"] = sex
    dob = _text(gp, "dateofbirth")
    if dob and len(dob) >= 10 and dob[4] == "-":
        pat["birth_date"] = dob[:10]
    acq = _find(root, "dataacquisition")
    rec = None
    if acq is not None and acq.get("date"):
        rec = f"{acq.get('date')}T{acq.get('time') or '00:00:00'}"
    device = " ".join(x for x in (_text(root, "machine") or (_find(root, "machine").get("machineid") if _find(root, "machine") is not None else None),) if x) or "Philips"
    return finish(fs, leads, "philips-xml", patient=pat, recorded_at=rec, device=device, notes=notes)
