"""Engine tests: integrity, input contract, determinism, golden outputs, HTTP. No research data needed."""

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from cardiotic_engine.api import LEADS, Engine, InputError
from cardiotic_engine.registry import MODELS_DIR, IntegrityError, verify

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def engine():
    return Engine()


@pytest.fixture(scope="module")
def data():
    z = np.load(FIX / "fixtures.npz")
    return z["ecg12"], z["strip"], json.loads((FIX / "golden.json").read_text())


def _leads(x):
    return {l: x[i].tolist() for i, l in enumerate(LEADS)}


def test_models_verify():
    assert set(verify()) == {"quality", "beats", "rhythm", "ecg12"}


def test_altered_model_file_is_refused(tmp_path):
    d = tmp_path / "models"
    shutil.copytree(MODELS_DIR, d)
    p = d / json.loads((d / "manifest.json").read_text())["models"]["beats"]["file"]
    b = bytearray(p.read_bytes()); b[-10] ^= 0xFF; p.write_bytes(bytes(b))
    with pytest.raises(IntegrityError, match="SHA-256"):
        Engine(d)


def test_wrong_model_version_is_refused(tmp_path):
    d = tmp_path / "models"
    shutil.copytree(MODELS_DIR, d)
    m = json.loads((d / "manifest.json").read_text())
    m["models"]["ecg12"]["version"] = "v9.9"
    (d / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(IntegrityError, match="expects"):
        verify(d)


def _same_findings(a, b, kind):
    if kind == "ecg12":
        assert a["lead_quality"] == b["lead_quality"]
        assert [s["statement"] for s in a["statements"]] == [s["statement"] for s in b["statements"]]
        for k, v in b["measurements"].items():
            assert a["measurements"][k] == pytest.approx(v, abs=1e-6) if isinstance(v, float) else a["measurements"][k] == v
        assert max(abs(x["probability"] - y["probability"]) for x, y in zip(a["statements"], b["statements"])) < 1e-4
    else:
        assert a["findings"] == b["findings"]
        assert [x["class"] for x in a["beats"]] == [x["class"] for x in b["beats"]]
        assert [x["rhythm"] for x in a["rhythm_segments"]] == [x["rhythm"] for x in b["rhythm_segments"]]


def test_golden_outputs(engine, data):
    x, strip, golden = data
    _same_findings(engine.analyze_ecg12(_leads(x), 500)["result"], golden["ecg12"], "ecg12")
    _same_findings(engine.analyze_rhythm(strip.tolist(), 360, lead="MLII")["result"], golden["rhythm"], "rhythm")


def test_deterministic(engine, data):
    x, _, _ = data
    a = engine.analyze_ecg12(_leads(x), 500)["result"]
    b = engine.analyze_ecg12(_leads(x), 500)["result"]
    assert json.dumps(a, default=float) == json.dumps(b, default=float)


def test_units_and_eight_lead_input(engine, data):
    x, _, _ = data
    ref = engine.analyze_ecg12(_leads(x), 500)
    uv = engine.analyze_ecg12({l: (x[i] * 1000).tolist() for i, l in enumerate(LEADS)}, 500, units="uV")
    assert [s["statement"] for s in uv["result"]["statements"]] == [s["statement"] for s in ref["result"]["statements"]]
    eight = {l: x[i].tolist() for i, l in enumerate(LEADS) if l not in ("III", "AVR", "AVL", "AVF")}
    out = engine.analyze_ecg12(eight, 500)
    assert sum("derived" in n for n in out["input_notes"]) == 4
    assert out["result"]["measurements"]["ok"]


@pytest.mark.parametrize("leads, fs, units, msg", [
    ("not a dict", 500, "mV", "object"),
    ({"I": [0.0] * 5000}, 500, "mV", "missing leads"),
    ({"XX": [0.0] * 5000}, 500, "mV", "unknown lead"),
    (None, 50, "mV", "fs must be"),
    (None, 500, "volts", "units"),
    (None, 500, "mV", "long"),
])
def test_input_errors(engine, leads, fs, units, msg):
    if leads is None:
        leads = {l: [0.0] * (5000 if msg != "long" else 1000) for l in LEADS}
    with pytest.raises(InputError, match=msg):
        engine.analyze_ecg12(leads, fs, units)


def test_amplitude_and_nan_checks(engine, data):
    x, strip, _ = data
    with pytest.raises(InputError, match="units and gain"):
        engine.analyze_ecg12(_leads(x * 1000), 500)  # µV sent as mV
    s = strip.copy(); s[: len(s) // 5] = np.nan
    with pytest.raises(InputError, match="missing"):
        engine.analyze_rhythm(s.tolist(), 360)


def test_http_service(engine, data):
    from cardiotic_engine.server import serve

    x, _, golden = data
    httpd = serve("127.0.0.1", 0, engine)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert json.load(urllib.request.urlopen(base + "/v1/health"))["status"] == "ok"
        body = json.dumps({"fs": 500, "units": "mV", "leads": _leads(x)}).encode()
        out = json.load(urllib.request.urlopen(urllib.request.Request(base + "/v1/ecg12", data=body)))
        _same_findings(out["result"], golden["ecg12"], "ecg12")
        bad = urllib.request.Request(base + "/v1/ecg12", data=b'{"fs": 500, "leads": {}}')
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 400 and "missing leads" in json.load(e.value)["error"]
    finally:
        httpd.shutdown()
