"""The ECG report as a PDF (standard library only): A4 landscape, vector ECG on a 1 mm / 5 mm grid at
25 mm/s and 10 mm/mV, measurements, interpretation, comment, signature and software versions.

This is the document the HIS receives (HL7 OBX ED / FHIR presentedForm) and the one users download.
Text uses the PDF base-14 Helvetica fonts (WinAnsi); characters outside Latin-1 print as '?'.
"""

from __future__ import annotations

import base64
import zlib

import numpy as np

MM = 72 / 25.4                      # points per millimetre
W, H = 297 * MM, 210 * MM           # A4 landscape
LEADS = ("I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6")
SHOW = {"AVR": "aVR", "AVL": "aVL", "AVF": "aVF"}
LAYOUT = [["I", "AVR", "V1", "V4"], ["II", "AVL", "V2", "V5"], ["III", "AVF", "V3", "V6"]]


def _txt(s) -> str:
    s = str(s if s is not None else "").replace("—", "-").replace("–", "-").replace("·", "\xb7").replace("’", "'")
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Page:
    def __init__(self):
        self.ops: list[str] = []

    def text(self, x, y, s, size=9, bold=False, gray=0.0):
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {gray:.2f} g {x:.2f} {y:.2f} Td ({_txt(s)}) Tj ET")

    def line(self, x1, y1, x2, y2, w=0.5, rgb=(0, 0, 0)):
        self.ops.append(f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} RG {w:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x, y, w, h, stroke=(0.8, 0.8, 0.8), lw=0.5):
        self.ops.append(f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG {lw:.2f} w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    def polyline(self, pts, w=0.6, rgb=(0, 0, 0)):
        if len(pts) < 2:
            return
        path = f"{pts[0][0]:.2f} {pts[0][1]:.2f} m " + " ".join(f"{x:.2f} {y:.2f} l" for x, y in pts[1:])
        self.ops.append(f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} RG {w:.2f} w 1 j 1 J {path} S")

    def grid(self, x0, y0, w_mm, h_mm):
        pink, dark = (0.98, 0.80, 0.80), (0.93, 0.55, 0.55)
        for i in range(int(w_mm) + 1):
            x = x0 + i * MM
            self.line(x, y0, x, y0 + h_mm * MM, 0.5 if i % 5 == 0 else 0.15, dark if i % 5 == 0 else pink)
        for j in range(int(h_mm) + 1):
            y = y0 + j * MM
            self.line(x0, y, x0 + w_mm * MM, y, 0.5 if j % 5 == 0 else 0.15, dark if j % 5 == 0 else pink)

    def stream(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1")


def _decode(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype="<i2").astype(np.float64) / 1000.0  # µV -> mV


def build(pages: list[Page], title: str = "ECG report") -> bytes:
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1 + 2 * len(pages)  # reserved after the page objects
    kids = []
    for p in pages:
        data = zlib.compress(p.stream())
        content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {W:.2f} {H:.2f}] /Contents {content} 0 R "
                        f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> >>".encode()))
    assert add(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()) == pages_id
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    info = add(f"<< /Title ({_txt(title)}) /Producer (Cardiotic AI) >>".encode())
    out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def ecg_report(rep: dict, leads_b64: dict[str, str], fs: float, draft: bool) -> bytes:
    """rep: export.report_content(); leads_b64: the stored display leads (int16 µV, fs Hz)."""
    pg = Page()
    m, p = rep["measurements"], rep["patient"]
    left, top = 12 * MM, H - 12 * MM
    # header
    pg.text(left, top - 4, rep["site"], 14, bold=True)
    pg.text(left, top - 16, "12-lead ECG report \xb7 Cardiotic AI assisted", 8, gray=0.4)
    pg.text(W - 92 * MM, top - 4, "DRAFT - NOT SIGNED" if draft else "FINAL REPORT", 11, bold=True, gray=0.6 if draft else 0.0)
    pg.text(W - 92 * MM, top - 16, f"Report {rep['id']}", 8, gray=0.4)
    pg.line(left, top - 21, W - left, top - 21, 0.5, (0.8, 0.8, 0.8))
    sex = {"M": "Male", "F": "Female"}.get(p["sex"], "")
    cols = [("Patient", p["name"], f"MRN {p['mrn']}" + (f" \xb7 born {p['birth_date']}" if p["birth_date"] else "") + (f" \xb7 {sex}" if sex else "")),
            ("Recorded", rep["recorded_at"].replace("T", " "), " \xb7 ".join(x for x in (rep.get("location"), rep.get("device")) if x)),
            ("Ordered by", rep.get("ordered_by") or "-", "25 mm/s \xb7 10 mm/mV \xb7 0.05-150 Hz")]
    for i, (k, v, sub) in enumerate(cols):
        x = left + i * 92 * MM
        pg.text(x, top - 30, k, 7, gray=0.45)
        pg.text(x, top - 40, v, 10, bold=True)
        pg.text(x, top - 50, sub, 7.5, gray=0.3)
    # measurements
    meas = [("Rate", m.get("heart_rate_bpm"), "bpm"), ("PR", m.get("pr_ms"), "ms"), ("QRS", m.get("qrs_ms"), "ms"),
            ("QT", m.get("qt_ms"), "ms"), ("QTc (Bazett)", m.get("qtc_bazett_ms"), "ms"), ("QRS axis", m.get("qrs_axis_deg"), "deg")]
    bw = (W - 2 * left) / len(meas)
    for i, (k, v, u) in enumerate(meas):
        x = left + i * bw
        pg.rect(x + 1, top - 78, bw - 2, 20)
        pg.text(x + 5, top - 66, k + (" (edited)" if any(e.startswith(("qt", "qrs", "pr")) and k.lower().startswith(e[:2]) for e in rep.get("edited", [])) else ""), 6.5, gray=0.45)
        pg.text(x + 5, top - 75, "-" if v is None else f"{round(v):d} {u}", 9.5, bold=True)
    # ECG: 3 rows x 4 columns of 2.5 s, then a 10 s lead II rhythm strip
    sig = {k: _decode(v) for k, v in leads_b64.items()}
    gx, gw_mm, row_mm = left, 250, 25
    gy = top - 84 - 4 * row_mm * MM
    pg.grid(gx, gy, gw_mm, 4 * row_mm)
    n_col = int(round(2.5 * fs))

    def trace(x0, ybase, s):
        t = np.arange(len(s)) / fs
        step = max(1, len(s) // 600)  # ~0.4 mm resolution keeps the file small
        pg.polyline([(x0 + 25 * ti * MM, ybase + 10 * vi * MM) for ti, vi in zip(t[::step], s[::step])], 0.55)

    for r, row in enumerate(LAYOUT):
        ybase = gy + (4 - r - 0.5) * row_mm * MM
        for c, ld in enumerate(row):
            s = sig.get(ld)
            if s is None:
                continue
            seg = s[c * n_col:(c + 1) * n_col]
            x0 = gx + c * 62.5 * MM
            trace(x0, ybase, np.clip(seg - np.median(s), -1.2, 1.2))
            pg.text(x0 + 2, ybase + 8 * MM, SHOW.get(ld, ld), 7, bold=True)
            if c:
                pg.line(x0, ybase - 3 * MM, x0, ybase + 3 * MM, 0.6)
    if "II" in sig:
        ybase = gy + 0.5 * row_mm * MM
        trace(gx, ybase, np.clip(sig["II"][: int(10 * fs)] - np.median(sig["II"]), -1.2, 1.2))
        pg.text(gx + 2, ybase + 8 * MM, "II (rhythm)", 7, bold=True)
    # calibration pulse (1 mV)
    cx = gx + gw_mm * MM + 3 * MM
    pg.polyline([(cx, gy + 2 * MM), (cx + 1 * MM, gy + 2 * MM), (cx + 1 * MM, gy + 12 * MM), (cx + 6 * MM, gy + 12 * MM), (cx + 6 * MM, gy + 2 * MM), (cx + 7 * MM, gy + 2 * MM)], 0.6)
    # interpretation, comment, signature
    y = gy - 12
    pg.text(left, y, "INTERPRETATION", 7, bold=True, gray=0.45)
    y -= 11
    lines = [f"{i + 1}. {s['text']}" for i, s in enumerate(rep["statements"])] or ["No abnormality stated."]
    for ln in lines[:8]:
        pg.text(left + 2, y, ln, 9, bold=True)
        y -= 10.5
    if rep.get("note"):
        pg.text(left, y - 2, "COMMENT", 7, bold=True, gray=0.45)
        pg.text(left + 2, y - 12, rep["note"][:150], 8.5)
    sx = W - left - 80 * MM
    pg.rect(sx, gy - 52, 80 * MM, 44)
    pg.text(sx + 6, gy - 20, "Awaiting signature" if draft else "Electronically signed by", 7, gray=0.45)
    pg.text(sx + 6, gy - 32, "-" if draft else rep["signed_by"], 10, bold=True)
    pg.text(sx + 6, gy - 43, "Not valid until signed by a cardiologist" if draft else str(rep["signed_at"]).replace("T", " ")[:19], 7.5)
    pg.line(left, 14 * MM, W - left, 14 * MM, 0.4, (0.8, 0.8, 0.8))
    pg.text(left, 10 * MM, f"Pre-read by {rep['software']}; interpretation confirmed by the signing physician.", 6.5, gray=0.45)
    if draft:
        pg.ops.append("q 0.92 g BT /F2 90 Tf 0.866 0.5 -0.5 0.866 260 150 Tm (DRAFT) Tj ET Q")
    return build([pg], f"ECG report {rep['id']}")
