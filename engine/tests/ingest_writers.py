"""Writers used to test the ECG file readers: each produces a file as the format's specification describes.

These are NOT vendor files: they prove that the readers follow the published layouts and round-trip real
ECG samples. A reader must still be run on real exports from each cart model before that cart is claimed.
"""

from __future__ import annotations

import base64
import io
import struct

import numpy as np

LEADS = ("I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6")
PRETTY = {"AVR": "aVR", "AVL": "aVL", "AVF": "aVF"}


def csv_file(x, fs, unit="mV", with_time=False, comment=True, leads=LEADS):
    k = {"mV": 1.0, "uV": 1000.0}[unit]
    lines = [f"# fs={fs}"] if comment else []
    lines.append(",".join((["time"] if with_time else []) + [f"{PRETTY.get(l, l)} ({unit})" for l in leads]))
    for i in range(x.shape[1]):
        lines.append(",".join(([f"{i / fs:.6f}"] if with_time else []) + [f"{x[LEADS.index(l), i] * k:.5f}" for l in leads]))
    return "\n".join(lines).encode()


def edf_file(x, fs, leads=LEADS, patient="PAT-7 F 01-JAN-1960 X"):
    n = x.shape[1] // int(fs)  # whole seconds, one record per second
    ns = len(leads)
    h = [b"0       ", patient.ljust(80).encode(), b"Startdate".ljust(80), b"01.01.26", b"08.00.00",
         str(256 + 256 * ns).ljust(8).encode(), b"".ljust(44), str(n).ljust(8).encode(), b"1".ljust(8), str(ns).ljust(4).encode()]
    cols = [
        [f"ECG {PRETTY.get(l, l)}".ljust(16).encode() for l in leads], [b"".ljust(80)] * ns, [b"uV".ljust(8)] * ns,
        [b"-5000".ljust(8)] * ns, [b"5000".ljust(8)] * ns, [b"-32768".ljust(8)] * ns, [b"32767".ljust(8)] * ns,
        [b"".ljust(80)] * ns, [str(int(fs)).ljust(8).encode()] * ns, [b"".ljust(32)] * ns]
    out = b"".join(h) + b"".join(b"".join(c) for c in cols)
    idx = [LEADS.index(l) for l in leads]
    dig = np.clip(np.round((x[idx] * 1000 + 5000) * 65535 / 10000 - 32768), -32768, 32767).astype("<i2")
    for r in range(n):
        for row in dig:
            out += row[r * int(fs):(r + 1) * int(fs)].tobytes()
    return out


def aecg_file(x, fs, leads=LEADS):
    scale = 2.5  # uV per digit
    seqs = []
    for l in leads:
        d = np.round(x[LEADS.index(l)] * 1000 / scale).astype(int)
        seqs.append(f'<component><sequence><code code="MDC_ECG_LEAD_{l}" codeSystem="2.16.840.1.113883.6.24"/>'
                    f'<value xsi:type="SLIST_PQ"><origin value="0" unit="uV"/><scale value="{scale}" unit="uV"/>'
                    f'<digits>{" ".join(map(str, d))}</digits></value></sequence></component>')
    return ('<?xml version="1.0" encoding="UTF-8"?><AnnotatedECG xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<componentOf><timepointEvent><componentOf><subjectAssignment><subject><trialSubject><id extension="PAT-7" root="x"/>'
            '<subjectDemographicPerson><administrativeGenderCode code="F"/><birthTime value="19600101"/></subjectDemographicPerson>'
            '</trialSubject></subject></subjectAssignment></componentOf></timepointEvent></componentOf>'
            '<effectiveTime><low value="20260105081530"/></effectiveTime>'
            '<component><series><component><sequenceSet>'
            f'<component><sequence><code code="MDC_ECG_TIME_PD_RELATIVE"/><value xsi:type="GLIST_TS"><head value="0" unit="s"/><increment value="{1 / fs}" unit="s"/></value></sequence></component>'
            + "".join(seqs) + '</sequenceSet></component></series></component></AnnotatedECG>').encode()


