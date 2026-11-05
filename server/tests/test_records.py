"""Phase B: Holter report and relabelling, search, patient export / erasure / retention, site thresholds, catalog window."""

import io
import json
import zipfile

import numpy as np
import pytest
import ingest_writers as w
from conftest import PASSWORD
from test_server import _signable, client, upload


def _holter(server, ecg, mrn="UH-H1"):
    t = client(server, "rsawant")
    strip = np.tile(ecg[1], 6)
    data = w.csv_file(np.vstack([strip] * 12), 500, comment=False, leads=("II",))
    code, rec = t.call("POST", "/api/upload", raw=data, headers={"X-Fs": "500", "X-Patient-MRN": mrn})
    assert code == 201
    return t, client(server, "arao"), rec["id"]


def _actions(server):
    return [(r["user"], r["action"], r["target"]) for r in server.db.conn().execute("SELECT user, action, target FROM audit ORDER BY id")]


# ------------------------------------------------------------------ Holter
def test_cardiologist_can_relabel_beats_and_counts_follow(server, ecg):
    t, c, hid = _holter(server, ecg)
    before = c.call("GET", f"/api/holter/{hid}/beats", expect=200)[1]
    beats = c.call("GET", f"/api/holter/{hid}", expect=200)[1]["analysis"]["result"]["beats"]
    b = next(x for x in beats if x["class"] == "N")
    out = c.call("PUT", f"/api/holter/{hid}/beats", {"time_s": b["time_s"], "label": "V"}, expect=200)[1]
    assert out["counts"]["V"] == before["counts"]["V"] + 1 and out["counts"]["N"] == before["counts"]["N"] - 1 and out["counts"]["changed"] == 1
    again = c.call("PUT", f"/api/holter/{hid}/beats", {"time_s": b["time_s"], "label": None}, expect=200)[1]  # undo
    assert again["counts"]["changed"] == 0 and again["labels"] == {}
    assert t.call("PUT", f"/api/holter/{hid}/beats", {"time_s": b["time_s"], "label": "V"})[0] == 403
    assert c.call("PUT", f"/api/holter/{hid}/beats", {"time_s": 12345.678, "label": "V"})[0] == 400
    assert c.call("PUT", f"/api/holter/{hid}/beats", {"time_s": b["time_s"], "label": "X"})[0] == 400
    assert any(a[1] == "Relabelled Holter beat" for a in _actions(server))


