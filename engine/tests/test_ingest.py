"""ECG file readers: each format round-trips real ECG samples; refusals say why. The files come from
ingest_writers.py (the specifications' layouts), not from vendor carts."""

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import ingest_writers as w  # noqa: E402

from cardiotic_engine.api import Engine, InputError  # noqa: E402
from cardiotic_engine.ingest import IngestError, detect, parse  # noqa: E402

pytest.importorskip("pydicom")
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def x():
    return np.load(FIX / "fixtures.npz")["ecg12"]  # a real PTB-XL ECG: (12, 5000) mV at 500 Hz


@pytest.fixture(scope="module")
def engine():
    return Engine()


def _err(parsed, x):
    return max(np.abs(v - x[w.LEADS.index(k)][: len(v)]).max() for k, v in parsed.leads.items())


FILES = {
    "csv": (lambda x: w.csv_file(x, 500), 12, 1e-4, "csv"),
    "csv-uV-time": (lambda x: w.csv_file(x, 500, unit="uV", with_time=True, comment=False), 12, 1e-4, "csv"),
    "edf": (lambda x: w.edf_file(x, 500), 12, 2e-3, "edf"),
    "aecg": (lambda x: w.aecg_file(x, 500), 12, 2e-3, "hl7-aecg"),
    "muse": (lambda x: w.muse_file(x, 500), 8, 5e-3, "ge-muse-xml"),
    "dicom": (lambda x: w.dicom_file(x, 500), 12, 2e-3, "dicom-ecg"),
    "scp": (lambda x: w.scp_file(x, 500), 8, 2e-3, "scp-ecg"),
    "scp-diff": (lambda x: w.scp_file(x, 500, enc=1), 8, 2e-3, "scp-ecg"),
    "scp-diff2": (lambda x: w.scp_file(x, 500, enc=2), 8, 2e-3, "scp-ecg"),
    "scp-huffman-default": (lambda x: w.scp_huffman_file(x, 500), 8, 2e-3, "scp-ecg"),
    "scp-huffman-site-table": (lambda x: w.scp_huffman_file(x, 500, custom_table=True), 8, 2e-3, "scp-ecg"),
    "scp-huffman-no-diff": (lambda x: w.scp_huffman_file(x, 500, enc=0), 8, 2e-3, "scp-ecg"),
    "philips-xli": (lambda x: w.philips_file(x, 500), 12, 6e-3, "philips-xml"),
    "philips-uncompressed": (lambda x: w.philips_file(x, 500, compression="Uncompressed"), 12, 6e-3, "philips-xml"),
}


@pytest.mark.parametrize("name", FILES)
def test_format_round_trips_real_samples(name, x):
    make, n_leads, tol, fmt = FILES[name]
    p = parse(make(x))
    assert p.format == fmt and p.fs == pytest.approx(500) and len(p.leads) == n_leads
    assert len(next(iter(p.leads.values()))) >= 4990
    assert _err(p, x) < tol


def test_patient_and_time_fields_where_the_format_has_them(x):
    for make in (w.aecg_file, w.muse_file, w.dicom_file, w.scp_file, w.philips_file):
        p = parse(make(x, 500))
        assert p.patient["id"] == "PAT-7" and p.patient["sex"] == "F" and p.patient["birth_date"] == "1960-01-01"
    assert parse(w.aecg_file(x, 500)).recorded_at == "2026-01-05T08:15:30"
    assert parse(w.muse_file(x, 500)).recorded_at == "2026-01-05T08:15:30"
    assert parse(w.muse_file(x, 500)).patient["name"] == "Meera Rao"


def test_csv_needs_a_sampling_rate_and_header_leads(x):
    with pytest.raises(IngestError, match="sampling rate unknown"):
        parse(w.csv_file(x, 500, comment=False))
    assert parse(w.csv_file(x, 500, comment=False), fs=250).fs == 250
    with pytest.raises(IngestError, match="no ECG leads"):
        parse(b"a,b,c\n1,2,3\n4,5,6\n7,8,9\n")


