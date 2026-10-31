"""DICOM 12-lead ECG waveform (SOP class 1.2.840.10008.5.1.4.1.1.9.1.1). Needs pydicom (`pip install cardiotic-engine[dicom]`)."""

from __future__ import annotations

import io

import numpy as np

from .common import IngestError, finish, norm_lead, unit_factor


def read(data: bytes, fs: float | None = None, units: str | None = None):
    try:
        import pydicom
    except ImportError:
        raise IngestError("dicom: reading DICOM needs pydicom (pip install pydicom)") from None
    try:
        ds = pydicom.dcmread(io.BytesIO(data), force=False)
    except Exception as e:  # pydicom raises many types for damaged files
        raise IngestError(f"dicom: cannot read file ({type(e).__name__})") from None
    seq = getattr(ds, "WaveformSequence", None)
    if not seq:
        raise IngestError("dicom: no waveform data (is this an ECG waveform object?)")
    best = None
    for i, grp in enumerate(seq):  # several multiplex groups: take the longest (rhythm) one
        n = int(grp.NumberOfWaveformSamples)
        if best is None or n > best[0]:
            best = (n, i)
    n, gi = best
    grp = seq[gi]
    arr = ds.waveform_array(gi)  # (samples, channels), channel sensitivity and baseline already applied
    rate = float(grp.SamplingFrequency)
    leads, notes = {}, []
    for ch, cd in zip(range(arr.shape[1]), grp.ChannelDefinitionSequence):
        meaning = cd.ChannelSourceSequence[0].CodeMeaning if "ChannelSourceSequence" in cd else ""
        name = norm_lead(meaning)
        if not name or name in leads:
            continue
        unit = None
        if "ChannelSensitivityUnitsSequence" in cd:
            unit = cd.ChannelSensitivityUnitsSequence[0].CodeValue
        leads[name] = arr[:, ch].astype(np.float64) * unit_factor(unit or units or "uV")
    pat = {}
    if getattr(ds, "PatientID", ""):
        pat["id"] = str(ds.PatientID)
    if getattr(ds, "PatientName", ""):
        pat["name"] = str(ds.PatientName).replace("^", " ").strip()
    if getattr(ds, "PatientSex", "") in ("M", "F"):
        pat["sex"] = str(ds.PatientSex)
    if getattr(ds, "PatientBirthDate", ""):
        b = str(ds.PatientBirthDate)
        pat["birth_date"] = f"{b[:4]}-{b[4:6]}-{b[6:8]}" if len(b) == 8 else b
    rec = None
    d, t = getattr(ds, "AcquisitionDateTime", None) or "", ""
    if len(d) >= 14:
        rec = f"{d[:4]}-{d[4:6]}-{d[6:8]}T{d[8:10]}:{d[10:12]}:{d[12:14]}"
    return finish(fs or rate, leads, "dicom-ecg", patient=pat, recorded_at=rec,
                  device=" ".join(x for x in (str(getattr(ds, "Manufacturer", "")), str(getattr(ds, "ManufacturerModelName", ""))) if x) or None, notes=notes)
