"""Engine API: validated input in, versioned result out. Used by the HTTP service and embedders.

Two analyses:
  analyze_ecg12(leads, fs, units)   10 s 12-lead ECG -> lead quality, measurements, statements
  analyze_rhythm(signal, fs, units) single-lead strip / Holter -> quality, beats, rhythm, findings
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from cardiotic_engine import __version__
from cardiotic_engine.registry import MODELS_DIR, OnnxRunner, load_manifest, verify

LEADS = ("I", "II", "III", "AVR", "AVL", "AVF", "V1", "V2", "V3", "V4", "V5", "V6")
LIMB_DERIVED = ("III", "AVR", "AVL", "AVF")
UNITS = {"mv": 1.0, "uv": 1e-3, "µv": 1e-3}
MIN_FS = {"ecg12": 200.0, "rhythm": 100.0}
MAX_FS = 2000.0
ECG12_MIN_S, ECG12_MAX_S = 8.0, 60.0
RHYTHM_MIN_S, RHYTHM_MAX_S = 10.0, 48 * 3600.0
MAX_ABS_MV = 20.0  # larger values are a units or gain error, not an ECG


class InputError(ValueError):
    """The request cannot be analysed as given; the message says why."""


class SiteConfigError(ValueError):
    """The per-site operating-point file does not belong to these models or is not signed off."""


@dataclass
class _Loaded:
    manifest: dict
    ecg12: object
    single: object


def _scale(units: str) -> float:
    try:
        return UNITS[units.strip().lower()]
    except (KeyError, AttributeError):
        raise InputError(f"units must be one of mV, uV (got {units!r})") from None


def _check_fs(fs, kind: str) -> float:
    try:
        fs = float(fs)
    except (TypeError, ValueError):
        raise InputError("fs (sampling rate, Hz) must be a number") from None
    if not MIN_FS[kind] <= fs <= MAX_FS:
        raise InputError(f"fs must be between {MIN_FS[kind]:.0f} and {MAX_FS:.0f} Hz for this analysis (got {fs:g})")
    return fs


def _array(values, name: str) -> np.ndarray:
    try:
        x = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError):
        raise InputError(f"{name}: samples must be numbers") from None
    if x.ndim != 1:
        raise InputError(f"{name}: expected a flat list of samples")
    if not np.isfinite(x).all():
        bad = ~np.isfinite(x)
        if bad.mean() > 0.05:
            raise InputError(f"{name}: {bad.mean():.0%} of samples are missing or not finite")
        idx = np.arange(len(x))
        x = np.interp(idx, idx[~bad], x[~bad])
    return x


class Engine:
    def __init__(self, models_dir=MODELS_DIR, site_config=None):
        """site_config: path to a signed-off per-site operating-point file (ecg12/site.py), or None for the
        model's own thresholds. Default: the CARDIOTIC_SITE_CONFIG environment variable, if set."""
        from cardiotic_ml import pipeline
        from cardiotic_ml.ecg12 import analyze as a12

        self.integrity = verify(models_dir)  # raises before any model is loaded if a file was altered
        manifest = load_manifest(models_dir)
        m = manifest["models"]
        run = {role: OnnxRunner(models_dir / m[role]["file"]) for role in m}
        cards = {f"{e['name']}_{e['version']}": e for e in m.values()}
        single = pipeline.Models(run["quality"], run["beats"], run["rhythm"], cards)
        import hashlib
        import json
        import os
        from pathlib import Path

        site_config = site_config or os.environ.get("CARDIOTIC_SITE_CONFIG")
        site, self._site_info = None, None
        if site_config:
            raw = Path(site_config).read_bytes()
            site = json.loads(raw)
        try:
            ecg12 = a12.Models12(net=run["ecg12"], card=m["ecg12"], quality=run["quality"], q_card=m["quality"], site=site)
        except ValueError as e:
            raise SiteConfigError(f"site configuration refused: {e}") from None
        if site:
            self._site_info = {"site_id": site["site_id"], "config_version": site["config_version"], "approved_by": site["approved_by"],
                               "approved_at": site["approved_at"], "sha256": hashlib.sha256(raw).hexdigest(),
                               "statements": sorted(site["statements"])}
        self._m = _Loaded(manifest, ecg12, single)

    # ------------------------------------------------------------------ info
    def info(self) -> dict:
        return {"engine": "cardiotic-engine", "version": __version__,
                "models_version": self._m.manifest["engine_models_version"],
                "intended_use": self._m.manifest["intended_use"],
                "models": {role: {"model": v["model"], "sha256": v["sha256"]} for role, v in self.integrity.items()},
                **({"site_config": self._site_info} if self._site_info else {})}

    def _envelope(self, analysis: str, body: dict, t0: float, notes: list[str]) -> dict:
        body.pop("engine", None)
        return {"analysis": analysis, "engine": self.info(), "input_notes": notes,
                "processing_ms": round(1000 * (time.perf_counter() - t0), 1), "result": body}

    # ------------------------------------------------------------------ 12-lead
    def analyze_ecg12(self, leads: dict, fs, units: str = "mV") -> dict:
        from cardiotic_ml.ecg12.analyze import analyze_12lead

        t0 = time.perf_counter()
        fs = _check_fs(fs, "ecg12")
        k = _scale(units)
        if not isinstance(leads, dict):
            raise InputError("leads must be an object: lead name -> list of samples")
        given = {str(name).strip().upper(): _array(v, str(name)) * k for name, v in leads.items()}
        unknown = sorted(set(given) - set(LEADS))
        if unknown:
            raise InputError(f"unknown lead names {unknown}; expected {list(LEADS)}")
        notes = []
        if set(LIMB_DERIVED) - set(given) and {"I", "II"} <= set(given):
            # 8-lead storage (I, II, V1–V6) is common on ECG carts: derive III, aVR, aVL, aVF (Einthoven/Goldberger)
            i, ii = given["I"], given["II"]
            derived = {"III": ii - i, "AVR": -(i + ii) / 2, "AVL": i - ii / 2, "AVF": ii - i / 2}
            for name in LIMB_DERIVED:
                if name not in given:
                    given[name] = derived[name]
                    notes.append(f"lead {name} derived from I and II")
        missing = [l for l in LEADS if l not in given]
        if missing:
            raise InputError(f"missing leads {missing}")
        lengths = {len(v) for v in given.values()}
        if len(lengths) != 1:
            raise InputError("all leads must have the same number of samples")
        n = lengths.pop()
        dur = n / fs
        if not ECG12_MIN_S <= dur <= ECG12_MAX_S:
            raise InputError(f"12-lead ECG must be {ECG12_MIN_S:g}–{ECG12_MAX_S:g} s long (got {dur:.1f} s)")
        x = np.stack([given[l] for l in LEADS]).astype(np.float32)
        if np.abs(x).max() > MAX_ABS_MV:
            raise InputError(f"amplitudes above {MAX_ABS_MV:g} mV: check units and gain")
        if dur > 10.0:
            x = x[:, : int(10 * fs)]
            notes.append("only the first 10 s were analysed (the models use 10 s ECGs)")
        if fs != 500:
            notes.append(f"sampled at {fs:g} Hz; measurements were validated at 500 Hz")
        return self._envelope("ecg12", analyze_12lead(x, fs, self._m.ecg12), t0, notes)

    # ------------------------------------------------------------------ a file from an ECG machine
    def analyze_file(self, data: bytes, fs=None, units: str | None = None) -> dict:
        """Read an ECG file (CSV, EDF, HL7 aECG, GE MUSE XML, DICOM, SCP-ECG; format detected from the content)
        and analyse it: 12-lead if it has I, II and V1–V6 (the other four limb leads are derived), rhythm if it
        is a single lead. The result carries `source_file` (format, patient fields, time, device as written in the file)."""
        return self.analyze_parsed(self.read_file(data, fs, units))

    def read_file(self, data: bytes, fs=None, units: str | None = None):
        """Parse an ECG file into a ParsedEcg (InputError with the reason if it cannot be read)."""
        from cardiotic_engine.ingest import IngestError, parse

        try:
            return parse(data, fs=fs, units=units)
        except IngestError as e:
            raise InputError(str(e)) from None

    def analyze_parsed(self, ecg) -> dict:
        have = set(ecg.leads)
        if len(have) == 1:
            name = next(iter(have))
            out = self.analyze_rhythm(ecg.leads[name], ecg.fs, "mV", name)
        elif {"I", "II"} <= have and set(LEADS[6:]) <= have:
            out = self.analyze_ecg12({k: v for k, v in ecg.leads.items()}, ecg.fs, "mV")
        else:
            raise InputError(f"the file has leads {sorted(have)}; 12-lead analysis needs I, II and V1–V6 (or all 12), "
                             "rhythm analysis needs a single lead")
        out["input_notes"] = ecg.notes + out["input_notes"]
        out["source_file"] = ecg.info()
        return out

    # ------------------------------------------------------------------ single lead
    def analyze_rhythm(self, signal, fs, units: str = "mV", lead: str | None = None) -> dict:
        from cardiotic_ml import pipeline

        t0 = time.perf_counter()
        fs = _check_fs(fs, "rhythm")
        x = _array(signal, "signal") * _scale(units)
        dur = len(x) / fs
        if not RHYTHM_MIN_S <= dur <= RHYTHM_MAX_S:
            raise InputError(f"recording must be {RHYTHM_MIN_S:g} s to {RHYTHM_MAX_S / 3600:g} h long (got {dur:.1f} s)")
        if np.abs(x).max() > MAX_ABS_MV:
            raise InputError(f"amplitudes above {MAX_ABS_MV:g} mV: check units and gain")
        notes = []
        if lead is None or str(lead).strip().upper() not in ("II", "MLII"):
            notes.append("beat and rhythm models were validated on lead II / MLII; other leads are less reliable")
        if dur > (pipeline.CHUNK_S + 2 * pipeline.MARGIN_S):
            notes.append(f"long recording: analysed in {pipeline.CHUNK_S // 60}-minute sections")
        return self._envelope("rhythm", pipeline.analyze_long(x.astype(np.float32), fs, self._m.single), t0, notes)
