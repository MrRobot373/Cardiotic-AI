"""What every ECG file reader returns, and the helpers they share."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

LEADS = ("I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6")
_UNIT_TO_MV = {"mv": 1.0, "uv": 1e-3, "µv": 1e-3, "μv": 1e-3, "microvolts": 1e-3, "microvolt": 1e-3, "millivolts": 1.0,
               "millivolt": 1.0, "nv": 1e-6, "v": 1e3, "volts": 1e3}


class IngestError(ValueError):
    """The file cannot be read as an ECG; the message says what is wrong or not supported."""


@dataclass
class ParsedEcg:
    fs: float
    leads: dict[str, np.ndarray]              # LEADS name -> samples in mV
    format: str
    patient: dict = field(default_factory=dict)  # id, name, sex ("M"/"F"), birth_date (ISO) — whatever the file carries
    recorded_at: str | None = None            # ISO 8601 as written in the file (no time zone is guessed)
    device: str | None = None
    notes: list[str] = field(default_factory=list)
    layout: str = "recording"                 # "print-3x4" etc. when read back from a printout (digitise.py)
    windows: dict | None = None               # printouts: the sample range each lead covers

    def info(self) -> dict:
        return {"layout": self.layout, "format": self.format, "patient": self.patient, "recorded_at": self.recorded_at, "device": self.device,
                "fs": self.fs, "leads": list(self.leads), "seconds": round(len(next(iter(self.leads.values()))) / self.fs, 2)}


def norm_lead(label: str) -> str | None:
    """'ECG Lead aVR', 'MDC_ECG_LEAD_V1', 'I (mV)', 'lead_II' -> LEADS name, or None."""
    s = re.sub(r"\(.*?\)|\[.*?\]", "", str(label)).upper()
    s = re.sub(r"MDC_ECG_LEAD_|ECG|EKG|LEAD|[\s_\-.:]", "", s)
    return s if s in LEADS else None


def unit_factor(unit: str | None, default: str = "mV") -> float:
    """Multiplier from the stated unit to mV."""
    u = (unit or default).strip().lower().replace(" ", "")
    if u not in _UNIT_TO_MV:
        raise IngestError(f"unknown amplitude unit {unit!r}")
    return _UNIT_TO_MV[u]


def finish(fs: float, leads: dict[str, np.ndarray], fmt: str, **kw) -> ParsedEcg:
    """Common checks: at least one recognised lead, equal lengths, finite values."""
    if not leads:
        raise IngestError(f"{fmt}: no recognisable ECG leads found")
    n = {len(v) for v in leads.values()}
    if len(n) != 1:
        m = min(n)
        kw.setdefault("notes", []).append(f"leads have different lengths; cut to the shortest ({m} samples)")
        leads = {k: v[:m] for k, v in leads.items()}
    if not np.isfinite(fs) or fs <= 0:
        raise IngestError(f"{fmt}: invalid sampling rate {fs!r}")
    out = {}
    for k, v in leads.items():
        v = np.asarray(v, dtype=np.float64)
        if not np.isfinite(v).all():
            raise IngestError(f"{fmt}: lead {k} contains missing or non-finite samples")
        out[k] = v
    return ParsedEcg(float(fs), {k: out[k] for k in LEADS if k in out}, fmt, **kw)