def test_signed_holter_is_locked_and_reports_reach_the_his(server, ecg):
    t, c, hid = _holter(server, ecg)
    beats = c.call("GET", f"/api/holter/{hid}", expect=200)[1]["analysis"]["result"]["beats"]
    c.call("PUT", f"/api/holter/{hid}/beats", {"time_s": beats[0]["time_s"], "label": "S"}, expect=200)
    assert c.call("GET", f"/api/report/{hid}.hl7")[0] == 409  # nothing leaves before signing
    c.call("PUT", f"/api/reviews/{hid}", {"note": "Rare supraventricular ectopy."}, expect=200)
    c.call("POST", f"/api/reviews/{hid}/sign", {"password": PASSWORD}, expect=200)
    assert c.call("PUT", f"/api/holter/{hid}/beats", {"time_s": beats[1]["time_s"], "label": "V"})[0] == 409
    pdf = c.call("GET", f"/api/report/{hid}.pdf", expect=200)[1]
    assert pdf.startswith(b"%PDF") and b"FINAL" not in pdf[:0]
    hl7 = c.call("GET", f"/api/report/{hid}.hl7", expect=200)[1].decode("latin-1")
    assert "ORU^R01" in hl7 and "18754-2^Holter ECG study" in hl7 and "BEATS-S" in hl7 and "Rare supraventricular ectopy" in hl7 and "ED|HOLTER-PDF" not in hl7 or "HOLTER-PDF" in hl7
    seg = {l.split("|")[3].split("^")[0]: l.split("|")[5] for l in hl7.split("\r") if l.startswith("OBX|") and "BEATS-" in l}
    assert seg["BEATS-S"] == "1"
    fhir = c.call("GET", f"/api/report/{hid}.fhir.json", expect=200)[1]
    rep = next(e["resource"] for e in fhir["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")
    assert rep["code"]["coding"][0]["code"] == "18754-2" and rep["presentedForm"][0]["contentType"] == "application/pdf"
    # signing queued a delivery for the HIS, like a 12-lead report
    assert server.db.conn().execute("SELECT COUNT(*) FROM outbox WHERE ecg_id=?", (hid,)).fetchone()[0] == 1


# ------------------------------------------------------------------ search and catalog window
def test_search_by_mrn_name_and_id_with_paging(server, ecg):
    t, c, rid = _signable(server, ecg)
    _holter(server, ecg, mrn="ZZ-4242")
    r = c.call("GET", "/api/search?q=ZZ-4242", expect=200)[1]
    assert r["total"] == 1 and r["items"][0]["kind"] == "holter" and r["items"][0]["mrn"] == "ZZ-4242"
    assert c.call("GET", f"/api/search?q={rid}")[1]["total"] == 1
    assert c.call("GET", "/api/search?q=")[1]["total"] == 2
    assert c.call("GET", "/api/search?limit=1&offset=1")[1]["items"][0]["id"] in (rid, "H000001")
    assert c.call("GET", "/api/search?kind=ecg12")[1]["total"] == 1
    assert c.call("GET", "/api/search?q=%25")[1]["total"] == 0  # a % is text, not a wildcard
    assert c.call("GET", "/api/search?limit=abc")[0] == 400
    assert t.call("GET", "/api/search", expect=200)  # technicians search too


def test_large_archives_load_open_and_recent_only(server, ecg, monkeypatch):
    import cardiotic_server.store as st
    t, c, rid = _signable(server, ecg)
    assert c.call("GET", "/api/catalog")[1]["truncated"] is False
    monkeypatch.setattr(st, "CATALOG_FULL", 0)
    cat = c.call("GET", "/api/catalog")[1]
    assert cat["truncated"] is True and [e["id"] for e in cat["ecgs"]] == [rid]  # unsigned stays
    findings = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {f: "accepted" for f in findings}}, expect=200)
    c.call("POST", f"/api/reviews/{rid}/sign", {"password": PASSWORD}, expect=200)
    server.db.conn().execute("UPDATE recordings SET recorded_at='2020-01-01T00:00', summary=json_set(summary,'$.recorded_at','2020-01-01T00:00')")
    old = c.call("GET", "/api/catalog")[1]
    assert old["ecgs"] == [] and old["truncated"] is True and old["total_recordings"] == 1  # signed and old: found through search
    assert c.call("GET", f"/api/search?q={rid}")[1]["total"] == 1


# ------------------------------------------------------------------ patient export, erasure, retention
def _signed(server, ecg):
    t, c, rid = _signable(server, ecg)
    f = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {x: "accepted" for x in f}}, expect=200)
    c.call("POST", f"/api/reviews/{rid}/sign", {"password": PASSWORD}, expect=200)
    pid = server.db.conn().execute("SELECT patient_id FROM recordings WHERE id=?", (rid,)).fetchone()[0]
    server.db.conn().execute("UPDATE outbox SET status='sent'")
    return c, rid, pid


def test_patient_export_is_a_zip_for_admins_only(server, ecg):
    c, rid, pid = _signed(server, ecg)
    assert c.call("GET", f"/api/patients/{pid}/export")[0] == 403
    a = client(server, "kdesai")
    code, data = a.call("GET", f"/api/patients/{pid}/export", expect=200)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    assert {"patient.json", "index.json", f"{rid}/summary.json", f"{rid}/review.json", f"{rid}/review-history.json", f"{rid}/report.pdf"} <= names
    assert z.read(f"{rid}/report.pdf").startswith(b"%PDF") and json.loads(z.read("index.json"))["recordings"][0]["status"] == "signed"
    assert any(x[1] == "Exported patient data" for x in _actions(server))
    assert a.call("GET", "/api/patients/P99999/export")[0] == 404