def muse_file(x, fs, leads=("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")):
    per_bit = 4.88
    ld = ""
    for l in leads:
        raw = np.round(x[LEADS.index(l)] * 1000 / per_bit).astype("<i2").tobytes()
        ld += (f"<LeadData><LeadID>{l}</LeadID><LeadAmplitudeUnitsPerBit>{per_bit}</LeadAmplitudeUnitsPerBit>"
               f"<LeadAmplitudeUnits>MICROVOLTS</LeadAmplitudeUnits><WaveFormData>{base64.b64encode(raw).decode()}</WaveFormData></LeadData>")
    return ('<?xml version="1.0"?><RestingECG><PatientDemographics><PatientID>PAT-7</PatientID><PatientLastName>Rao</PatientLastName>'
            '<PatientFirstName>Meera</PatientFirstName><Gender>FEMALE</Gender><DateofBirth>01-01-1960</DateofBirth></PatientDemographics>'
            '<TestDemographics><AcquisitionDate>01-05-2026</AcquisitionDate><AcquisitionTime>08:15:30</AcquisitionTime></TestDemographics>'
            f'<Waveform><WaveformType>Median</WaveformType><SampleBase>{int(fs)}</SampleBase><LeadData><LeadID>I</LeadID></LeadData></Waveform>'
            f'<Waveform><WaveformType>Rhythm</WaveformType><SampleBase>{int(fs)}</SampleBase><SampleExponent>0</SampleExponent>{ld}</Waveform></RestingECG>').encode()


def dicom_file(x, fs, leads=LEADS):
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    code = lambda v, m: _ds(CodeValue=v, CodingSchemeDesignator="MDC", CodeMeaning=m)  # noqa: E731

    def _ds(**kw):
        d = Dataset()
        for k, v in kw.items():
            setattr(d, k, v)
        return d

    chans = []
    for l in leads:
        c = _ds(ChannelSourceSequence=Sequence([code("2:1", f"Lead {PRETTY.get(l, l)}")]), ChannelSensitivity="1", ChannelSensitivityCorrectionFactor="1",
                ChannelBaseline="0", ChannelSampleSkew="0", WaveformBitsStored=16,
                ChannelSensitivityUnitsSequence=Sequence([_ds(CodeValue="uV", CodingSchemeDesignator="UCUM", CodeMeaning="microvolt")]))
        chans.append(c)
    idx = [LEADS.index(l) for l in leads]
    data = np.round(x[idx] * 1000).astype("<i2").T.copy()  # (samples, channels) in uV, interleaved
    grp = _ds(WaveformOriginality="ORIGINAL", NumberOfWaveformChannels=len(leads), NumberOfWaveformSamples=x.shape[1], SamplingFrequency=str(fs),
              ChannelDefinitionSequence=Sequence(chans), WaveformBitsAllocated=16, WaveformSampleInterpretation="SS", WaveformData=data.tobytes())
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.9.1.1"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
    ds.PatientID, ds.PatientName, ds.PatientSex, ds.PatientBirthDate = "PAT-7", "Rao^Meera", "F", "19600101"
    ds.AcquisitionDateTime = "20260105081530"
    ds.Manufacturer, ds.ManufacturerModelName = "TestCart", "T1"
    ds.WaveformSequence = Sequence([grp])
    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds, enforce_file_format=True)
    return buf.getvalue()


