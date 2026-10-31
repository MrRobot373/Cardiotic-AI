"""SCP-ECG (EN 1064 / ISO 11073-91064): sections 0 (pointers), 1 (patient), 3 (leads), 6 (rhythm data).

Supported: uncompressed or first/second-difference 16-bit data (no Section 2 Huffman tables).
Not supported yet, with a clear error: Huffman-compressed data (Section 2) and reference-beat
subtraction (Section 5). Many carts write Huffman SCP: export those as DICOM or HL7 aECG.
"""

from __future__ import annotations

import struct

import numpy as np

from .common import IngestError, finish

LEAD_CODES = {1: "I", 2: "II", 3: "V1", 4: "V2", 5: "V3", 6: "V4", 7: "V5", 8: "V6",
              61: "III", 62: "AVR", 63: "AVL", 64: "AVF"}


def crc16(b: bytes) -> int:
    crc = 0xFFFF
    for byte in b:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def looks_like_scp(data: bytes) -> bool:
    return len(data) > 22 and struct.unpack_from("<I", data, 2)[0] == len(data) and struct.unpack_from("<H", data, 8)[0] == 0  # size, then section 0 id


def _sections(data: bytes) -> tuple[dict[int, bytes], list[str]]:
    notes = []
    if struct.unpack_from("<H", data, 0)[0] != crc16(data[2:]):
        notes.append("SCP-ECG file CRC does not match (file may be damaged or written by a lenient cart)")
    n0 = struct.unpack_from("<I", data, 10)[0]  # section 0 length
    out, pos = {}, 6 + 16
    while pos + 10 <= 6 + n0:
        sid, length, index = struct.unpack_from("<HII", data, pos)
        pos += 10
        if length == 0 or index == 0:
            continue
        start = index - 1
        if start + length > len(data):
            raise IngestError(f"scp-ecg: section {sid} points outside the file")
        out[sid] = data[start + 16: start + length]
    return out, notes


def _s1(b: bytes) -> dict:
    pat, pos = {}, 0
    while pos + 3 <= len(b):
        tag, ln = b[pos], struct.unpack_from("<H", b, pos + 1)[0]
        v = b[pos + 3: pos + 3 + ln]
        pos += 3 + ln
        if tag == 255:
            break
        text = v.split(b"\x00")[0].decode("latin-1", "replace").strip()
        if tag == 2 and text:
            pat["id"] = text
        elif tag == 0 and text:
            pat["_last"] = text
        elif tag == 1 and text:
            pat["_first"] = text
        elif tag == 5 and len(v) >= 4:
            y, m, d = struct.unpack_from("<HBB", v)
            pat["birth_date"] = f"{y:04d}-{m:02d}-{d:02d}"
        elif tag == 8 and v[:1] in (b"\x01", b"\x02"):
            pat["sex"] = "M" if v[0] == 1 else "F"
    name = " ".join(x for x in (pat.pop("_first", None), pat.pop("_last", None)) if x)
    if name:
        pat["name"] = name
    return pat


def read(data: bytes, fs: float | None = None, units: str | None = None):
    if not looks_like_scp(data):
        raise IngestError("scp-ecg: not an SCP-ECG file")
    sec, notes = _sections(data)
    if 2 in sec:
        raise IngestError("scp-ecg: Huffman-compressed SCP-ECG (Section 2) is not supported yet; export the ECG as DICOM or HL7 aECG")
    if 3 not in sec or 6 not in sec:
        raise IngestError("scp-ecg: lead definition (Section 3) or rhythm data (Section 6) is missing")
    s3 = sec[3]
    n_leads, flags = s3[0], s3[1]
    if flags & 1:
        raise IngestError("scp-ecg: reference-beat subtraction is not supported yet")
    spans = []
    for i in range(n_leads):
        start, end, code = struct.unpack_from("<IIB", s3, 2 + 9 * i)
        spans.append((start, end, code))
    s6 = sec[6]
    avm, stm, enc, _bim = struct.unpack_from("<HHBB", s6, 0)
    lens = struct.unpack_from(f"<{n_leads}H", s6, 6)
    if enc not in (0, 1, 2):
        raise IngestError(f"scp-ecg: unknown encoding type {enc}")
    pos = 6 + 2 * n_leads
    leads = {}
    for (start, end, code), nbytes in zip(spans, lens):
        raw = np.frombuffer(s6, dtype="<i2", count=nbytes // 2, offset=pos).astype(np.int64)
        pos += nbytes
        if enc >= 1:
            raw = np.cumsum(raw)
        if enc == 2:
            raw = np.cumsum(raw)
        name = LEAD_CODES.get(code)
        if name and name not in leads:
            leads[name] = raw * avm * 1e-6  # AVM is nanovolts per bit -> mV
    if stm <= 0:
        raise IngestError("scp-ecg: invalid sample interval")
    return finish(fs or 1e6 / stm, leads, "scp-ecg", patient=_s1(sec[1]) if 1 in sec else {}, notes=notes)