def test_erasure_needs_admin_mrn_confirmation_and_respects_retention(server, ecg):
    c, rid, pid = _signed(server, ecg)
    mrn = server.db.conn().execute("SELECT mrn FROM patients WHERE id=?", (pid,)).fetchone()[0]
    a = client(server, "kdesai")
    assert c.call("DELETE", f"/api/patients/{pid}", {"confirm_mrn": mrn})[0] == 403
    assert a.call("DELETE", f"/api/patients/{pid}", {"confirm_mrn": "wrong"})[0] == 400
    code, out = a.call("DELETE", f"/api/patients/{pid}", {"confirm_mrn": mrn})
    assert code == 409 and "retention" in out["error"]  # signed minutes ago: inside the 10-year period
    a.call("PUT", "/api/settings", {"retentionYears": 0}, expect=200)
    assert client(server, "arao").call("PUT", "/api/settings", {"retentionYears": 5})[0] == 403
    server.db.conn().execute("UPDATE outbox SET status='pending'")
    assert a.call("DELETE", f"/api/patients/{pid}", {"confirm_mrn": mrn})[0] == 409  # a message is still waiting for the HIS
    server.db.conn().execute("UPDATE outbox SET status='sent'")
    assert a.call("DELETE", f"/api/patients/{pid}", {"confirm_mrn": mrn}, expect=200)[1] == {"erased": pid, "recordings": 1}
    cnt = lambda t: server.db.conn().execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    assert [cnt(t) for t in ("patients", "recordings", "reviews", "review_versions", "outbox")] == [0, 0, 0, 0, 0]
    assert server.db.verify_audit()["ok"] is True  # the audit chain is intact
    assert ("Kiran Desai", "Erased patient record", f"{pid}: 1 recordings") in _actions(server)
    assert mrn not in json.dumps([x for x in _actions(server) if x[1] == "Erased patient record"])
    assert a.call("GET", f"/api/ecg/{rid}")[0] == 404


def test_retention_listing_shows_what_could_be_erased(server, ecg):
    c, rid, pid = _signed(server, ecg)
    a = client(server, "kdesai")
    assert a.call("GET", "/api/retention", expect=200)[1]["eligible"] == []
    server.db.conn().execute("UPDATE reviews SET signed_at='2001-01-01T00:00:00+00:00'")
    r = a.call("GET", "/api/retention", expect=200)[1]
    assert r["retentionYears"] == 10 and [x["id"] for x in r["eligible"]] == [rid]
    assert c.call("GET", "/api/retention")[0] == 403


# ------------------------------------------------------------------ site thresholds
def _cfg(server, **over):
    card = server.engine._m.manifest["models"]["ecg12"]
    cfg = {"site_id": "PULSE-1", "config_version": "1", "model": f"{card['name']}_{card['version']}", "approved_by": "Dr. Rao", "approved_at": "2026-11-01",
           "statements": {"AFIB": {"threshold": 0.35}, "LNGQT": {"threshold": 0.2}}}
    cfg.update(over)
    return json.dumps(cfg).encode()