def _crc16(b):
    crc = 0xFFFF
    for byte in b:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def scp_file(x, fs, enc=0, leads=("I", "II", "V1", "V2", "V3", "V4", "V5", "V6"), huffman=False):
    codes = {"I": 1, "II": 2, "V1": 3, "V2": 4, "V3": 5, "V4": 6, "V5": 7, "V6": 8, "III": 61, "AVR": 62, "AVL": 63, "AVF": 64}
    avm = 1000  # nanovolts per bit
    n = x.shape[1]

    def section(sid, body):
        h = struct.pack("<HIBB6x", sid, len(body) + 16, 20, 20)
        return struct.pack("<H", _crc16(h + body)) + h + body

    s1 = bytes([2]) + struct.pack("<H", 6) + b"PAT-7\x00" + bytes([0]) + struct.pack("<H", 4) + b"Rao\x00" \
        + bytes([1]) + struct.pack("<H", 6) + b"Meera\x00" + bytes([8]) + struct.pack("<H", 1) + b"\x02" \
        + bytes([5]) + struct.pack("<H", 4) + struct.pack("<HBB", 1960, 1, 1) + bytes([255]) + struct.pack("<H", 0)
    s3 = bytes([len(leads), 0b00000100 | (len(leads) << 3)]) + b"".join(struct.pack("<IIB", 1, n, codes[l]) for l in leads)
    chans = []
    for l in leads:
        v = np.round(x[LEADS.index(l)] * 1e6 / avm).astype(np.int64)  # mV -> nV -> counts
        if enc == 1:
            v = np.diff(v, prepend=0)
        elif enc == 2:
            v = np.diff(np.diff(v, prepend=0), prepend=0)
        chans.append(v.astype("<i2").tobytes())
    s6 = struct.pack("<HHBB", avm, int(round(1e6 / fs)), enc, 0) + b"".join(struct.pack("<H", len(c)) for c in chans) + b"".join(chans)
    secs = {1: s1, 3: s3, 6: s6}
    if huffman:
        secs[2] = b"\x01\x00"
    blocks = {sid: section(sid, body) for sid, body in sorted(secs.items())}
    ptr_len = 16 + 10 * 12
    pos = 6 + ptr_len + 1
    table = b""
    for sid in range(12):
        if sid in blocks:
            table += struct.pack("<HII", sid, len(blocks[sid]), pos)
            pos += len(blocks[sid])
        else:
            table += struct.pack("<HII", sid, 0, 0)
    sec0 = section(0, table)  # pointer section describes itself implicitly; positions above skip its own block
    # section 0 starts at byte 7 (index 7 -> offset 6): CRC(2)+header(16)+table
    total = 6 + len(sec0) + sum(len(b) for b in blocks.values())
    pos = 6 + len(sec0) + 1
    table = b""
    for sid in range(12):
        if sid in blocks:
            table += struct.pack("<HII", sid, len(blocks[sid]), pos)
            pos += len(blocks[sid])
        else:
            table += struct.pack("<HII", sid, 0, 0)
    sec0 = section(0, table)
    body = sec0 + b"".join(blocks.values())
    head = struct.pack("<I", 6 + len(body))
    return struct.pack("<H", _crc16(head + body)) + head + body


# ------------------------------------------------------------------ Philips XML with XLI compression
def _lzw_encode(data: bytes, bits: int = 10) -> bytes:
    max_code = (1 << bits) - 2
    table = {bytes([i]): i for i in range(256)}
    nxt, w, codes = 256, b"", []
    for ch in data:
        wc = w + bytes([ch])
        if wc in table:
            w = wc
        else:
            codes.append(table[w])
            if nxt <= max_code:
                table[wc] = nxt
                nxt += 1
            w = bytes([ch])
    if w:
        codes.append(table[w])
    acc, nacc, out = 0, 0, bytearray()
    for c in codes:
        acc = (acc << bits) | c
        nacc += bits
        while nacc >= 8:
            out.append((acc >> (nacc - 8)) & 0xFF)
            nacc -= 8
    if nacc:
        out.append((acc << (8 - nacc)) & 0xFF)
    return bytes(out)


def _xli_chunk(x: np.ndarray) -> bytes:
    """Inverse of the reference XLI decoder for one lead of int16 samples."""
    out = [int(v) for v in x]
    n = len(out)
    raw = [0] * n
    raw[0], raw[1] = out[0], out[1]
    first = 2 * out[1] - out[0] - out[2]
    for i in range(3, n):
        raw[i - 1] = (2 * out[i - 1] - out[i - 2] - out[i]) + 64
    raw[n - 1] = 64
    r16 = np.asarray(raw, dtype=np.int64).astype(np.int16).view(np.uint16)
    buf = bytes((r16 >> 8).astype(np.uint8)) + bytes((r16 & 0xFF).astype(np.uint8))
    comp = _lzw_encode(buf)
    return struct.pack("<iHh", len(comp), 0, first) + comp


