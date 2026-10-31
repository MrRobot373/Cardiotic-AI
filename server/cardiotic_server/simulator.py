"""A monitor gateway for testing and training: streams a real recording to Live Assist in real time
(or faster), exactly as a gateway connected to a bedside monitor does.

    cardiotic-server live-simulator --url https://cardiotic.local --token lv_... --file holter.edf [--speed 1] [--vitals]
"""

from __future__ import annotations

import json
import time
import urllib.request

import numpy as np


def stream(url: str, token: str, signal: np.ndarray, fs: float, speed: float = 1.0, chunk_s: float = 1.0, vitals: bool = False,
           loop: bool = True, stop=None) -> None:
    n = int(chunk_s * fs)
    pos, t_start, sent = 0, time.time(), 0.0
    rng = np.random.default_rng(0)
    while stop is None or not stop.is_set():
        if pos + n > len(signal):
            if not loop:
                return
            pos = 0
        payload = {"fs": fs, "units": "mV", "samples": [round(float(v), 4) for v in signal[pos:pos + n]]}
        if vitals:  # an illustrative SpO2 / blood pressure stream, as a monitor would forward it
            payload["vitals"] = {"spo2": int(rng.integers(95, 100)), "abp_sys": int(rng.integers(110, 130)), "abp_dia": int(rng.integers(65, 80))}
        req = urllib.request.Request(url.rstrip("/") + "/api/live/ingest", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "X-Device-Token": token}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        pos += n
        sent += chunk_s
        wait = t_start + sent / speed - time.time()
        if wait > 0:
            time.sleep(wait)
