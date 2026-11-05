"""The standalone engine service for equipment makers (/v1): every route, limits and errors."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest
import ingest_writers as w

from cardiotic_engine import server as srv
from cardiotic_engine.api import LEADS, Engine

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def base():
    httpd = srv.serve("127.0.0.1", 0, Engine())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(base, method, path, data=None, headers=None):
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture(scope="module")
def ecg():
    return np.load(FIX / "fixtures.npz")["ecg12"]


def test_models_and_health(base):
    code, out = call(base, "GET", "/v1/models")
    assert code == 200 and out["engine"] == "cardiotic-engine" and set(out["models"]) >= {"quality", "beats", "rhythm", "ecg12"}
    assert all(len(v["sha256"]) == 64 for v in out["models"].values())
    assert call(base, "GET", "/v1/health")[1] == {"status": "ok", "models_verified": True}
    assert call(base, "GET", "/v1/nothing")[0] == 404


def test_file_route_reads_a_vendor_file_and_honours_headers(base, ecg):
    code, out = call(base, "POST", "/v1/file", w.dicom_file(ecg, 500))
    assert code == 200 and out["analysis"] == "ecg12" and out["result"]["statements"]
    csv = w.csv_file(ecg, 500, comment=False)  # no stated rate: the caller says it
    assert call(base, "POST", "/v1/file", csv)[0] == 400
    code, out = call(base, "POST", "/v1/file", csv, {"X-Fs": "500", "X-Units": "mV"})
    assert code == 200 and out["analysis"] == "ecg12"
    assert call(base, "POST", "/v1/file", b"this is not an ECG file")[0] == 400


def test_rhythm_route_and_input_errors(base, ecg):
    strip = np.tile(ecg[1], 8)
    code, out = call(base, "POST", "/v1/rhythm", json.dumps({"fs": 500, "lead": "II", "signal": strip.tolist()}).encode())
    assert code == 200 and "findings" in out["result"]
    assert call(base, "POST", "/v1/rhythm", json.dumps({"fs": 500, "signal": "abc"}).encode())[0] == 400
    assert call(base, "POST", "/v1/ecg12", b"[1, 2]")[0] == 400  # not an object
    assert call(base, "POST", "/v1/ecg12", b"not json")[0] == 400
    assert call(base, "POST", "/v1/ecg12", json.dumps({"fs": 500, "leads": {l: [0.0] * 5000 for l in LEADS[:3]}}).encode())[0] == 400


def test_limits_and_methods(base, monkeypatch):
    assert call(base, "POST", "/v1/ecg12")[0] == 400  # no body
    assert call(base, "POST", "/v1/unknown", b"{}")[0] == 404
    monkeypatch.setattr(srv, "MAX_BODY", 10)
    assert call(base, "POST", "/v1/file", b"x" * 11)[0] == 413
    for m in ("PUT", "DELETE", "PATCH"):
        assert call(base, m, "/v1/ecg12", b"{}")[0] == 405


def test_unexpected_failure_does_not_leak_internals(base, monkeypatch, ecg):
    monkeypatch.setattr(Engine, "analyze_file", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret internal path /srv/x")))
    code, out = call(base, "POST", "/v1/file", w.dicom_file(ecg, 500))
    assert code == 500 and "secret" not in json.dumps(out)


# ------------------------------------------------------------------ AF operating point
def test_af_mode_changes_only_how_probabilities_become_a_call(monkeypatch, ecg):
    import cardiotic_ml.pipeline as pl
    eng = Engine()
    assert eng.info()["af_mode"] == "balanced" and sorted(eng.af_modes()) == ["balanced", "screening"]
    thr = eng.af_modes()["screening"]["threshold"]
    T = eng._m.manifest["models"]["rhythm"].get("temperature", 1.0)

    real = pl._batched

    def fake(probs):  # rhythm logits that the pipeline's softmax(logits / T) turns back into `probs`; the other models run for real
        monkeypatch.setattr(pl, "_batched", lambda model, *a: np.tile(T * np.log(np.array(probs)), (len(a[0]), 1)) if model is eng._m.single.rhythm else real(model, *a))

    strip = np.tile(ecg[1], 8)
    call = lambda: {s["rhythm"] for s in eng.analyze_rhythm(strip.tolist(), 500, "mV", "II")["result"]["rhythm_segments"]}  # noqa: E731
    fake([0.70, thr + 0.05, 0.25 - thr, 0.0001 + 0.0])  # N most probable, AF a little above the screening threshold
    assert call() == {"N"}
    eng.set_af_mode("screening")
    assert call() == {"A"} and eng.info()["af_mode"] == "screening"
    fake([0.90, thr - 0.05, 0.15 - thr + 0.05 + 0.0, 0.0001])  # AF below the threshold: not called in either mode
    assert call() == {"N"}
    eng.set_af_mode("balanced")
    fake([0.30, 0.45, 0.2499, 0.0001])  # AF most probable: called when balanced
    assert call() == {"A"}
    with pytest.raises(ValueError, match="AF mode must be one of"):
        eng.set_af_mode("review")  # the fewer-false-alarms mode failed its offering test and is not shipped


def test_offered_modes_carry_their_measured_results():
    ops = Engine().af_modes()
    for name, m in ops.items():
        assert m["val"]["sensitivity"] > 0.9 and m["test"]["af_windows"] > 1000, name
    assert ops["screening"]["test"]["sensitivity"] > ops["balanced"]["test"]["sensitivity"]
    assert ops["screening"]["test"]["false_af_windows"] > ops["balanced"]["test"]["false_af_windows"]  # the cost is shown, not hidden