def philips_file(x, fs, compression="XLI", resolution=5):
    labels = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
    counts = {l: np.round(x[LEADS.index(l.upper())] * 1000 / resolution).astype(np.int64) for l in labels}
    if compression == "XLI":  # Philips residual coding of the derived limb leads
        i, ii, iii = counts["I"], counts["II"], counts["III"]
        stored = dict(counts)
        stored["III"] = ii - i - iii
        stored["aVR"] = -counts["aVR"] - np.floor((i + ii) / 2).astype(np.int64)
        stored["aVL"] = np.floor((i - iii) / 2).astype(np.int64) - counts["aVL"]
        stored["aVF"] = np.floor((ii + iii) / 2).astype(np.int64) - counts["aVF"]
        blob = b"".join(_xli_chunk(stored[l]) for l in labels)
    else:
        blob = b"".join(counts[l].astype("<i2").tobytes() for l in labels)
    dur = int(round(x.shape[1] / fs * 1000))
    return ('<?xml version="1.0" encoding="utf-8"?><restingecgdata xmlns="http://www3.medical.philips.com">'
            '<documentinfo><documenttype>PhilipsECG</documenttype><documentversion>1.04</documentversion></documentinfo>'
            '<dataacquisition date="2026-01-05" time="08:15:30"><machine machineid="PageWriter TC50">PageWriter TC50</machine>'
            f'<signalcharacteristics><samplingrate>{int(fs)}</samplingrate><signalresolution>{resolution}</signalresolution>'
            '<acquisitiontype>STD-12</acquisitiontype><numberchannelsallocated>12</numberchannelsallocated></signalcharacteristics></dataacquisition>'
            '<patient><generalpatientdata><patientid>PAT-7</patientid><name><firstname>Meera</firstname><lastname>Rao</lastname></name>'
            '<sex>Female</sex><age><dateofbirth>1960-01-01</dateofbirth></age></generalpatientdata></patient>'
            f'<waveforms><parsedwaveforms durationperchannel="{dur}" numberofleads="12" leadlabels="{" ".join(labels)}" dataencoding="Base64" '
            f'compression="{compression}">{base64.b64encode(blob).decode()}</parsedwaveforms></waveforms></restingecgdata>').encode()


# ------------------------------------------------------------------ SCP-ECG Huffman
def _huff_encode(values, table) -> bytes:
    bits = []
    by_value = {val: (p, c) for p, tot, mode, val, c in table if tot == p and mode == 1}
    esc = sorted((tot - p, p, c) for p, tot, mode, val, c in table if tot > p)
    for v in values:
        if v in by_value:
            p, c = by_value[v]
            bits += [(c >> k) & 1 for k in range(p)]
        else:
            nb, p, c = next(e for e in esc if -(1 << (e[0] - 1)) <= v < (1 << (e[0] - 1)))
            bits += [(c >> k) & 1 for k in range(p)]
            bits += [((v & ((1 << nb) - 1)) >> (nb - 1 - k)) & 1 for k in range(nb)]
    bits += [0] * (-len(bits) % 8)
    return bytes(np.packbits(np.asarray(bits, dtype=np.uint8)))


def scp_huffman_file(x, fs, custom_table=False, enc=1, leads=("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")):
    from cardiotic_engine.ingest.scp_ecg import DEFAULT_HUFFMAN
    table = DEFAULT_HUFFMAN
    if custom_table:  # a site-specific table: 0 and +/-1 get short codes, everything else the 16-bit escape
        table = [(1, 1, 1, 0, 0), (2, 2, 1, 1, 1), (3, 3, 1, -1, 3), (3, 19, 1, 0, 7)]
    base = scp_file(x, fs, enc=enc, leads=leads)
    codes = {"I": 1, "II": 2, "V1": 3, "V2": 4, "V3": 5, "V4": 6, "V5": 7, "V6": 8}
    avm, n = 1000, x.shape[1]
    chans = []
    for l in leads:
        v = np.round(x[LEADS.index(l)] * 1e6 / avm).astype(np.int64)
        if enc == 1:
            v = np.diff(v, prepend=0)
        chans.append(_huff_encode([int(t) for t in v], table))
    s6 = struct.pack("<HHBB", avm, int(round(1e6 / fs)), enc, 0) + b"".join(struct.pack("<H", len(c)) for c in chans) + b"".join(chans)
    s2 = struct.pack("<H", 19999) if not custom_table else struct.pack("<HH", 1, len(table)) + b"".join(struct.pack("<BBBhI", *e) for e in table)
    s3 = bytes([len(leads), 0b00000100 | (len(leads) << 3)]) + b"".join(struct.pack("<IIB", 1, n, codes[l]) for l in leads)
    s1 = bytes([2]) + struct.pack("<H", 6) + b"PAT-7\x00" + bytes([255]) + struct.pack("<H", 0)

    def section(sid, body):
        h = struct.pack("<HIBB6x", sid, len(body) + 16, 20, 20)
        return struct.pack("<H", _crc16(h + body)) + h + body

    blocks = {sid: section(sid, b) for sid, b in sorted({1: s1, 2: s2, 3: s3, 6: s6}.items())}
    def table0(start):
        t, pos = b"", start
        for sid in range(12):
            if sid in blocks:
                t += struct.pack("<HII", sid, len(blocks[sid]), pos)
                pos += len(blocks[sid])
            else:
                t += struct.pack("<HII", sid, 0, 0)
        return t
    sec0 = section(0, table0(0))
    sec0 = section(0, table0(6 + len(sec0) + 1))
    body = sec0 + b"".join(blocks.values())
    head = struct.pack("<I", 6 + len(body))
    return struct.pack("<H", _crc16(head + body)) + head + body


