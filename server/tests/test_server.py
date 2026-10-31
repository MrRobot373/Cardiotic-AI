import json
import time

import pytest

import ingest_writers as w
from cardiotic_server import auth, export
from helpers import Client


def client(server, user):
    c = Client(server.base)
    assert c.login(user)[0] == 200
    return c


def upload(c, ecg, fmt="dicom", mrn=None, **headers):
    data = {"dicom": w.dicom_file, "aecg": w.aecg_file, "csv": lambda x, fs: w.csv_file(x, fs, comment=False)}[fmt](ecg, 500)
    h = {"X-Filename": f"ecg.{fmt}", **({"X-Patient-MRN": mrn} if mrn else {}), **headers}
    if fmt == "csv":
        h["X-Fs"] = "500"
    return c.call("POST", "/api/upload", raw=data, headers=h)


# ------------------------------------------------------------------ accounts
def test_login_logout_and_roles(server):
    c = Client(server.base)
    assert c.call("GET", "/api/catalog")[0] == 401
    assert c.login("arao", "wrong password!!")[0] == 401
    code, out = c.login("arao")
    assert code == 200 and out["user"]["role"] == "cardiologist" and "pw_hash" not in json.dumps(out)
    assert c.call("GET", "/api/me")[1]["user"]["name"] == "Dr. Ananya Rao"
    assert c.call("POST", "/api/logout", {})[0] == 200
    assert c.call("GET", "/api/me")[0] == 401  # the session is gone


def test_lockout_after_repeated_failures_and_same_message(server):
    c = Client(server.base)
    msgs = {c.login("rsawant", "nope nope nope")[1]["error"] for _ in range(5)}
    assert len(msgs) == 1
    assert c.login("rsawant")[0] == 401  # locked even with the right password
    assert c.login("nobody", "whatever whatever")[1]["error"] in msgs  # unknown user looks the same
    server.db.conn().execute("UPDATE users SET locked_until=0")
    assert c.login("rsawant")[0] == 200


def test_idle_session_expires(server, monkeypatch):
    c = client(server, "arao")
    monkeypatch.setattr(auth, "IDLE_SECONDS", 0)
    time.sleep(0.01)
    assert c.call("GET", "/api/me")[0] == 401


def test_password_policy_and_hashing(server):
    with pytest.raises(ValueError, match="at least"):
        auth.create_user(server.db, "x1", "X", "admin", "short")
    with pytest.raises(ValueError, match="user name"):
        auth.create_user(server.db, "mallory", "M", "admin", "mallory-password-1")
    h = server.db.conn().execute("SELECT pw_hash FROM users WHERE username='arao'").fetchone()[0]
    assert h.startswith("scrypt$") and "correct horse" not in h


def test_cookie_session_needs_the_csrf_header(server):
    import urllib.request
    req = urllib.request.Request(server.base + "/api/login", data=json.dumps({"username": "arao", "password": "correct horse battery"}).encode(), method="POST")
    with urllib.request.urlopen(req) as r:
        cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    sess = cookie.split(";")[0]
    post = urllib.request.Request(server.base + "/api/patients", data=b'{"mrn":"A1","name":"A B"}', method="POST", headers={"Cookie": sess})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(post)
    assert e.value.code == 403
    post = urllib.request.Request(server.base + "/api/patients", data=b'{"mrn":"A1","name":"A B"}', method="POST", headers={"Cookie": sess, "X-Requested-With": "cardiotic"})
    assert urllib.request.urlopen(post).status == 201


def test_only_admin_manages_users(server):
    assert client(server, "arao").call("GET", "/api/users")[0] == 403
    a = client(server, "kdesai")
    assert a.call("POST", "/api/users", {"username": "newdoc", "name": "New Doc", "role": "cardiologist", "password": "a-long-password-1"}, expect=201)
    assert Client(server.base).login("newdoc", "a-long-password-1")[0] == 200
    assert a.call("PATCH", "/api/users/newdoc", {"active": False}, expect=200)
    assert Client(server.base).login("newdoc", "a-long-password-1")[0] == 401
    assert a.call("PATCH", "/api/users/kdesai", {"active": False})[0] == 409


