"""CSV / text export: a header row naming the leads, one row per sample.

Sampling rate: a `# fs=500` comment line, a time column (seconds or milliseconds), or the `fs` argument.
Units: `I (uV)` in the header, a `# units=uV` comment line, or the `units` argument; default mV.
"""

from __future__ import annotations

import csv
import io
import re

import numpy as np

from .common import IngestError, finish, norm_lead, unit_factor


def read(data: bytes, fs: float | None = None, units: str | None = None):
    text = data.decode("utf-8-sig", errors="replace")
    comments = dict(re.findall(r"^#\s*(\w+)\s*[=:]\s*([^\s,;]+)", text, flags=re.M))
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if len(lines) < 3:
        raise IngestError("csv: no data rows")
    first = lines[0]
    delim = next((d for d in (",", ";", "\t") if d in first), " " if len(first.split()) > 1 and "(" not in first else ",")
    rows = list(csv.reader(lines, delimiter=delim))
    header = [h.strip() for h in rows[0]]
    cols, per_col_units, time_col = {}, {}, None
    for j, h in enumerate(header):
        name = norm_lead(h)
        if name and name not in cols:
            cols[name] = j
            m = re.search(r"\(([^)]*)\)|\[([^\]]*)\]", h)
            per_col_units[name] = (m.group(1) or m.group(2)) if m else None
        elif re.match(r"(?i)^(time|t|seconds|sec|ms)\b", h):
            time_col = j
    if not cols:
        raise IngestError("csv: the header row names no ECG leads (expected I, II, III, aVR, aVL, aVF, V1–V6)")
    try:
        body = np.array([[float(c) for c in r] for r in rows[1:] if len(r) == len(header)], dtype=np.float64)
    except ValueError:
        raise IngestError("csv: data rows must be numbers (after one header row)") from None
    if len(body) < 3:
        raise IngestError("csv: no data rows")
    notes = []
    if fs is None and "fs" in comments:
        fs = float(comments["fs"])
    if fs is None and time_col is not None:
        dt = float(np.median(np.diff(body[:, time_col])))
        if dt <= 0:
            raise IngestError("csv: the time column does not increase")
        scale = 1e-3 if re.match(r"(?i)^ms", header[time_col]) or body[-1, time_col] > 100 else 1.0
        fs = 1.0 / (dt * scale)
        notes.append(f"sampling rate {fs:g} Hz taken from the time column")
    if fs is None:
        raise IngestError("csv: sampling rate unknown; add a '# fs=500' line, a time column, or pass fs")
    default_unit = units or comments.get("units") or "mV"
    leads = {k: body[:, j] * unit_factor(per_col_units[k] or default_unit) for k, j in cols.items()}
    return finish(fs, leads, "csv", notes=notes)