# ------------------------------------------------------------------ printed ECGs, drawn by matplotlib (an independent renderer)
def printout(x, fs, kind="pdf", layout="3x4", dpi=200, rotate=0.0, photo=False):
    """A standard ECG printout of x (12, 10 s) on 1 mm / 5 mm pink grid at 25 mm/s and 10 mm/mV, as PDF or PNG/JPEG."""
    import io as _io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grid = {"3x4": [["I", "AVR", "V1", "V4"], ["II", "AVL", "V2", "V5"], ["III", "AVF", "V3", "V6"], ["II*"]],
            "12x1": [[l] for l in LEADS]}[layout]
    rows = len(grid)
    row_mm = 25 if layout == "3x4" else 15
    w_mm, h_mm = 250, rows * row_mm
    fig = plt.figure(figsize=((w_mm + 40) / 25.4, (h_mm + 40) / 25.4))
    ax = fig.add_axes([20 / (w_mm + 40), 20 / (h_mm + 40), w_mm / (w_mm + 40), h_mm / (h_mm + 40)])
    ax.set_xlim(0, w_mm); ax.set_ylim(0, h_mm); ax.axis("off")
    for i in range(w_mm + 1):
        ax.axvline(i, color="#f4a6a6" if i % 5 else "#e06666", lw=0.2 if i % 5 else 0.5, zorder=0)
    for j in range(h_mm + 1):
        ax.axhline(j, color="#f4a6a6" if j % 5 else "#e06666", lw=0.2 if j % 5 else 0.5, zorder=0)
    n = x.shape[1]
    t = np.arange(n) / fs * 25
    for r, row in enumerate(grid):
        base = h_mm - (r + 0.55) * row_mm
        for c, lead in enumerate(row):
            name = lead.rstrip("*")
            s = x[LEADS.index(name)]
            a, b = (0, n) if len(row) == 1 else (c * n // len(row), (c + 1) * n // len(row))
            ax.plot(t[a:b], base + 10 * np.clip(s[a:b] - np.median(s), -1.2, 1.2), color="black", lw=0.6, zorder=2)
            ax.text(t[a] + 1, base + 7, PRETTY.get(name, name), fontsize=6, zorder=3)
    fig.text(0.02, 0.98, "25 mm/s  10 mm/mV", fontsize=7, va="top")
    buf = _io.BytesIO()
    if kind == "pdf":
        fig.savefig(buf, format="pdf")
        plt.close(fig)
        return buf.getvalue()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    if not (rotate or photo):
        return buf.getvalue()
    from PIL import Image, ImageEnhance, ImageFilter
    im = Image.open(_io.BytesIO(buf.getvalue())).convert("RGB")
    if rotate:
        im = im.rotate(rotate, resample=Image.BICUBIC, fillcolor=(232, 232, 226))
    if photo:
        im = ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(0.8))).enhance(0.85)
    out = _io.BytesIO()
    im.save(out, format="JPEG" if photo else "PNG", quality=70)
    return out.getvalue()