# ------------------------------------------------------------------ upload and analysis
def test_upload_analyses_stores_and_lists(server, ecg):
    t = client(server, "rsawant")
    code, rec = upload(t, ecg, "dicom", location="ECG room 1", **{"X-Ordered-By": "Dr. Rao"})
    assert code == 201 and rec["id"].startswith("E") and rec["source"]["dataset"] == "dicom-ecg"
    cat = t.call("GET", "/api/catalog", expect=200)[1]
    assert [e["id"] for e in cat["ecgs"]] == [rec["id"]] and cat["patients"][0]["mrn"] == "PAT-7"
    assert cat["patients"][0]["sex"] == "F" and cat["patients"][0]["age"] > 60
    assert cat["ecgs"][0]["measurements"]["ok"] and cat["ecgs"][0]["statements"]
    d = t.call("GET", f"/api/ecg/{rec['id']}", expect=200)[1]
    assert set(d["leads"]) == set(w.LEADS) and d["median"] and d["analysis"]["result"]["measurements"]["heart_rate_bpm"] > 30
    assert t.call("GET", "/api/reviews")[1][rec["id"]]["status"] == "new"


def test_duplicate_unreadable_and_forbidden_uploads(server, ecg):
    t = client(server, "rsawant")
    assert upload(t, ecg, "dicom")[0] == 201
    code, out = upload(t, ecg, "dicom")
    assert code == 409 and "already uploaded" in out["error"]
    assert t.call("POST", "/api/upload", raw=b"%PDF-1.4 " + b"0" * 64)[0] == 400
    assert t.call("POST", "/api/upload", raw=b"")[0] == 400
    assert upload(client(server, "kdesai"), ecg, "aecg")[0] == 403
    assert upload(Client(server.base), ecg, "aecg")[0] == 401


def test_file_without_patient_id_is_kept_unmatched_and_can_be_assigned(server, ecg):
    t = client(server, "rsawant")
    code, rec = upload(t, ecg, "csv")
    assert code == 201
    cat = t.call("GET", "/api/catalog")[1]
    assert cat["patients"][0]["mrn"].startswith("UNMATCHED-") and cat["patients"][0]["name"] == "Unidentified patient"
    t.call("POST", "/api/patients", {"mrn": "UH-1", "name": "Real Patient", "sex": "M"}, expect=201)
    t.call("POST", f"/api/recordings/{rec['id']}/patient", {"mrn": "UH-1"}, expect=200)
    cat = t.call("GET", "/api/catalog")[1]
    pid = next(p["id"] for p in cat["patients"] if p["mrn"] == "UH-1")
    assert cat["ecgs"][0]["patient_id"] == pid


def test_header_mrn_overrides_nothing_but_fills_missing_ids(server, ecg):
    t = client(server, "rsawant")
    code, rec = upload(t, ecg, "csv", mrn="UH-77")
    assert t.call("GET", "/api/catalog")[1]["patients"][0]["mrn"] == "UH-77"


# ------------------------------------------------------------------ review and sign-off
def _signable(server, ecg):
    t = client(server, "rsawant")
    rec = upload(t, ecg, "dicom", **{"X-Ordered-By": "Dr. Rao"})[1]
    c = client(server, "arao")
    return t, c, rec["id"]


def test_sign_requires_every_finding_decided_and_a_cardiologist(server, ecg):
    t, c, rid = _signable(server, ecg)
    assert t.call("POST", f"/api/reviews/{rid}/sign", {})[0] == 403
    code, out = c.call("POST", f"/api/reviews/{rid}/sign", {})
    assert code == 409 and "decide on every AI finding" in out["error"]
    findings = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    dec = {f: "accepted" for f in findings}
    rv = c.call("PUT", f"/api/reviews/{rid}", {"decisions": dec, "note": "Reviewed.", "status": "in_review"}, expect=200)[1]
    assert rv["decisions"] == dec and rv["version"] == 1
    signed = c.call("POST", f"/api/reviews/{rid}/sign", {"version": 1}, expect=200)[1]
    assert signed["status"] == "signed" and signed["signedBy"] == "Dr. Ananya Rao" and signed["signedAt"]
    assert c.call("PUT", f"/api/reviews/{rid}", {"note": "changed"})[0] == 409  # signed reports are read-only
    assert c.call("POST", f"/api/reviews/{rid}/sign", {})[0] == 409


def test_technician_can_send_for_reading_but_not_decide(server, ecg):
    t, c, rid = _signable(server, ecg)
    assert t.call("PUT", f"/api/reviews/{rid}", {"status": "in_review"}, expect=200)[1]["status"] == "in_review"
    assert t.call("PUT", f"/api/reviews/{rid}", {"decisions": {"AFIB": "accepted"}})[0] == 403
    assert client(server, "kdesai").call("PUT", f"/api/reviews/{rid}", {"status": "repeat"})[0] == 403
    assert c.call("PUT", f"/api/reviews/{rid}", {"status": "signed"})[0] == 400


