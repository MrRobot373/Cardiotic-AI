import base64
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cardiotic_server import auth, sso
from cardiotic_server.db import Database
from helpers import Client


def _code(secret, offset=0):
    return sso.totp_at(secret, int(time.time() // 30) + offset)


# ------------------------------------------------------------------ two-factor
def test_totp_enrol_then_required_at_sign_in(server):
    c = Client(server.base)
    c.login("arao")
    setup = c.call("POST", "/api/me/totp/setup", {}, expect=200)[1]
    assert setup["uri"].startswith("otpauth://totp/") and "issuer=" in setup["uri"]
    assert c.call("POST", "/api/me/totp/enable", {"code": "000000"})[0] == 400
    c.call("POST", "/api/me/totp/enable", {"code": _code(setup["secret"])}, expect=200)
    assert c.call("GET", "/api/me")[1]["user"]["two_factor"] is True
    # next sign-in: password, then code
    n = Client(server.base)
    code, out = n.login("arao")
    assert code == 200 and out["totp_required"] and "token" not in out
    assert n.call("GET", "/api/catalog")[0] == 401  # no session yet
    assert n.call("POST", "/api/login/totp", {"challenge": out["challenge"], "code": "123456"})[0] == 401
    time.sleep(0)  # a fresh code (the enrolment one was used and cannot be replayed)
    res = n.call("POST", "/api/login/totp", {"challenge": out["challenge"], "code": _code(setup["secret"], 1)}, expect=200)[1]
    n.token = res["token"]
    assert n.call("GET", "/api/catalog")[0] == 200
    # the same code cannot be used twice
    m = Client(server.base)
    ch = m.login("arao")[1]["challenge"]
    assert m.call("POST", "/api/login/totp", {"challenge": ch, "code": _code(setup["secret"], 1)})[0] == 401
    # an administrator can reset it (lost phone)
    a = Client(server.base); a.login("kdesai")
    a.call("PATCH", "/api/users/arao", {"reset_totp": True}, expect=200)
    assert "token" in Client(server.base).login("arao")[1]


def test_required_2fa_limits_a_new_session_to_enrolment(server):
    server.db.set_setting("auth", {"require_2fa": True})
    c = Client(server.base)
    out = c.login("rsawant")[1]
    assert out["user"]["enrol_2fa"] is True
    code, err = c.call("GET", "/api/catalog")
    assert code == 403 and "two-factor" in err["error"]
    secret = c.call("POST", "/api/me/totp/setup", {}, expect=200)[1]["secret"]
    c.call("POST", "/api/me/totp/enable", {"code": _code(secret)}, expect=200)
    assert c.call("GET", "/api/catalog")[0] == 200


def test_rfc6238_vector_and_clock_drift():
    s = base64.b32encode(b"12345678901234567890").decode()
    assert sso.totp_at(s, 59 // 30) == "287082" and sso.totp_at(s, 1111111109 // 30) == "081804"
    step = sso.totp_verify(s, sso.totp_at(s, 1000), 0, at=1000 * 30 + 15)
    assert step == 1000 and sso.totp_verify(s, sso.totp_at(s, 1001), 0, at=1000 * 30 + 15) == 1001
    assert sso.totp_verify(s, sso.totp_at(s, 1003), 0, at=1000 * 30) is None
    assert sso.totp_verify(s, sso.totp_at(s, 1000), 1000, at=1000 * 30) is None  # replay


# ------------------------------------------------------------------ LDAP / Active Directory (ldap3 mock directory)
def _mock_directory():
    import ldap3
    srv = ldap3.Server("mock-dc")
    conn = ldap3.Connection(srv, "cn=svc,dc=hosp,dc=local", "svc-pass", client_strategy=ldap3.MOCK_SYNC)
    conn.strategy.add_entry("cn=svc,dc=hosp,dc=local", {"userPassword": "svc-pass", "objectClass": "person"})
    conn.strategy.add_entry("cn=Priya Nair,ou=people,dc=hosp,dc=local", {
        "userPassword": "Dir-Pass-2026", "sAMAccountName": "pnair", "cn": "Priya Nair", "displayName": "Dr. Priya Nair", "title": "Consultant cardiologist",
        "memberOf": ["CN=ECG-Readers,OU=Groups,DC=hosp,DC=local", "CN=Staff,OU=Groups,DC=hosp,DC=local"], "objectClass": "person"})
    conn.strategy.add_entry("cn=Nobody,ou=people,dc=hosp,dc=local", {
        "userPassword": "Other-Pass-2026", "sAMAccountName": "nobody", "cn": "Nobody", "memberOf": ["CN=Staff,OU=Groups,DC=hosp,DC=local"], "objectClass": "person"})
    conn.bind()
    return srv, ldap3.MOCK_SYNC


LDAP_CFG = {"enabled": True, "url": "ldaps://dc.hosp.local", "bind_dn": "cn=svc,dc=hosp,dc=local", "bind_password": "svc-pass", "base_dn": "ou=people,dc=hosp,dc=local",
            "user_filter": "(sAMAccountName={username})", "role_groups": {"cardiologist": "CN=ECG-Readers,OU=Groups,DC=hosp,DC=local"}}


def test_ldap_directory_sign_in_maps_groups_to_roles(server, monkeypatch):
    srv, strat = _mock_directory()
    server.db.set_setting("auth", {"ldap": LDAP_CFG})
    real = auth.login
    monkeypatch.setattr(auth, "login", lambda db, u, p, ldap_options=None: real(db, u, p, {"server": srv, "strategy": strat}))
    c = Client(server.base)
    code, out = c.login("pnair", "Dir-Pass-2026")
    assert code == 200 and out["user"]["role"] == "cardiologist" and out["user"]["name"] == "Dr. Priya Nair" and out["user"]["source"] == "ldap"
    assert Client(server.base).login("pnair", "wrong-password-1")[0] == 401
    assert Client(server.base).login("nobody", "Other-Pass-2026")[0] == 401  # in the directory, but no Cardiotic role
    assert Client(server.base).login("ghost", "whatever-123")[0] == 401
    assert Client(server.base).login("arao")[0] == 200  # local accounts keep working
    users = {u["username"]: u for u in (lambda a: (a.login("kdesai"), a.call("GET", "/api/users")[1])[1])(Client(server.base))}
    assert users["pnair"]["source"] == "ldap" and "nobody" not in users
    with pytest.raises(ValueError, match="no such local user"):
        auth.set_password(server.db, "pnair", "a-long-password-1")


def test_ldap_unreachable_is_reported_as_such(server):
    server.db.set_setting("auth", {"ldap": {**LDAP_CFG, "url": "ldap://127.0.0.1:1"}})
    code, out = Client(server.base).login("pnair", "Dir-Pass-2026")
    assert code == 401 and "directory cannot be reached" in out["error"]


# ------------------------------------------------------------------ OpenID Connect (a real flow against a test identity provider)
class FakeIdP:
    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes, self.claims_extra = {}, {}
        idp = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _json(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_GET(self):
                if self.path == "/.well-known/openid-configuration":
                    return self._json({"issuer": idp.issuer, "authorization_endpoint": idp.issuer + "/authorize", "token_endpoint": idp.issuer + "/token", "jwks_uri": idp.issuer + "/jwks"})
                if self.path == "/jwks":
                    n = idp.key.public_key().public_numbers()
                    enc = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).decode().rstrip("=")  # noqa: E731
                    return self._json({"keys": [{"kty": "RSA", "kid": "k1", "n": enc(n.n), "e": enc(n.e), "alg": "RS256"}]})
                self._json({}, 404)

            def do_POST(self):
                form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
                saved = idp.codes.pop(form.get("code"), None)
                import hashlib
                ok = saved and base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=") == saved["challenge"] and form["client_secret"] == "s3cret"
                if not ok:
                    return self._json({"error": "invalid_grant"}, 400)
                return self._json({"id_token": idp.sign({"iss": idp.issuer, "aud": "cardiotic", "sub": "u-77", "preferred_username": "vsharma", "name": "Dr. Vivek Sharma",
                                                         "roles": ["ECG.Cardiologist"], "nonce": saved["nonce"], "exp": time.time() + 300, **idp.claims_extra})})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.issuer = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def sign(self, claims):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
        h, p = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode()), b64(json.dumps(claims).encode())
        return f"{h}.{p}.{b64(self.key.sign(f'{h}.{p}'.encode(), padding.PKCS1v15(), hashes.SHA256()))}"

    def authorize(self, url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        code = f"code-{len(self.codes)}"
        self.codes[code] = {"challenge": q["code_challenge"], "nonce": q["nonce"]}
        return code, q["state"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        r = opener.open(url)
        return r.status, r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers


def test_oidc_sign_in_end_to_end(server):
    sso._cache.clear()
    idp = FakeIdP()
    try:
        server.db.set_setting("auth", {"oidc": {"enabled": True, "display_name": "Hospital SSO", "issuer": idp.issuer, "client_id": "cardiotic", "client_secret": "s3cret",
                                                "redirect_uri": server.base + "/api/auth/oidc/callback", "role_claim": "roles", "role_map": {"ECG.Cardiologist": "cardiologist"}}})
        assert json.loads(urllib.request.urlopen(server.base + "/api/health").read())["sso"] == "Hospital SSO"
        code, h = _get(server.base + "/api/auth/oidc/start?next=/ecg/E000001")
        assert code == 302 and h["Location"].startswith(idp.issuer + "/authorize") and "code_challenge_method=S256" in h["Location"]
        auth_code, state = idp.authorize(h["Location"])
        code, h = _get(server.base + f"/api/auth/oidc/callback?code={auth_code}&state={state}")
        assert code == 302 and h["Location"] == "/ecg/E000001" and "HttpOnly" in h["Set-Cookie"]
        cookie = h["Set-Cookie"].split(";")[0]
        me = json.loads(urllib.request.urlopen(urllib.request.Request(server.base + "/api/me", headers={"Cookie": cookie})).read())["user"]
        assert me["username"] == "vsharma" and me["role"] == "cardiologist" and me["source"] == "oidc"
        # a replayed state, a forged token, a wrong nonce and an unmapped role are all refused
        code, h = _get(server.base + f"/api/auth/oidc/callback?code={auth_code}&state={state}")
        assert code == 302 and h["Location"].startswith("/login?error=")
        for extra, msg in (({"roles": ["Visitor"]}, "no Cardiotic AI role"), ({"aud": "other-app"}, "another application"), ({"exp": time.time() - 3600}, "expired")):
            idp.claims_extra = extra
            _, h = _get(server.base + "/api/auth/oidc/start")
            c2, st2 = idp.authorize(h["Location"])
            _, h = _get(server.base + f"/api/auth/oidc/callback?code={c2}&state={st2}")
            assert urllib.parse.unquote(h["Location"]).find(msg) > 0, (extra, h["Location"])
        idp.claims_extra = {}
        good = idp.sign({"iss": idp.issuer, "aud": "cardiotic", "nonce": "n", "exp": time.time() + 60})
        forged = good.rsplit(".", 1)[0] + "." + base64.urlsafe_b64encode(b"x" * 256).decode().rstrip("=")
        with pytest.raises(ValueError, match="signature"):
            sso.verify_id_token(server.db.get_setting("auth")["oidc"], forged, "n")
        with pytest.raises(ValueError, match="nonce"):
            sso.verify_id_token(server.db.get_setting("auth")["oidc"], good, "other")
    finally:
        idp.httpd.shutdown()


def test_auth_settings_validation_and_masking(server):
    a = Client(server.base); a.login("kdesai")
    assert Client(server.base).call("GET", "/api/auth-settings")[0] == 401
    assert a.call("PUT", "/api/auth-settings", {"ldap": {"enabled": True, "url": "ldaps://x"}})[0] == 400
    a.call("PUT", "/api/auth-settings", {"ldap": LDAP_CFG}, expect=200)
    got = a.call("GET", "/api/auth-settings")[1]
    assert got["ldap"]["bind_password"] == "********"
    a.call("PUT", "/api/auth-settings", {"ldap": got["ldap"], "require_2fa": True}, expect=200)  # saving the masked value keeps the secret
    assert server.db.get_setting("auth")["ldap"]["bind_password"] == "svc-pass"


def test_database_from_version_1_is_upgraded(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL); INSERT INTO meta VALUES ('schema_version','1');
      CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
        pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
      CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL, last_seen REAL NOT NULL, expires REAL NOT NULL);""")
    c.execute("INSERT INTO users(username, name, role, pw_hash, created_at) VALUES ('old','Old User','admin',?, 'x')", (auth.hash_password("an-old-password-1"),))
    c.commit(); c.close()
    db = Database(path)
    assert db.conn().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    assert auth.login(db, "old", "an-old-password-1")["user"]["source"] == "local"
