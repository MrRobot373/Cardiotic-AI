"""Phase A: read-access log, password confirmation at signing, password policy, per-address rate limit,
network allow-lists, critical-result notifications, review history."""

import json
import socket
from pathlib import Path
import time

import pytest
from conftest import PASSWORD
from helpers import Client

from cardiotic_server import auth, notify, security
from cardiotic_server.triage import triage
from test_server import _signable, client, upload


def _decide_all(c, rid):
    f = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {x: "accepted" for x in f}}, expect=200)


def _actions(server):
    return [(r["user"], r["action"], r["target"]) for r in server.db.conn().execute("SELECT user, action, target FROM audit ORDER BY id")]


# ------------------------------------------------------------------ read access is audited
def test_opening_a_record_is_audited_once_per_window(server, ecg):
    t, c, rid = _signable(server, ecg)
    for _ in range(3):
        c.call("GET", f"/api/ecg/{rid}", expect=200)
    c.call("GET", f"/api/report/{rid}.pdf", expect=200)
    views = [a for a in _actions(server) if a[1].startswith("Viewed")]
    assert views.count(("Dr. Ananya Rao", "Viewed ECG", rid)) == 1  # three opens, one entry
    assert ("Dr. Ananya Rao", "Viewed report (PDF)", rid) in views


# ------------------------------------------------------------------ password confirmation at signing
def test_signing_needs_the_password_again(server, ecg):
    t, c, rid = _signable(server, ecg)
    _decide_all(c, rid)
    code, out = c.call("POST", f"/api/reviews/{rid}/sign", {})
    assert code == 403 and out["reauth"] is True and server.db.conn().execute("SELECT status FROM reviews WHERE ecg_id=?", (rid,)).fetchone()[0] != "signed"
    code, out = c.call("POST", f"/api/reviews/{rid}/sign", {"password": "wrong password!"})
    assert code == 403 and out["reauth"] is True
    assert c.call("POST", f"/api/reviews/{rid}/sign", {"password": PASSWORD}, expect=200)[1]["status"] == "signed"
    assert any(a[1] == "Signed ECG report" and "confirmed by password" in a[2] for a in _actions(server))
    assert any(a[1] == "Signature confirmation failed" for a in _actions(server))


def test_wrong_confirmations_lock_the_account_like_sign_in(server, ecg):
    t, c, rid = _signable(server, ecg)
    _decide_all(c, rid)
    for _ in range(4):
        assert c.call("POST", f"/api/reviews/{rid}/sign", {"password": "nope nope nope"})[0] == 403
    assert c.call("POST", f"/api/reviews/{rid}/sign", {"password": "nope nope nope"})[0] == 401  # fifth: locked, sessions ended
    assert Client(server.base).login("arao")[0] == 401