def test_muse_rhythm_waveform_is_chosen_over_median(x):
    p = parse(w.muse_file(x, 500))
    assert len(p.leads["I"]) == x.shape[1]


def test_unsupported_and_damaged_files_are_refused_with_the_reason(x):
    with pytest.raises(IngestError, match="cannot read the PDF"):
        parse(b"%PDF-1.7 " + b"0" * 100)
    with pytest.raises(IngestError, match="no signalcharacteristics"):
        parse(b'<?xml version="1.0"?><restingecgdata><x/></restingecgdata>' + b" " * 20)
    from cardiotic_engine.ingest.scp_ecg import DEFAULT_HUFFMAN, huffman_decode
    with pytest.raises(IngestError, match="Huffman data ends"):
        huffman_decode(b"\xfe", 5, [DEFAULT_HUFFMAN])  # stream ends in the middle of the second code
    bad = w.philips_file(x, 500).replace(b'compression="XLI"', b'compression="ZIP"')
    with pytest.raises(IngestError, match="compression ZIP"):
        parse(bad)
    with pytest.raises(IngestError, match="too small"):
        detect(b"abc")
    with pytest.raises(IngestError, match="shorter"):
        parse(w.edf_file(x, 500)[:-5000])
    bad = w.muse_file(x, 500).replace(b"<WaveFormData>", b"<WaveFormData>!!")
    with pytest.raises(IngestError, match="base64"):
        parse(bad)
    with pytest.raises(IngestError, match="not valid XML"):
        parse(b'<AnnotatedECG xmlns="urn:hl7-org:v3"><oops>' + b" " * 30)
    with pytest.raises(IngestError, match="dicom:"):
        parse(b"\x00" * 128 + b"DICM" + b"garbage" * 20)


def test_scp_crc_mismatch_is_a_note_not_an_error(x):
    data = bytearray(w.scp_file(x, 500))
    data[-3] ^= 0x01  # damage a sample byte
    p = parse(bytes(data))
    assert any("CRC" in n for n in p.notes)


def test_analyze_file_matches_analysing_the_same_samples(engine, x):
    leads = {l: x[i].tolist() for i, l in enumerate(w.LEADS)}
    direct = engine.analyze_ecg12(leads, 500)["result"]
    for name in ("dicom", "aecg", "edf"):
        out = engine.analyze_file(FILES[name][0](x))
        assert out["source_file"]["format"] == FILES[name][3]
        assert [s["statement"] for s in out["result"]["statements"]] == [s["statement"] for s in direct["statements"]]
        for k in ("qrs_ms", "heart_rate_bpm"):
            assert out["result"]["measurements"][k] == pytest.approx(direct["measurements"][k], abs=6)


def test_eight_lead_file_derives_the_limb_leads_and_says_so(engine, x):
    out = engine.analyze_file(w.muse_file(x, 500))
    assert any("derived" in n for n in out["input_notes"]) and out["source_file"]["patient"]["id"] == "PAT-7"


def test_analyze_file_refuses_files_it_cannot_analyse(engine, x):
    with pytest.raises(InputError, match="needs I, II and V1"):
        engine.analyze_file(w.csv_file(x, 500, leads=("I", "II", "III")))
    with pytest.raises(InputError, match="cannot read the PDF"):
        engine.analyze_file(b"%PDF-1.4 " + b"0" * 64)
    short = w.csv_file(x[:, :1500], 500)
    with pytest.raises(InputError, match="8–60 s"):
        engine.analyze_file(short)


def test_single_lead_file_goes_to_rhythm_analysis(engine, x):
    strip = np.tile(x[1], 3)[None]
    data = w.csv_file(np.vstack([strip] * 12)[:, :15000], 500, leads=("II",))
    out = engine.analyze_file(data)
    assert out["analysis"] == "rhythm" and out["source_file"]["leads"] == ["II"]


