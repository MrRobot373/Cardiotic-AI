"""Live Assist: advisory review flags from bedside-monitor ECG streams (OT / ICU).

A monitor gateway posts each bed's ECG (and, if it has them, the monitor's own SpO2 / blood pressure) to
POST /api/live/ingest with the bed's device token. Every few seconds the last minute of each bed is analysed with
the same engine as recorded ECGs (signal quality, beats, rhythm). Flags are advisory and never replace,
delay or silence the monitor's alarms:

  possible AF            two consecutive 30 s rhythm windows called atrial fibrillation (high confidence)
  ventricular run        three or more ventricular beats in a row
  pause                  no beat for 3 s or more
  slow / fast rate       heart rate < 40 or > 150 bpm for 30 s
While the signal is unusable or noisy (diathermy, movement) analysis pauses and says so instead of flagging.

Silent mode (per bed or for the whole site) runs everything and records the flags, but shows them only to
administrators: the silent-mode study the product plan requires before flags are shown to clinicians.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from collections import deque

import numpy as np

from .db import now

log = logging.getLogger("cardiotic_server.live")
BUFFER_S = 300          # each bed keeps the last 5 minutes
WINDOW_S = 60           # analysed every TICK_S over the last minute
TICK_S = 5
OFFLINE_S = 10          # no data for this long: the bed shows "stream lost", nothing else
FLAG_RULES = {"pause_s": 3.0, "slow_bpm": 40, "fast_bpm": 150, "run_beats": 3, "af_windows": 2, "af_prob": 0.8}


class Bed:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.fs = None
        self.samples: deque = deque()
        self.t_end = 0.0                 # stream time (s) of the newest sample
        self.received_at = 0.0           # wall clock of the last post
        self.vitals: dict = {}
        self.state = {"status": "waiting", "hr": None, "rhythm": None, "quality": None, "updated": None}
        self.flags: list[dict] = []
        self.lock = threading.Lock()
        self.analysed_to = 0.0

    def add(self, fs: float, samples: list[float], vitals: dict | None) -> None:
        with self.lock:
            if self.fs and abs(self.fs - fs) > 1e-6:
                self.samples.clear()
            self.fs = fs
            self.samples.extend(float(v) for v in samples)
            self.t_end += len(samples) / fs
            while len(self.samples) > BUFFER_S * fs:
                self.samples.popleft()
            self.received_at = time.time()
            if vitals:
                self.vitals = {k: vitals[k] for k in ("spo2", "abp_sys", "abp_dia", "hr_monitor") if k in vitals}

    def window(self, seconds: float) -> tuple[np.ndarray, float]:
        with self.lock:
            n = int(min(len(self.samples), seconds * (self.fs or 1)))
            x = np.fromiter((self.samples[i] for i in range(len(self.samples) - n, len(self.samples))), dtype=np.float32, count=n)
            return x, self.t_end - n / (self.fs or 1)


def _token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


class LiveHub(threading.Thread):
    def __init__(self, store, interval: float = TICK_S):
        super().__init__(daemon=True, name="live-assist")
        self.store, self.interval, self._stop_evt = store, interval, threading.Event()
        self.beds: dict[str, Bed] = {}
        self.lock = threading.Lock()
        self.load()

    # ------------------------------------------------------------ configuration (beds and their device tokens)
    def load(self) -> None:
        cfgs = self.store.db.get_setting("live_beds", [])
        with self.lock:
            self.beds = {c["bed"]: self.beds.get(c["bed"]) or Bed(c) for c in cfgs}
            for c in cfgs:
                self.beds[c["bed"]].cfg = c

    def add_bed(self, bed: str, unit: str, label: str = "", mrn: str = "", silent: bool | None = None) -> str:
        bed = bed.strip().upper()
        if not bed or len(bed) > 20 or unit not in ("OT", "ICU", "ER", "WARD"):
            raise ValueError("bed needs an ID (up to 20 characters) and a unit: OT, ICU, ER or WARD")
        token = "lv_" + secrets.token_urlsafe(24)
        cfgs = [c for c in self.store.db.get_setting("live_beds", []) if c["bed"] != bed]
        cfgs.append({"bed": bed, "unit": unit, "label": label[:60], "mrn": mrn.strip()[:40], "silent": silent, "token_sha256": _token_hash(token)})
        self.store.db.set_setting("live_beds", sorted(cfgs, key=lambda c: (c["unit"], c["bed"])))
        self.load()
        return token

    def remove_bed(self, bed: str) -> None:
        cfgs = self.store.db.get_setting("live_beds", [])
        self.store.db.set_setting("live_beds", [c for c in cfgs if c["bed"] != bed])
        self.load()

    def update_bed(self, bed: str, patch: dict) -> None:
        cfgs = self.store.db.get_setting("live_beds", [])
        for c in cfgs:
            if c["bed"] == bed:
                for k in ("label", "mrn", "silent", "unit"):
                    if k in patch:
                        c[k] = patch[k]
        self.store.db.set_setting("live_beds", cfgs)
        self.load()

    def site_silent(self) -> bool:
        return bool(self.store.db.get_setting("live", {}).get("silent", True))  # silent until the site decides otherwise

    def is_silent(self, bed: Bed) -> bool:
        return self.site_silent() if bed.cfg.get("silent") is None else bool(bed.cfg["silent"])

    # ------------------------------------------------------------ ingest
    def ingest(self, token: str, payload: dict) -> dict:
        th = _token_hash(token or "")
        bed = next((b for b in self.beds.values() if secrets.compare_digest(b.cfg["token_sha256"], th)), None)
        if bed is None:
            raise PermissionError("unknown device token")
        try:
            fs = float(payload["fs"])
            samples = payload["samples"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("body needs fs (Hz) and samples (mV)") from None
        if not 100 <= fs <= 1000 or not isinstance(samples, list) or not samples or len(samples) > 60 * fs:
            raise ValueError("fs must be 100-1000 Hz and samples 1 to 60 s of values")
        if not all(isinstance(v, (int, float)) and abs(v) < 20 for v in samples):
            raise ValueError("samples must be numbers in mV")
        units = str(payload.get("units", "mV")).lower()
        if units in ("uv", "µv"):
            samples = [v / 1000 for v in samples]
        bed.add(fs, samples, payload.get("vitals"))
        return {"bed": bed.cfg["bed"], "buffered_s": round(len(bed.samples) / fs, 1)}

    # ------------------------------------------------------------ analysis
    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.wait(self.interval):
            for bed in list(self.beds.values()):
                try:
                    self.analyse(bed)
                except Exception:
                    log.exception("live analysis failed for %s", bed.cfg.get("bed"))

    def analyse(self, bed: Bed) -> None:
        from cardiotic_ml import pipeline

        if bed.fs is None:
            return
        if time.time() - bed.received_at > OFFLINE_S:
            bed.state.update(status="offline", updated=now())
            return
        if bed.t_end - bed.analysed_to < TICK_S * 0.8 and bed.state["status"] != "waiting":
            return
        x, t0 = bed.window(WINDOW_S)
        if len(x) < 15 * bed.fs:
            bed.state.update(status="starting", updated=now())
            return
        res = pipeline.analyze(x, bed.fs, self.store.engine._m.single)
        bed.analysed_to = bed.t_end
        q = [s["quality"] for s in res["quality_segments"][-4:]]  # the last 10 s
        if q.count("unusable") >= 2 or (res["findings"] and res["findings"][0].startswith("Not analysable")):
            bed.state.update(status="paused", quality="unusable", hr=None, rhythm=None, updated=now(), reason="signal unusable (diathermy, movement or lead off): analysis paused")
            return
        if q.count("noisy") >= 3:
            bed.state.update(status="paused", quality="noisy", hr=None, rhythm=None, updated=now(), reason="signal noisy: analysis paused, no flags")
            return
        beats = res["beats"]
        times = np.array([b["time_s"] for b in beats])
        cls = [b["class"] for b in beats]
        recent = times > times[-1] - 15 if len(times) else np.zeros(0, bool)
        hr = float(60 / np.median(np.diff(times[recent]))) if recent.sum() >= 3 else None
        rhythm = res["rhythm_segments"][-1]["rhythm"] if res["rhythm_segments"] else None
        bed.state.update(status="analysing", quality="good" if not q.count("noisy") else "noisy", hr=hr, rhythm=rhythm, updated=now(), reason=None)
        self._flags(bed, res, times, cls, hr, t0)

    def _flags(self, bed: Bed, res: dict, times: np.ndarray, cls: list[str], hr: float | None, t0: float) -> None:
        found = []
        rs = res["rhythm_segments"]
        af = [s for s in rs if s["rhythm"] == "A" and s["probability"] >= FLAG_RULES["af_prob"]]
        if len(af) >= FLAG_RULES["af_windows"] and len(rs) >= 2 and all(s["rhythm"] == "A" for s in rs[-FLAG_RULES["af_windows"]:]):
            found.append(("af", "Possible atrial fibrillation", t0 + af[0]["start_s"]))
        run = 0
        for i, c in enumerate(cls):
            run = run + 1 if c == "V" else 0
            if run == FLAG_RULES["run_beats"]:
                found.append(("vrun", f"Ventricular run ({run}+ beats)", t0 + float(times[i])))
        if len(times) > 1:
            gaps = np.diff(times)
            k = int(np.argmax(gaps))
            if gaps[k] >= FLAG_RULES["pause_s"]:
                found.append(("pause", f"Pause {gaps[k]:.1f} s", t0 + float(times[k])))
        if hr is not None and hr < FLAG_RULES["slow_bpm"]:
            found.append(("slow", f"Slow rate {hr:.0f} bpm", t0 + float(times[-1])))
        if hr is not None and hr > FLAG_RULES["fast_bpm"]:
            found.append(("fast", f"Fast rate {hr:.0f} bpm", t0 + float(times[-1])))
        for kind, text, at in found:
            open_same = next((f for f in bed.flags if f["kind"] == kind and not f["acknowledged"] and f["last_seen_stream_s"] > at - 120), None)
            if open_same:  # the same ongoing finding: keep one flag, extend it
                open_same["last_seen_stream_s"] = max(open_same["last_seen_stream_s"], at)
                open_same["last_seen"] = now()
                continue
            flag = {"id": secrets.token_hex(6), "kind": kind, "text": text, "raised": now(), "last_seen": now(), "stream_s": round(at, 1),
                    "last_seen_stream_s": at, "acknowledged": None, "silent": self.is_silent(bed)}
            bed.flags.append(flag)
            bed.flags = bed.flags[-50:]
            self.store.db.audit("Live Assist", "Advisory flag" + (" (silent mode)" if flag["silent"] else ""), f"{bed.cfg['bed']}: {text}")

    # ------------------------------------------------------------ what the board shows
    def board(self, user: dict) -> dict:
        see_silent = user["role"] == "admin"
        beds = []
        for b in self.beds.values():
            offline = b.fs is None or time.time() - b.received_at > OFFLINE_S
            silent = self.is_silent(b)
            flags = [f for f in b.flags if not f["acknowledged"] and (see_silent or not f["silent"])]
            beds.append({"bed": b.cfg["bed"], "unit": b.cfg["unit"], "label": b.cfg.get("label", ""), "mrn": b.cfg.get("mrn", ""), "silent": silent,
                         "status": "offline" if offline and b.fs is not None else b.state["status"] if not offline else "waiting",
                         "offline_for_s": round(time.time() - b.received_at) if b.fs is not None and offline else None,
                         "hr": b.state.get("hr") if not offline else None, "rhythm": b.state.get("rhythm") if not offline else None,
                         "quality": b.state.get("quality"), "reason": b.state.get("reason"),
                         "vitals": b.vitals if not offline else {}, "flags": flags})
        return {"silent_site": self.site_silent(), "beds": beds, "rules": FLAG_RULES}

    def trace(self, bed_id: str, seconds: float = 10) -> dict:
        b = self.beds.get(bed_id)
        if b is None:
            raise KeyError(bed_id)
        if b.fs is None or time.time() - b.received_at > OFFLINE_S:
            return {"bed": bed_id, "fs": 0, "samples": [], "t_end": b.t_end}
        x, t0 = b.window(seconds)
        step = max(1, int(round(b.fs / 125)))  # 125 Hz is plenty for a 10 s trace on screen
        return {"bed": bed_id, "fs": b.fs / step, "samples": [round(float(v), 3) for v in x[::step]], "t_end": b.t_end}

    def acknowledge(self, user: dict, bed_id: str, flag_id: str) -> None:
        b = self.beds.get(bed_id)
        f = next((f for f in (b.flags if b else []) if f["id"] == flag_id), None)
        if f is None:
            raise KeyError(flag_id)
        f["acknowledged"] = {"by": user["name"], "at": now()}
        self.store.db.audit(user["name"], "Reviewed advisory flag", f"{bed_id}: {f['text']}")
