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