def test_site_thresholds_upload_activate_roll_back(server, ecg):
    a = client(server, "kdesai")
    try:
        assert a.call("GET", "/api/site-config", expect=200)[1]["versions"] == []
        assert client(server, "rsawant").call("GET", "/api/site-config")[0] == 403
        raw = _cfg(server)
        cid = a.call("POST", "/api/site-config", raw=raw, expect=201)[1]["id"]
        assert a.call("POST", "/api/site-config", raw=raw)[0] == 409  # same file twice
        assert a.call("POST", "/api/site-config", raw=_cfg(server, approved_by=""))[0] == 400  # not signed off
        assert a.call("POST", "/api/site-config", raw=_cfg(server, model="ecg12_net_v9.9"))[0] == 400  # another model
        assert a.call("POST", "/api/site-config", raw=b"not json")[0] == 400
        assert server.engine.info().get("site_config") is None  # uploading does not activate
        out = a.call("POST", f"/api/site-config/{cid}/activate", {}, expect=200)[1]
        assert out["versions"][0]["active"] is True and server.engine.info()["site_config"]["statements"] == ["AFIB", "LNGQT"]
        assert any(x[1] == "Activated site thresholds" for x in _actions(server))
        cid2 = a.call("POST", "/api/site-config", raw=_cfg(server, config_version="2", statements={"AFIB": {"threshold": 0.5}}), expect=201)[1]["id"]
        a.call("POST", f"/api/site-config/{cid2}/activate", {}, expect=200)
        v = a.call("GET", "/api/site-config")[1]["versions"]
        assert [x["active"] for x in v] == [True, False] and server.engine.info()["site_config"]["statements"] == ["AFIB"]
        a.call("POST", f"/api/site-config/{cid}/activate", {}, expect=200)  # roll back
        assert server.engine.info()["site_config"]["config_version"] == "1"
        a.call("POST", "/api/site-config/deactivate", {}, expect=200)
        assert server.engine.info().get("site_config") is None
        assert a.call("POST", "/api/site-config/999/activate", {})[0] == 404
    finally:
        server.engine.apply_site_config(None)  # the engine fixture is shared by the whole test session


def test_site_thresholds_survive_a_restart(server):
    from cardiotic_server import siteconfigs
    a = client(server, "kdesai")
    try:
        cid = a.call("POST", "/api/site-config", raw=_cfg(server), expect=201)[1]["id"]
        a.call("POST", f"/api/site-config/{cid}/activate", {}, expect=200)
        server.engine.apply_site_config(None)  # as if the process had just started
        siteconfigs.restore_on_start(server)
        assert server.engine.info()["site_config"]["site_id"] == "PULSE-1"
        server.db.conn().execute("UPDATE site_configs SET raw=?", (_cfg(server, model="ecg12_net_v9.9").decode(),))
        siteconfigs.restore_on_start(server)  # no longer fits the model: switched off, not silently kept
        assert server.engine.info().get("site_config") is None and siteconfigs.active_id(server.db) is None
        assert any(x[1] == "Site thresholds switched off at start-up" for x in _actions(server))
    finally:
        server.engine.apply_site_config(None)


def test_search_result_can_be_opened_through_catalog_include(server, ecg, monkeypatch):
    import cardiotic_server.store as st
    c, rid, pid = _signed(server, ecg)
    server.db.conn().execute("UPDATE recordings SET recorded_at='2020-01-01T00:00', summary=json_set(summary,'$.recorded_at','2020-01-01T00:00')")
    monkeypatch.setattr(st, "CATALOG_FULL", 0)
    assert c.call("GET", "/api/catalog")[1]["ecgs"] == []
    cat = c.call("GET", f"/api/catalog?include={rid},bad;drop,E1x", expect=200)[1]
    assert [e["id"] for e in cat["ecgs"]] == [rid] and [p["id"] for p in cat["patients"]] == [pid]


def test_af_mode_is_a_site_setting_that_switches_the_engine(server):
    a = client(server, "kdesai")
    try:
        assert a.call("GET", "/api/settings", expect=200)[1]["afMode"] == "balanced"
        assert a.call("PUT", "/api/settings", {"afMode": "review"})[0] == 400
        assert client(server, "rsawant").call("PUT", "/api/settings", {"afMode": "screening"})[0] == 403
        a.call("PUT", "/api/settings", {"afMode": "screening"}, expect=200)
        assert server.engine.info()["af_mode"] == "screening"
        assert any(x[1] == "Changed site settings" and "afMode" in x[2] for x in _actions(server))
        a.call("PUT", "/api/settings", {"afMode": "balanced"}, expect=200)
        assert server.engine.info()["af_mode"] == "balanced"
    finally:
        server.engine.set_af_mode("balanced")