def test_two_factor_code_confirms_a_signature(server, ecg):
    from cardiotic_server import sso
    t, c, rid = _signable(server, ecg)
    _decide_all(c, rid)
    secret = c.call("POST", "/api/me/totp/setup", {}, expect=200)[1]["secret"]
    step = int(time.time() // 30)
    code = sso.totp_at(secret, step)
    c.call("POST", "/api/me/totp/enable", {"code": code}, expect=200)
    later = sso.totp_at(secret, step + 1)
    assert c.call("POST", f"/api/reviews/{rid}/sign", {"code": later}, expect=200)[1]["status"] == "signed"
    assert any("confirmed by two-factor code" in a[2] for a in _actions(server))


def test_admin_can_turn_confirmation_off_but_not_others(server, ecg):
    assert client(server, "arao").call("PUT", "/api/settings", {"signReauth": False})[0] == 403
    client(server, "kdesai").call("PUT", "/api/settings", {"signReauth": False}, expect=200)
    t, c, rid = _signable(server, ecg)
    _decide_all(c, rid)
    assert c.call("POST", f"/api/reviews/{rid}/sign", {}, expect=200)[1]["status"] == "signed"


# ------------------------------------------------------------------ passwords
def test_admin_created_accounts_must_choose_their_own_password(server):
    a = client(server, "kdesai")
    a.call("POST", "/api/users", {"username": "newdoc", "name": "New Doc", "role": "cardiologist", "password": "Temporary-pass-1"}, expect=201)
    n = Client(server.base)
    out = n.login("newdoc", "Temporary-pass-1")[1]
    assert out["user"]["change_password"] is True
    assert n.call("GET", "/api/catalog")[0] == 403  # nothing opens before the change
    assert n.call("GET", "/api/me", expect=200)[1]["user"]["change_password"] is True
    assert n.call("POST", "/api/me/password", {"current": "wrong", "new": "A-brand-new-pass-9"})[0] == 403
    assert n.call("POST", "/api/me/password", {"current": "Temporary-pass-1", "new": "Temporary-pass-1"})[0] == 400  # same as the old one
    assert n.call("POST", "/api/me/password", {"current": "Temporary-pass-1", "new": "short"})[0] == 400
    n.call("POST", "/api/me/password", {"current": "Temporary-pass-1", "new": "A-brand-new-pass-9"}, expect=200)
    n.call("GET", "/api/catalog", expect=200)
    assert Client(server.base).login("newdoc", "Temporary-pass-1")[0] == 401
    assert Client(server.base).login("newdoc", "A-brand-new-pass-9")[0] == 200


def test_password_history_blocks_reuse_of_the_last_five(server):
    a = client(server, "kdesai")
    a.call("POST", "/api/users", {"username": "h1", "name": "H One", "role": "technician", "password": "Start-pass-number-0"}, expect=201)
    n = Client(server.base)
    cur = "Start-pass-number-0"
    n.login("h1", cur)
    for i in range(1, 4):
        new = f"Pass-number-{i}-ok-ok"
        n.call("POST", "/api/me/password", {"current": cur, "new": new}, expect=200)
        cur = new
    assert n.call("POST", "/api/me/password", {"current": cur, "new": "Start-pass-number-0"})[0] == 400


def test_expired_password_forces_a_change(server):
    client(server, "kdesai").call("PUT", "/api/auth-settings", {"password_max_days": 30}, expect=200)
    server.db.conn().execute("UPDATE users SET pw_changed=? WHERE username='rsawant'", (time.time() - 40 * 86400,))
    c = Client(server.base)
    assert c.login("rsawant")[1]["user"]["change_password"] is True
    assert client(server, "arao").call("GET", "/api/me")[1]["user"]["change_password"] is False  # arao's password is new


def test_admin_reset_requires_a_change_at_next_sign_in(server):
    client(server, "kdesai").call("PATCH", "/api/users/rsawant", {"password": "Reset-by-admin-1"}, expect=200)
    assert Client(server.base).login("rsawant", "Reset-by-admin-1")[1]["user"]["change_password"] is True


# ------------------------------------------------------------------ per-address rate limit
def test_one_address_cannot_try_many_accounts(server, monkeypatch):
    lim = security.LoginLimiter(limit=4, window=600, block=900)
    monkeypatch.setattr("cardiotic_server.app.security.LoginLimiter", lambda: lim, raising=False)
    # the running server already has its limiter; exercise the class directly and through the endpoint with a small custom one
    for i in range(4):
        assert lim.failed("1.2.3.4") is False
    assert lim.failed("1.2.3.4") is True
    with pytest.raises(security.RateLimited):
        lim.check("1.2.3.4")
    lim.check("5.6.7.8")  # others are unaffected


def test_endpoint_returns_429_after_many_failures(tmp_path, engine, monkeypatch):
    import threading
    monkeypatch.setattr(security, "LIMIT", 3)
    from cardiotic_server.app import make_app
    httpd, store, _ = make_app(tmp_path / "r.db", None, engine, "127.0.0.1", 0, start_worker=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        c = Client(base)
        codes = [c.call("POST", "/api/login", {"username": f"nobody{i}", "password": "x" * 12})[0] for i in range(6)]
        assert codes[:3] == [401, 401, 401] and 429 in codes
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_forwarded_for_is_trusted_only_from_a_proxy():
    proxies = security.parse_networks(["10.0.0.5"])
    assert security.client_ip("10.0.0.5", "203.0.113.9", proxies) == "203.0.113.9"
    assert security.client_ip("198.51.100.7", "203.0.113.9", proxies) == "198.51.100.7"  # a stranger cannot pick its own address
    assert security.client_ip("10.0.0.5", "203.0.113.9, 192.0.2.1", proxies) == "192.0.2.1"  # the entry the proxy added
    assert security.client_ip("10.0.0.5", "not-an-ip", proxies) == "10.0.0.5"


# ------------------------------------------------------------------ allow-lists and TLS
def test_network_allow_list_parsing_and_matching():
    nets = security.parse_networks(["10.1.2.3", "192.168.0.0/16"])
    assert security.address_allowed("10.1.2.3", nets) and security.address_allowed("192.168.4.5", nets)
    assert not security.address_allowed("10.1.2.4", nets) and not security.address_allowed("garbage", nets)
    assert security.address_allowed("::ffff:10.1.2.3", nets)
    assert security.address_allowed("8.8.8.8", [])  # empty: the hospital firewall decides
    with pytest.raises(ValueError, match="not an IP"):
        security.parse_networks(["10.1.2"])


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _mllp(port, text="MSH|^~\\&|X|Y|CARDIOTIC||20260101||ADT^A04|C1|P|2.5.1\rPID|1||UH-1||Doe^Jo||19800101|F\r", ctx=None):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        s = ctx.wrap_socket(raw, server_hostname="localhost") if ctx else raw
        s.settimeout(5)
        s.sendall(b"\x0b" + text.encode() + b"\x1c\x0d")
        try:
            return s.recv(4096)
        except OSError:
            return b""


def test_hl7_listener_refuses_senders_outside_the_allow_list(server):
    port = _free_port()
    server.hl7in.apply({"enabled": True, "port": port, "host": "127.0.0.1", "allowed_hosts": ["10.9.9.9"]})
    try:
        assert _mllp(port) == b""  # connection dropped without an answer
        assert any(a[1] == "HL7 connection refused" for a in _actions(server))
        server.hl7in.apply({"enabled": True, "port": port, "host": "127.0.0.1", "allowed_hosts": ["127.0.0.1"]})
        assert b"MSA|AA" in _mllp(port)
    finally:
        server.hl7in.stop()


@pytest.fixture()
def certs(tmp_path):
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .sign(key, hashes.SHA256()))
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return {"cert": str(tmp_path / "c.pem"), "key": str(tmp_path / "k.pem"), "ca": str(tmp_path / "c.pem")}


def test_hl7_over_tls(server, certs):
    import ssl
    port = _free_port()
    server.hl7in.apply({"enabled": True, "port": port, "host": "127.0.0.1", "tls": {"enabled": True, "cert": certs["cert"], "key": certs["key"]}})
    try:
        ctx = ssl.create_default_context(cafile=certs["ca"])
        assert b"MSA|AA" in _mllp(port, ctx=ctx)
        assert _mllp(port) == b""  # plain text to a TLS port is not answered
    finally:
        server.hl7in.stop()


def test_outbound_mllp_over_tls_reaches_a_tls_his(server, certs):
    import socketserver
    import ssl
    import threading

    from cardiotic_server import export
    seen = []

    class H(socketserver.BaseRequestHandler):
        def handle(self):
            buf = self.request.recv(65536)
            seen.append(buf)
            self.request.sendall(b"\x0bMSH|^~\\&|HIS||||||ACK|A1|P|2.5.1\rMSA|AA|C1\r\x1c\x0d")

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        def get_request(self):
            sock, addr = super().get_request()
            return ctx.wrap_socket(sock, server_side=True), addr

    ctx = security.server_tls_context({"enabled": True, "cert": certs["cert"], "key": certs["key"]})
    srv = S(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client_ctx = security.client_tls_context({"enabled": True, "ca": certs["ca"], "verify_hostname": False})
        ok, text = export.send_mllp("127.0.0.1", srv.server_address[1], "MSH|^~\\&|A|B|C|D|20260101||ORU^R01|C1|P|2.5.1\r", tls=client_ctx)
        assert ok and seen and b"ORU^R01" in seen[0]
        with pytest.raises(OSError):  # a client that does not trust the certificate cannot send
            export.send_mllp("127.0.0.1", srv.server_address[1], "MSH|x\r", tls=security.client_tls_context({"enabled": True, "verify_hostname": True}))
    finally:
        srv.shutdown()
        srv.server_close()


def test_settings_reject_bad_allow_list_and_missing_tls_files(server):
    a = client(server, "kdesai")
    assert a.call("PUT", "/api/feeds", {"folders": [], "dicom": {"enabled": False, "allowed_hosts": ["10.1.2"]}})[0] == 400
    code, out = a.call("PUT", "/api/his", {"enabled": False, "inbound": {"enabled": True, "port": _free_port(), "tls": {"enabled": True, "cert": "/nope/c.pem", "key": "/nope/k.pem"}}})
    assert code == 400 and "TLS cert file not found" in out["error"]
    code, out = a.call("PUT", "/api/his", {"enabled": False, "tls": {"enabled": True, "cert": "relative.pem"}})
    assert code == 400 and "absolute" in out["error"]


def test_dicom_allow_list_by_ae_title_and_address(server, ecg):
    pytest.importorskip("pynetdicom")
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification
    port = _free_port()
    server.dicom.apply({"enabled": True, "port": port, "ae_title": "CARDIOTIC", "host": "127.0.0.1", "allowed_ae_titles": ["CART1"]})
    try:
        def echo(aet):
            ae = AE(ae_title=aet)
            ae.add_requested_context(Verification)
            a = ae.associate("127.0.0.1", port)
            ok = a.is_established
            if ok:
                a.release()
            return ok
        assert echo("CART1") and not echo("INTRUDER")
    finally:
        server.dicom.stop()
    server.dicom.apply({"enabled": True, "port": port, "ae_title": "CARDIOTIC", "host": "127.0.0.1", "allowed_hosts": ["10.9.9.9"]})
    try:
        assert not echo_addr(port)
        assert any(a[1] == "DICOM connection refused" for a in _actions(server))
    finally:
        server.dicom.stop()


def echo_addr(port):
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification
    ae = AE(ae_title="CART1")
    ae.add_requested_context(Verification)
    a = ae.associate("127.0.0.1", port)
    if a.is_established:
        a.release()
        return True
    return False


# ------------------------------------------------------------------ critical-result notifications
CRIT = {"statements": [{"statement": "AFIB"}], "m": {"heart_rate_bpm": 130}}


SHARED = json.loads((Path(__file__).resolve().parents[2] / "shared" / "triage-cases.json").read_text())


@pytest.mark.parametrize("case", SHARED, ids=lambda c: "+".join(c["statements"]) + str(c["m"]))
def test_server_triage_matches_the_shared_cases(case):
    """frontend/tests/clinical.test.ts runs the same file through the web app's rules: the two implementations cannot drift apart."""
    out = triage([{"statement": s} for s in case["statements"]], case["m"])
    assert out["priority"] == case["priority"]
    if "reason" in case:
        assert out["reason"] == case["reason"]


def test_critical_upload_raises_a_notification_that_can_be_acknowledged(server, ecg, monkeypatch):
    import cardiotic_server.store as st
    monkeypatch.setattr("cardiotic_server.triage.triage", lambda *a, **k: {"priority": "critical", "reason": "Rate 160 bpm"})
    t = client(server, "rsawant")
    rec = upload(t, ecg, "dicom", **{"X-Location": "Ward 4"})[1]
    c = client(server, "arao")
    items = c.call("GET", "/api/notifications", expect=200)[1]["items"]
    assert len(items) == 1 and items[0]["recording_id"] == rec["id"] and items[0]["level"] == "critical" and items[0]["location"] == "Ward 4"
    assert client(server, "kdesai").call("GET", "/api/notifications")[1]["items"] == []  # admins do not read ECGs
    c.call("POST", f"/api/notifications/{items[0]['id']}/ack", {}, expect=200)
    assert c.call("GET", "/api/notifications")[1]["items"] == []
    assert any(a[1] == "Acknowledged critical result notification" for a in _actions(server))
    assert client(server, "kdesai").call("GET", "/api/notifications/history", expect=200)[1][0]["acknowledged_by"] == "Dr. Ananya Rao"


def test_notification_email_has_no_patient_data_and_retries(server, ecg, monkeypatch):
    monkeypatch.setattr("cardiotic_server.triage.triage", lambda *a, **k: {"priority": "critical", "reason": "QTc 520 ms"})
    a = client(server, "kdesai")
    a.call("PUT", "/api/notify-settings", {"email": {"enabled": True, "host": "mail.local", "sender": "ecg@h.org", "to": ["oncall@h.org"]}, "app_url": "https://ecg.h.org"}, expect=200)
    assert a.call("GET", "/api/notify-settings")[1]["email"]["password"] == ""
    upload(client(server, "rsawant"), ecg, "dicom", mrn="UH-SECRET-1")
    sent, calls = [], []

    def flaky(cfg, msg):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("mail server down")
        sent.append(msg)

    m = notify.Mailer(server, sender=flaky)
    assert m.run_once() == 0
    row = server.db.conn().execute("SELECT email_status, email_attempts, email_error FROM notifications").fetchone()
    assert row["email_status"] == "pending" and row["email_attempts"] == 1 and "mail server down" in row["email_error"]
    m._next.clear()
    assert m.run_once() == 1
    body = sent[0].get_content() + sent[0]["Subject"]
    assert "CRITICAL" in sent[0]["Subject"] and "QTc 520 ms" in body and "https://ecg.h.org/ecg/E000001" in body
    assert "UH-SECRET-1" not in body and "Unidentified" not in body
    assert server.db.conn().execute("SELECT email_status FROM notifications").fetchone()[0] == "sent"


def test_notify_settings_validation_and_roles(server):
    a = client(server, "kdesai")
    assert client(server, "arao").call("GET", "/api/notify-settings")[0] == 403
    assert a.call("PUT", "/api/notify-settings", {"email": {"enabled": True, "host": "", "sender": "x@y", "to": []}})[0] == 400
    assert a.call("PUT", "/api/notify-settings", {"email": {"enabled": True, "host": "m", "sender": "bad", "to": ["a@b.c"]}})[0] == 400
    assert a.call("PUT", "/api/notify-settings", {"app_url": "ftp://x"})[0] == 400
    assert a.call("PUT", "/api/notify-settings", {"levels": ["critical", "urgent"], "sound": False}, expect=200)[1]["levels"] == ["critical", "urgent"]


# ------------------------------------------------------------------ review history
def test_review_history_keeps_every_version_and_shows_what_changed(server, ecg):
    t, c, rid = _signable(server, ecg)
    findings = [s["statement"] for s in c.call("GET", f"/api/ecg/{rid}")[1]["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {f: "accepted" for f in findings}}, expect=200)
    c.call("PUT", f"/api/reviews/{rid}", {"note": "Rate control advised"}, expect=200)
    c.call("POST", f"/api/reviews/{rid}/sign", {"password": PASSWORD}, expect=200)
    c.call("PUT", f"/api/reviews/{rid}", {"status": "in_review"}, expect=200)  # amendment
    c.call("PUT", f"/api/reviews/{rid}", {"decisions": {findings[0]: "rejected"}}, expect=200) if findings else None
    h = c.call("GET", f"/api/reviews/{rid}/history", expect=200)[1]
    assert [x["version"] for x in h] == sorted(x["version"] for x in h) and len(h) >= 5
    changes = [ch for x in h for ch in x["changes"]]
    assert any(ch.startswith(("signed by Dr. Ananya Rao")) for ch in changes)
    assert any("signature of Dr. Ananya Rao removed (amendment)" in ch for ch in changes)
    assert "note changed" in changes
    assert t.call("GET", f"/api/reviews/{rid}/history", expect=200)  # technicians may read the trail
    assert client(server, "kdesai").call("GET", "/api/reviews/E999999/history")[0] == 404
