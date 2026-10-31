"""SCP-ECG (EN 1064 / ISO 11073-91064): sections 0 (pointers), 1 (patient), 2 (Huffman tables), 3 (leads),
6 (rhythm data).

Rhythm data may be uncompressed, first- or second-difference coded, and Huffman coded with the tables in
Section 2 or the standard's default table (Section 2 table count 19999). Refused with a clear error:
reference-beat subtraction (Section 3 flag, Section 5 data), which some carts use for long recordings.
"""

from __future__ import annotations

import struct

import numpy as np

from .common import IngestError, finish

LEAD_CODES = {1: "I", 2: "II", 3: "V1", 4: "V2", 5: "V3", 6: "V4", 7: "V5", 8: "V6",
              61: "III", 62: "AVR", 63: "AVL", 64: "AVF"}


# The standard's default Huffman table: (prefix bits, total bits, table-mode switch, base value, base code).
# Codes are given with the first transmitted bit as the least significant bit. 0 -> "0"; +/-1..8 -> n ones,
# a zero and a sign bit; the last two entries carry the value itself in 8 or 16 bits after a 10-bit prefix.
DEFAULT_HUFFMAN = [(1, 1, 1, 0, 0)] + [e for v in range(1, 9) for e in (
    (v + 2 if v < 8 else 10, v + 2 if v < 8 else 10, 1, v, (1 << v) - 1),
    (v + 2 if v < 8 else 10, v + 2 if v < 8 else 10, 1, -v, (1 << v) - 1 + (1 << (v + 1))))] + [(10, 18, 1, 0, 511), (10, 26, 1, 0, 1023)]


def huffman_tables(s2: bytes) -> list[list[tuple[int, int, int, int, int]]]:
    n = struct.unpack_from("<H", s2, 0)[0]
    if n == 19999:
        return [DEFAULT_HUFFMAN]
    tables, pos = [], 2
    for _ in range(n):
        m = struct.unpack_from("<H", s2, pos)[0]
        pos += 2
        t = []
        for _ in range(m):
            t.append(struct.unpack_from("<BBBhI", s2, pos))
            pos += 9
        tables.append(t)
    if not tables or not all(tables):
        raise IngestError("scp-ecg: Section 2 has no Huffman codes")
    return tables


def huffman_decode(data: bytes, count: int, tables) -> np.ndarray:
    """`count` values from a Huffman bit stream (bits read most significant first within each byte)."""
    lookup = [{(p, c): (tot, mode, val) for p, tot, mode, val, c in t} for t in tables]
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    out, pos, table, n_bits = [], 0, 0, len(bits)
    while len(out) < count:
        code, k = 0, 0
        while True:
            if pos >= n_bits:
                raise IngestError(f"scp-ecg: Huffman data ends after {len(out)} of {count} samples")
            code |= int(bits[pos]) << k
            pos += 1
            k += 1
            hit = lookup[table].get((k, code))
            if hit is not None:
                break
            if k > 32:
                raise IngestError("scp-ecg: invalid Huffman code")
        tot, mode, val = hit
        if mode == 0:  # switch to another table, no value
            table = val - 1
            if not 0 <= table < len(lookup):
                raise IngestError("scp-ecg: Huffman table switch to a table that does not exist")
            continue
        extra = tot - k
        if extra:
            if pos + extra > n_bits:
                raise IngestError("scp-ecg: Huffman data ends inside a value")
            v = 0
            for b in bits[pos:pos + extra]:
                v = (v << 1) | int(b)
            pos += extra
            if v >= 1 << (extra - 1):
                v -= 1 << extra
            out.append(v)
        else:
            out.append(val)
    return np.asarray(out, dtype=np.int64)


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
    tables = huffman_tables(sec[2]) if 2 in sec else None
    if 3 not in sec or 6 not in sec:
        raise IngestError("scp-ecg: lead definition (Section 3) or rhythm data (Section 6) is missing")
    s3 = sec[3]
    n_leads, flags = s3[0], s3[1]
    if flags & 1:
        raise IngestError("scp-ecg: this file uses reference-beat subtraction, which is not read; set the cart to export SCP-ECG without it, or DICOM / HL7 aECG")
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
        if tables is not None:
            raw = huffman_decode(s6[pos:pos + nbytes], end - start + 1, tables)
        else:
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
