"""EDF / EDF+ (European Data Format)."""

from __future__ import annotations

import numpy as np
from scipy import signal as sps

from .common import IngestError, finish, norm_lead, unit_factor


def read(data: bytes, fs: float | None = None, units: str | None = None):
    if len(data) < 256 or data[:8] != b"0       ":
        raise IngestError("edf: not an EDF file")
    try:
        ns = int(data[252:256])
        nrec = int(data[236:244])
        dur = float(data[244:252])
        hdr_bytes = int(data[184:192])
    except ValueError:
        raise IngestError("edf: damaged header") from None
    if ns < 1 or dur <= 0:
        raise IngestError("edf: no signals or no record duration")
    off = 256

    def field(width):
        nonlocal off
        out = [data[off + i * width: off + (i + 1) * width].decode("ascii", "replace").strip() for i in range(ns)]
        off += ns * width
        return out

    label, _trans, dim, pmin, pmax, dmin, dmax, _pre, nsamp, _res = (field(w) for w in (16, 80, 8, 8, 8, 8, 8, 80, 8, 32))
    nsamp = [int(x) for x in nsamp]
    per_rec = sum(nsamp)
    if nrec < 0:  # recording still open: count what is there
        nrec = (len(data) - hdr_bytes) // (2 * per_rec)
    if (len(data) - hdr_bytes) // 2 < nrec * per_rec:
        raise IngestError("edf: file is shorter than its header says")
    raw = np.frombuffer(data, dtype="<i2", count=nrec * per_rec, offset=hdr_bytes)
    raw = raw.reshape(nrec, per_rec)
    leads, rates, start = {}, {}, 0
    for i in range(ns):
        sig = raw[:, start:start + nsamp[i]].reshape(-1)
        start += nsamp[i]
        name = norm_lead(label[i])
        if not name or name in leads:
            continue
        d0, d1, p0, p1 = float(dmin[i]), float(dmax[i]), float(pmin[i]), float(pmax[i])
        if d1 == d0:
            raise IngestError(f"edf: signal {label[i]!r} has equal digital min and max")
        phys = (sig.astype(np.float64) - d0) * (p1 - p0) / (d1 - d0) + p0
        leads[name] = phys * unit_factor(dim[i] or units or "mV")
        rates[name] = nsamp[i] / dur
    notes = []
    if leads and len(set(rates.values())) > 1:
        top = max(rates.values())
        for k, r in rates.items():
            if r != top:
                leads[k] = sps.resample(leads[k], int(round(len(leads[k]) * top / r)))
        notes.append(f"leads had different sampling rates; all resampled to {top:g} Hz")
    if not leads:
        raise IngestError("edf: no ECG leads among the signals")
    return finish(next(iter(rates.values())) if len(set(rates.values())) == 1 else max(rates.values()), leads, "edf", notes=notes,
                  patient={"id": data[8:88].decode("ascii", "replace").split(" ")[0] if data[8:88].strip() else None})