def test_client_supplied_audit_label_is_recorded_not_stored_as_a_review_field(server, ecg):
    t, c, rid = _signable(server, ecg)
    assert t.call("PUT", f"/api/reviews/{rid}", {"status": "in_review", "audit": "Sent ECG for reading"}, expect=200)
    assert any(a["action"] == "Sent ECG for reading" for a in client(server, "kdesai").call("GET", "/api/audit")[1])


def test_stale_version_is_refused(server, ecg):
    t, c, rid = _signable(server, ecg)
    c.call("PUT", f"/api/reviews/{rid}", {"note": "one"}, expect=200)
    assert c.call("PUT", f"/api/reviews/{rid}", {"note": "two", "version": 0})[0] == 409


def test_validation_rejects_bad_review_fields(server, ecg):
    t, c, rid = _signable(server, ecg)
    for bad in ({"decisions": {"AFIB": "maybe"}}, {"edits": {"qt_ms": "long"}}, {"note": "x" * 5000}, {"status": "weird"}, {"nope": 1}):
        assert c.call("PUT", f"/api/reviews/{rid}", bad)[0] == 400, bad


def test_amend_reopens_a_signed_report_with_audit(server, ecg):
    t, c, rid = _signable(server, ecg)
    findings = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {f: "accepted" for f in findings}}, expect=200)
    c.call("POST", f"/api/reviews/{rid}/sign", {}, expect=200)
    assert t.call("PUT", f"/api/reviews/{rid}", {"status": "in_review"})[0] == 409
    rv = c.call("PUT", f"/api/reviews/{rid}", {"status": "in_review"}, expect=200)[1]
    assert rv["status"] == "in_review" and rv["signedBy"] is None
    actions = [a["action"] for a in client(server, "kdesai").call("GET", "/api/audit")[1]]
    assert "Signed ECG report" in actions and "Re-opened signed report (amendment)" in actions and "Uploaded ECG" in actions


# ------------------------------------------------------------------ audit, settings
def test_audit_chain_detects_tampering(server, ecg):
    _signable(server, ecg)
    a = client(server, "kdesai")
    assert a.call("GET", "/api/audit/verify")[1]["ok"]
    server.db.conn().execute("UPDATE audit SET action='Nothing happened' WHERE id=2")
    out = a.call("GET", "/api/audit/verify")[1]
    assert out["ok"] is False and out["first_bad_id"] == 2
    assert client(server, "rsawant").call("GET", "/api/audit")[0] == 403


def test_site_settings_roles_and_validation(server):
    assert client(server, "rsawant").call("PUT", "/api/settings", {"siteName": "X"})[0] == 403
    a = client(server, "kdesai")
    assert a.call("PUT", "/api/settings", {"siteName": "Pulse Care"}, expect=200)[1]["siteName"] == "Pulse Care"
    assert a.call("PUT", "/api/settings", {"operatingPoint": "extreme"})[0] == 400
    assert a.call("PUT", "/api/settings", {"unknown": 1})[0] == 400
    assert client(server, "arao").call("GET", "/api/me")[1]["site"]["siteName"] == "Pulse Care"


# ------------------------------------------------------------------ HIS export
def _sign_all(server, ecg):
    t, c, rid = _signable(server, ecg)
    findings = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {f: "accepted" for f in findings[:-1]} | ({findings[-1]: "rejected"} if findings else {}), "note": "Rate | control & review"}, expect=200)
    c.call("POST", f"/api/reviews/{rid}/sign", {}, expect=200)
    return c, rid, findings


def test_reports_exist_only_after_signing_and_say_what_was_signed(server, ecg):
    t, c, rid = _signable(server, ecg)
    assert c.call("GET", f"/api/report/{rid}.hl7")[0] == 409
    assert c.call("GET", f"/api/report/{rid}.fhir.json")[0] == 409