def test_http_file_endpoint(engine, x):
    from cardiotic_engine.server import serve
    httpd = serve("127.0.0.1", 0, engine)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/v1/file", data=w.dicom_file(x, 500), method="POST")
        out = json.loads(urllib.request.urlopen(req).read())
        assert out["analysis"] == "ecg12" and out["source_file"]["format"] == "dicom-ecg"
        req = urllib.request.Request(base + "/v1/file", data=w.csv_file(x, 500, comment=False), method="POST", headers={"X-Fs": "500"})
        assert json.loads(urllib.request.urlopen(req).read())["source_file"]["fs"] == 500
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base + "/v1/file", data=b"%PDF-1.7 " + b"0" * 50, method="POST"))
        assert e.value.code == 400 and "PDF" in json.loads(e.value.read())["error"]
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base + "/v1/file", data=w.csv_file(x, 500, comment=False), method="POST", headers={"X-Fs": "abc"}))
        assert e.value.code == 400
    finally:
        httpd.shutdown()


# ------------------------------------------------------------------ digitiser (printouts drawn by matplotlib, an independent renderer)
def _trace_r(e, x):
    rs = []
    for i, lead in enumerate(w.LEADS):
        a, b = e.windows[lead]
        ref = np.clip(x[i] - np.median(x[i]), -1.2, 1.2)[a:b]
        got = e.leads[lead][a:b]
        rs.append(np.corrcoef(ref - np.median(ref), got - np.median(got))[0, 1])
    return np.median(rs), np.min(rs)


@pytest.mark.parametrize("kind,kw,min_median_r", [
    ("pdf", {}, 0.99), ("pdf", {"layout": "12x1"}, 0.99),
    ("png", {}, 0.85), ("png", {"rotate": 1.5, "photo": True}, 0.85),
])
def test_digitiser_reads_printouts_back(kind, kw, min_median_r, x):
    pytest.importorskip("matplotlib")
    e = parse(w.printout(x, 500, kind, **kw))
    assert e.layout == ("print-12x1" if kw.get("layout") == "12x1" else "print-3x4")
    if e.layout == "print-3x4":
        assert e.windows["II"] == (0, 5000) and e.windows["V4"] == (3750, 5000)
    med, _ = _trace_r(e, x)
    assert med >= min_median_r, med
    if kw.get("rotate"):
        assert any("straightened" in n for n in e.notes)


def test_digitised_printout_is_analysed_with_its_limits_stated(engine, x):
    pytest.importorskip("matplotlib")
    out = engine.analyze_file(w.printout(x, 500, "pdf"))
    r = out["result"]
    assert out["source_file"]["layout"] == "print-3x4" and r["layout"] == "print-3x4"
    assert r["measurements"]["heart_rate_bpm"] == pytest.approx(engine.analyze_ecg12({l: x[i].tolist() for i, l in enumerate(w.LEADS)}, 500)["result"]["measurements"]["heart_rate_bpm"], abs=3)
    assert r["measurements"]["qrs_ms"] is None and any("QRS, QT and QTc are not measured" in n for n in r["notes"])
    direct = engine.analyze_ecg12({l: x[i].tolist() for i, l in enumerate(w.LEADS)}, 500)["result"]["statements"]
    assert r["statements"] and {s["statement"] for s in r["statements"]} & {s["statement"] for s in direct}  # the printout model finds what the full ECG shows
    assert out["engine"]["models"]["ecg12_print"]["model"] == "ecg12_net_print-v0.1"
    full = engine.analyze_file(w.printout(x, 500, "pdf", layout="12x1"))["result"]
    assert full["measurements"]["qrs_ms"] is not None and any("12 x 1" in n for n in full["notes"])


def test_digitiser_refuses_what_it_cannot_read(x):
    from PIL import Image
    import io as _io
    blank = _io.BytesIO()
    Image.new("RGB", (1200, 800), "white").save(blank, "PNG")
    with pytest.raises(IngestError, match="no ECG traces"):
        parse(blank.getvalue())
    tiny = _io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(tiny, "PNG")
    with pytest.raises(IngestError, match="too small"):
        parse(tiny.getvalue())
