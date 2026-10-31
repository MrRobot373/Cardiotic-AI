import socket

import ingest_writers as w
from cardiotic_server import feeds
from helpers import Client


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def test_folder_feed_imports_stable_files_and_sorts_them(server, ecg, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    server.db.set_setting("feeds", {"folders": [{"name": "ECG room 1", "path": str(inbox), "location": "ECG room 1"}]})
    (inbox / "a.dcm").write_bytes(w.dicom_file(ecg, 500))
    (inbox / "b.xml").write_bytes(w.aecg_file(ecg * 0.8, 500))
    (inbox / "scan.pdf").write_bytes(b"%PDF-1.4 " + b"0" * 80)
    (inbox / "c.dcm.part").write_bytes(b"still copying")
    ff = feeds.FolderFeeds(server)
    assert ff.poll() == 0  # first sight: wait until the size stops changing
    assert ff.poll() == 3
    assert sorted(p.name for p in (inbox / "processed").iterdir()) == ["a.dcm", "b.xml"]
    assert "digitiser" in (inbox / "failed" / "scan.pdf.reason.txt").read_text() or (inbox / "failed" / "scan.pdf.reason.txt").exists()
    assert (inbox / "c.dcm.part").exists()
    cat = Client(server.base)
    cat.login("arao")
    ecgs = cat.call("GET", "/api/catalog")[1]["ecgs"]
    assert len(ecgs) == 2 and {e["location"] for e in ecgs} == {"ECG room 1"}
    st = server.db.get_setting("feed_status")["ECG room 1"]
    assert st["received"] == 2 and st["failed"] == 1
    audit = [a["action"] + " " + a["user"] for a in cat.call("GET", "/api/audit")[1]]
    assert any(a.startswith("Uploaded ECG Machine feed: ECG room 1") for a in audit)
    # the same ECG exported again is filed as processed, not as an error
    (inbox / "again.dcm").write_bytes(w.dicom_file(ecg, 500))
    ff.poll(); ff.poll()
    assert (inbox / "processed" / "again.dcm").exists() and len(cat.call("GET", "/api/catalog")[1]["ecgs"]) == 2


def test_unreachable_folder_is_reported(server, tmp_path):
    server.db.set_setting("feeds", {"folders": [{"name": "MUSE", "path": str(tmp_path / "missing")}]})
    feeds.FolderFeeds(server).poll()
    assert "not reachable" in server.db.get_setting("feed_status")["MUSE"]["last_error"]


def test_dicom_receiver_accepts_ecg_and_rejects_garbage(server, ecg):
    import io
    import pydicom
    from pynetdicom import AE
    from pynetdicom.sop_class import TwelveLeadECGWaveformStorage, Verification

    port = _free_port()
    server.dicom.apply({"enabled": True, "port": port, "ae_title": "CARDIOTIC", "location": "Emergency", "host": "127.0.0.1"})
    try:
        ae = AE(ae_title="GE_MAC5500")
        ae.add_requested_context(TwelveLeadECGWaveformStorage)
        ae.add_requested_context(Verification)
        assoc = ae.associate("127.0.0.1", port, ae_title="CARDIOTIC")
        assert assoc.is_established
        assert assoc.send_c_echo().Status == 0
        ds = pydicom.dcmread(io.BytesIO(w.dicom_file(ecg, 500)))
        ds.SOPClassUID = TwelveLeadECGWaveformStorage
        assert assoc.send_c_store(ds).Status == 0x0000
        del ds.WaveformSequence  # no waveform: refused, with a failure status the cart can show
        from pydicom.uid import generate_uid
        ds.SOPInstanceUID = generate_uid()
        assert assoc.send_c_store(ds).Status == 0xC000
        assoc.release()
    finally:
        server.dicom.stop()
    c = Client(server.base)
    c.login("arao")
    ecgs = c.call("GET", "/api/catalog")[1]["ecgs"]
    assert len(ecgs) == 1 and ecgs[0]["location"] == "Emergency"
    st = server.db.get_setting("feed_status")["DICOM GE_MAC5500"]
    assert st["received"] == 1 and st["failed"] == 1


def test_feed_settings_api(server, tmp_path):
    a, t = Client(server.base), Client(server.base)
    a.login("kdesai"); t.login("rsawant")
    assert t.call("PUT", "/api/feeds", {"folders": []})[0] == 403
    assert a.call("PUT", "/api/feeds", {"folders": [{"name": "x", "path": "relative/path"}]})[0] == 400
    port = _free_port()
    a.call("PUT", "/api/feeds", {"folders": [{"name": "MUSE export", "path": str(tmp_path)}], "dicom": {"enabled": True, "port": port}}, expect=200)
    try:
        got = t.call("GET", "/api/feeds", expect=200)[1]
        assert got["folders"][0]["name"] == "MUSE export" and got["dicom_running"] is True and got["dicom"]["ae_title"] == "CARDIOTIC"
    finally:
        a.call("PUT", "/api/feeds", {"folders": [], "dicom": {"enabled": False}}, expect=200)
    assert a.call("GET", "/api/feeds")[1]["dicom_running"] is False