def test_hl7_and_fhir_reflect_the_signed_review(server, ecg):
    c, rid, findings = _sign_all(server, ecg)
    hl7 = c.call("GET", f"/api/report/{rid}.hl7", expect=200)[1].decode("latin-1")
    segs = [s.split("|") for s in hl7.strip("\r").split("\r")]
    assert segs[0][8].startswith("ORU^R01") and segs[0][11] == "2.5.1"
    pid = next(s for s in segs if s[0] == "PID")
    assert pid[3].startswith("PAT-7^") and pid[5] == "Rao^Meera"
    stm = [s[5].split("^")[0] for s in segs if s[0] == "OBX" and s[3].startswith("ECG-STMT")]
    assert findings and set(stm) == set(findings[:-1])  # the rejected finding is not in the report
    assert not any(s[0] == "OBX" and s[2] == "FT" and "Rate \\F\\ control" not in s[5] for s in segs)  # delimiters escaped
    fhir = c.call("GET", f"/api/report/{rid}.fhir.json", expect=200)[1]
    assert fhir["resourceType"] == "Bundle" and fhir["type"] == "transaction"
    dr = next(e["resource"] for e in fhir["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")
    assert dr["status"] == "final" and dr["code"]["coding"][0]["code"] == "11524-6" and dr["resultsInterpreter"][0]["display"] == "Dr. Ananya Rao"
    refs = {e["fullUrl"] for e in fhir["entry"]}
    assert all(r["reference"] in refs for r in dr["result"]) and dr["subject"]["reference"] in refs


def test_edited_qt_is_what_the_hospital_receives(server, ecg):
    t, c, rid = _signable(server, ecg)
    findings = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {f: "accepted" for f in findings}, "edits": {"qt_ms": 400, "cal.tEnd": 123}}, expect=200)
    c.call("POST", f"/api/reviews/{rid}/sign", {}, expect=200)
    hl7 = c.call("GET", f"/api/report/{rid}.hl7")[1].decode("latin-1")
    qt = next(s for s in (l.split("|") for l in hl7.split("\r")) if len(s) > 3 and s[0] == "OBX" and s[3].startswith("8634-8"))
    assert qt[5] == "400"


def test_signing_queues_a_message_and_the_worker_delivers_to_an_mllp_listener(server, ecg):
    import socket
    import threading

    received = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def listen():
        conn, _ = srv.accept()
        buf = b""
        while not buf.endswith(export.MLLP_END):
            buf += conn.recv(4096)
        received.append(buf.strip(export.MLLP_START + export.MLLP_END).decode("latin-1"))
        mid = received[0].split("\r")[0].split("|")[9]
        conn.sendall(export.MLLP_START + f"MSH|^~\\&|HIS||CARDIOTIC||20260101||ACK^R01|1|P|2.5.1\rMSA|AA|{mid}\r".encode() + export.MLLP_END)
        conn.close()

    threading.Thread(target=listen, daemon=True).start()
    server.db.set_setting("his", {"enabled": True, "host": "127.0.0.1", "port": srv.getsockname()[1], "facility": "HOSP", "application": "HIS"})
    _sign_all(server, ecg)
    ob = server.db.conn().execute("SELECT status, kind FROM outbox").fetchall()
    assert [(r["status"], r["kind"]) for r in ob] == [("pending", "hl7-oru")]
    assert server.worker.deliver_due() == 1
    assert server.db.conn().execute("SELECT status, sent_at FROM outbox").fetchone()["status"] == "sent"
    assert received and received[0].startswith("MSH|") and "ORU^R01" in received[0] and "HOSP" in received[0].split("\r")[0]
    assert any(a["action"] == "Report sent to HIS" for a in client(server, "kdesai").call("GET", "/api/audit")[1])


def test_unreachable_his_keeps_the_message_and_backs_off(server, ecg):
    server.db.set_setting("his", {"enabled": True, "host": "127.0.0.1", "port": 1})
    _sign_all(server, ecg)
    assert server.worker.deliver_due() == 0
    row = server.db.conn().execute("SELECT status, attempts, last_error, next_try FROM outbox").fetchone()
    assert row["status"] == "pending" and row["attempts"] == 1 and "cannot reach" in row["last_error"] and row["next_try"] > time.time()
    assert server.worker.deliver_due() == 0  # not retried before its time
    a = client(server, "kdesai")
    assert a.call("GET", "/api/outbox")[1][0]["status"] == "pending"
    assert a.call("POST", "/api/outbox/1/retry", {}, expect=200)


def test_his_rejection_is_recorded(server, ecg):
    import socket
    import threading
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)

    def listen():
        conn, _ = srv.accept()
        conn.recv(65536)
        conn.sendall(export.MLLP_START + b"MSH|^~\\&|HIS||C||2026||ACK|1|P|2.5.1\rMSA|AR|X|unknown patient\r" + export.MLLP_END)
        conn.close()
    threading.Thread(target=listen, daemon=True).start()
    server.db.set_setting("his", {"enabled": True, "host": "127.0.0.1", "port": srv.getsockname()[1]})
    _sign_all(server, ecg)
    server.worker.deliver_due()
    assert "rejected" in server.db.conn().execute("SELECT last_error FROM outbox").fetchone()["last_error"]


