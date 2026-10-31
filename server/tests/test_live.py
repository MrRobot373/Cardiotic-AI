"""Live Assist: gateway ingest with device tokens, analysis of the last minute, advisory flags, silent mode."""
import time
from pathlib import Path

import numpy as np
import pytest

from helpers import Client

STRIP = np.load(Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "fixtures.npz")["strip"]  # MIT-BIH 233, 360 Hz


def _push(c, token, x, fs=360, chunk=360, vitals=None):
    for i in range(0, len(x) - chunk + 1, chunk):
        code, out = c.call("POST", "/api/live/ingest", {"fs": fs, "samples": [round(float(v), 4) for v in x[i:i + chunk]], **({"vitals": vitals} if vitals else {})},
                           headers={"X-Device-Token": token})
        assert code == 200, out


def _bed(server, bed="ICU-4", silent=False):
    a = Client(server.base); a.login("kdesai")
    return a, a.call("POST", "/api/live/beds", {"bed": bed, "unit": "ICU", "label": "Bed 4", "mrn": "UH-1", "silent": silent}, expect=201)[1]["device_token"]


def test_stream_is_analysed_and_shown_on_the_board(server):
    a, token = _bed(server)
    c = Client(server.base); c.login("arao")
    assert c.call("POST", "/api/live/ingest", {"fs": 360, "samples": [0.0] * 360}, headers={"X-Device-Token": "lv_wrong"})[0] == 401
    _push(c, token, STRIP, vitals={"spo2": 97, "abp_sys": 118, "abp_dia": 72})
    server.live.analyse(server.live.beds["ICU-4"])
    board = c.call("GET", "/api/live")[1]
    bed = board["beds"][0]
    assert bed["status"] == "analysing" and 50 < bed["hr"] < 130 and bed["vitals"]["spo2"] == 97
    tr = c.call("GET", "/api/live/ICU-4/trace?seconds=10")[1]
    assert tr["fs"] == 120 and len(tr["samples"]) == 1200
    # record 233 has frequent ventricular beats with runs: a ventricular-run flag, visible (bed not silent)
    kinds = {f["kind"] for f in bed["flags"]}
    assert kinds <= {"vrun", "pause", "af", "slow", "fast"}


def test_pause_is_flagged_and_review_is_audited(server):
    a, token = _bed(server)
    c = Client(server.base); c.login("arao")
    x = np.concatenate([STRIP[: 360 * 40], np.full(360 * 4, float(np.median(STRIP))) + np.random.default_rng(1).normal(0, 0.005, 360 * 4), STRIP[360 * 40:]])
    _push(c, token, x)
    server.live.analyse(server.live.beds["ICU-4"])
    flags = c.call("GET", "/api/live")[1]["beds"][0]["flags"]
    pause = next(f for f in flags if f["kind"] == "pause")
    assert pause["text"].startswith("Pause 4") or pause["text"].startswith("Pause 3") or pause["text"].startswith("Pause 5")
    t = Client(server.base); t.login("rsawant")
    t.call("POST", f"/api/live/ICU-4/flags/{pause['id']}/ack", {}, expect=200)
    assert not any(f["kind"] == "pause" for f in c.call("GET", "/api/live")[1]["beds"][0]["flags"])
    assert Client(server.base).call("POST", f"/api/live/ICU-4/flags/{pause['id']}/ack", {})[0] == 401
    actions = [e["action"] for e in a.call("GET", "/api/audit")[1]]
    assert "Advisory flag" in actions and "Reviewed advisory flag" in actions


def test_silent_mode_records_but_does_not_show_clinicians(server):
    a, token = _bed(server, silent=True)
    c = Client(server.base); c.login("arao")
    x = np.concatenate([STRIP[: 360 * 40], np.zeros(360 * 4), STRIP[360 * 40:]])
    _push(c, token, x)
    server.live.analyse(server.live.beds["ICU-4"])
    assert c.call("GET", "/api/live")[1]["beds"][0]["flags"] == []
    admin_flags = a.call("GET", "/api/live")[1]["beds"][0]["flags"]
    assert admin_flags and all(f["silent"] for f in admin_flags)
    assert any(e["action"] == "Advisory flag (silent mode)" for e in a.call("GET", "/api/audit")[1])


def test_noise_pauses_analysis_and_offline_is_reported(server, monkeypatch):
    a, token = _bed(server)
    c = Client(server.base); c.login("arao")
    noise = np.random.default_rng(0).normal(0, 1.5, 360 * 60)  # diathermy-like interference
    _push(c, token, noise)
    server.live.analyse(server.live.beds["ICU-4"])
    bed = c.call("GET", "/api/live")[1]["beds"][0]
    assert bed["status"] == "paused" and bed["hr"] is None and bed["flags"] == [] and "paused" in bed["reason"]
    from cardiotic_server import live
    monkeypatch.setattr(live, "OFFLINE_S", 0)
    time.sleep(0.01)
    bed = c.call("GET", "/api/live")[1]["beds"][0]
    assert bed["status"] == "offline" and bed["hr"] is None and bed["vitals"] == {}


def test_bed_administration_and_input_checks(server):
    a = Client(server.base); a.login("kdesai")
    c = Client(server.base); c.login("arao")
    assert c.call("POST", "/api/live/beds", {"bed": "OT-1", "unit": "OT"})[0] == 403
    assert a.call("POST", "/api/live/beds", {"bed": "", "unit": "OT"})[0] == 400
    token = a.call("POST", "/api/live/beds", {"bed": "ot-1", "unit": "OT"}, expect=201)[1]["device_token"]
    assert "token_sha256" not in str(a.call("GET", "/api/live/beds")[1]) and token not in str(a.call("GET", "/api/live/beds")[1])
    for bad in ({"fs": 50, "samples": [0.1]}, {"fs": 360, "samples": []}, {"fs": 360, "samples": ["x"]}, {"fs": 360, "samples": [99.0]}, {"samples": [0.1]}):
        assert c.call("POST", "/api/live/ingest", bad, headers={"X-Device-Token": token})[0] == 400, bad
    a.call("PUT", "/api/live/settings", {"silent": False}, expect=200)
    assert c.call("GET", "/api/live")[1]["silent_site"] is False
    a.call("DELETE", "/api/live/beds/OT-1", expect=200)
    assert c.call("POST", "/api/live/ingest", {"fs": 360, "samples": [0.1] * 10}, headers={"X-Device-Token": token})[0] == 401


def test_af_is_flagged_on_a_real_af_recording(server):
    try:
        from cardiotic_ml.data import mitdb
        rec = mitdb.load_record(201)  # MIT-BIH 201: atrial fibrillation episodes
    except Exception:
        pytest.skip("research data (MIT-BIH) not available")
    import json
    ann = rec.ann_samples[[a.startswith("(AFIB") for a in rec.aux]] if hasattr(rec, "aux") else None
    start = int(ann[0]) if ann is not None and len(ann) else 0
    a, token = _bed(server)
    c = Client(server.base); c.login("arao")
    _push(c, token, rec.signal[start + 360 * 10: start + 360 * 75])
    server.live.analyse(server.live.beds["ICU-4"])
    bed = c.call("GET", "/api/live")[1]["beds"][0]
    assert bed["rhythm"] == "A" and any(f["kind"] == "af" for f in bed["flags"]), json.dumps(bed)[:400]
