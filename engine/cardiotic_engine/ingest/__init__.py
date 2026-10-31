"""Read an ECG file (bytes) into a ParsedEcg: format is detected from the content, not the file name.

Formats: CSV, EDF/EDF+, HL7 aECG (FDA XML, Philips SierraECG), GE MUSE XML, DICOM 12-lead ECG waveform,
SCP-ECG (uncompressed or difference coded). Everything else is refused with the reason, never guessed.

Not supported yet (clear errors): Huffman-compressed SCP-ECG, Philips PageWriter XML (XLI compression),
PDF / paper-ECG images (needs the ECG image digitiser).
"""

from __future__ import annotations

import re

from . import csv_reader, dicom_waveform, edf, hl7_aecg, muse_xml, scp_ecg
from .common import LEADS, IngestError, ParsedEcg

__all__ = ["parse", "detect", "ParsedEcg", "IngestError", "LEADS"]


def detect(data: bytes) -> str:
    if len(data) < 16:
        raise IngestError("the file is empty or too small to be an ECG")
    if data[128:132] == b"DICM":
        return "dicom"
    if data[:8] == b"0       ":
        return "edf"
    if data[:5] == b"%PDF-":
        raise IngestError("PDF files are not read yet: paper-ECG images and PDFs need the ECG image digitiser; export the ECG as DICOM, HL7 aECG or MUSE XML")
    if scp_ecg.looks_like_scp(data):
        return "scp"
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<"):
        root = re.search(rb"<(?!\?|!)(?:[\w.-]+:)?([\w.-]+)", head)
        tag = (root.group(1).decode() if root else "").lower()
        if tag == "annotatedecg" or b"AnnotatedECG" in head:
            return "aecg"
        if tag == "restingecg":
            return "muse"
        if tag == "restingecgdata":
            raise IngestError("Philips PageWriter XML (restingecgdata, XLI-compressed) is not supported yet; export from the cart as HL7 aECG (SierraECG) or DICOM")
        raise IngestError(f"unknown XML ECG format (root element <{tag}>)")
    if head[:2] == b"\x89P" or head[:3] == b"\xff\xd8\xff":
        raise IngestError("images are not read yet: paper-ECG images need the ECG image digitiser")
    try:
        data[:2048].decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestError("unknown binary file format") from None
    return "csv"


_READERS = {"dicom": dicom_waveform.read, "edf": edf.read, "scp": scp_ecg.read, "aecg": hl7_aecg.read, "muse": muse_xml.read, "csv": csv_reader.read}


def parse(data: bytes, fs: float | None = None, units: str | None = None) -> ParsedEcg:
    """`fs` / `units` only matter for files that do not state them (CSV) and override what the file says."""
    return _READERS[detect(data)](data, fs=fs, units=units)