def test_his_settings_validation(server):
    a = client(server, "kdesai")
    assert a.call("PUT", "/api/his", {"enabled": True})[0] == 400
    assert a.call("PUT", "/api/his", {"enabled": True, "host": "h", "port": 99999})[0] == 400
    assert a.call("PUT", "/api/his", {"enabled": True, "host": "his.local", "port": 2575}, expect=200)
    assert client(server, "arao").call("GET", "/api/his")[0] == 403


# ------------------------------------------------------------------ holter
def test_single_lead_upload_becomes_a_holter_recording(server, ecg):
    import numpy as np
    t = client(server, "rsawant")
    strip = np.tile(ecg[1], 6)  # 60 s of lead II
    data = w.csv_file(np.vstack([strip] * 12), 500, comment=False, leads=("II",))
    code, rec = t.call("POST", "/api/upload", raw=data, headers={"X-Fs": "500", "X-Patient-MRN": "UH-9"})
    assert code == 201 and rec["id"].startswith("H") and rec["duration_s"] == pytest.approx(60, abs=0.1)
    cat = t.call("GET", "/api/catalog")[1]
    assert [h["id"] for h in cat["holters"]] == [rec["id"]] and cat["ecgs"] == []
    sig = t.call("GET", f"/api/holter/{rec['id']}/signal", expect=200)[1]
    assert len(sig) == 2 * 30000
    assert t.call("GET", f"/api/holter/{rec['id']}", expect=200)[1]["analysis"]["result"]["beats"]


def test_web_app_is_served_with_security_headers(tmp_path, engine):
    import threading
    import urllib.request
    from cardiotic_server.app import make_app
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<html><script>document.x=1</script><script type=module src=/assets/a.js></script>app</html>")
    (tmp_path / "web" / "assets").mkdir()
    (tmp_path / "web" / "assets" / "a.js").write_text("1")
    httpd, _, _ = make_app(tmp_path / "s.db", tmp_path / "web", engine, "127.0.0.1", 0, start_worker=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        r = urllib.request.urlopen(base + "/worklist/anything")  # single-page app fallback
        body = r.read()
        csp = r.headers["Content-Security-Policy"]
        assert b"app</html>" in body and "frame-ancestors 'none'" in csp
        import base64, hashlib
        assert "'sha256-" + base64.b64encode(hashlib.sha256(b"document.x=1").digest()).decode() + "'" in csp and "unsafe-inline'" not in csp.split("script-src")[1]
        assert "immutable" in urllib.request.urlopen(base + "/assets/a.js").headers["Cache-Control"]
        r = urllib.request.urlopen(base + "/../../etc/passwd")  # path traversal falls back to the app, never a file
        assert b"app</html>" in r.read()
    finally:
        httpd.shutdown()


def test_unread_request_bodies_do_not_corrupt_the_next_request_on_the_same_connection(server):
    import http.client
    conn = http.client.HTTPConnection(server.base.split("//")[1])
    conn.request("POST", "/api/logout", body=b'{"x": 1}', headers={"Content-Type": "application/json"})  # no session: refused before reading the body
    r = conn.getresponse(); r.read()
    assert r.status == 401
    conn.request("GET", "/api/health")
    r = conn.getresponse()
    assert r.status == 200 and json.loads(r.read())["status"] == "ok"
    conn.close()


def test_signing_while_other_requests_run(server, ecg):
    """Signing builds the HL7 message inside its transaction; requests from other users at that moment must
    keep working (a shared connection would fail across threads)."""
    import threading
    t, c, rid = _signable(server, ecg)
    findings = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {f: "accepted" for f in findings}}, expect=200)
    codes, stop = [], threading.Event()

    def poll():
        p = client(server, "rsawant")
        while not stop.is_set():
            codes.append(p.call("GET", "/api/reviews")[0])
            codes.append(p.call("GET", "/api/catalog")[0])

    threads = [threading.Thread(target=poll) for _ in range(4)]
    for th in threads:
        th.start()
    try:
        assert c.call("POST", f"/api/reviews/{rid}/sign", {})[0] == 200
        for _ in range(20):  # sign more ECGs while the others poll
            _, rec = upload(t, ecg * (1 + 0.01 * (_ + 1)), "dicom")
            fs = [s["statement"] for s in c.call("GET", f"/api/ecg/{rec['id']}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
            c.call("PUT", f"/api/reviews/{rec['id']}", {"decisions": {f: "accepted" for f in fs}}, expect=200)
            assert c.call("POST", f"/api/reviews/{rec['id']}/sign", {})[0] == 200
    finally:
        stop.set()
        for th in threads:
            th.join()
    assert codes and set(codes) == {200}
    assert server.db.conn().execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 21
