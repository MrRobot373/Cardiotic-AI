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
