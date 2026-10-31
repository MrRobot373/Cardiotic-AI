"""HTTP API and web app host (standard library). Put TLS in front (the hospital's reverse proxy, or set
CARDIOTIC_COOKIE_SECURE=1 behind one): the server speaks plain HTTP on the address it is given.

Sign-in sets an HttpOnly, SameSite=Strict cookie; API clients may send `Authorization: Bearer <token>`.
State-changing requests that authenticate by cookie must carry `X-Requested-With: cardiotic`
(a header a cross-site page cannot add), so another site cannot drive a signed-in browser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cardiotic_engine.api import Engine, InputError

from . import auth, export, feeds, hl7in
from .db import Database
from .store import Conflict, Forbidden, NotFound, Store

log = logging.getLogger("cardiotic_server")
MAX_JSON = 1 << 20
MAX_UPLOAD = int(os.environ.get("CARDIOTIC_MAX_UPLOAD", str(256 * 1024 * 1024)))
COOKIE = "cardiotic_session"
SECURE = os.environ.get("CARDIOTIC_COOKIE_SECURE") == "1"
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"


def _csp_for_page(html: bytes) -> str:
    """The page's own inline scripts (the theme set-up that runs before first paint) are allowed by hash; nothing else inline."""
    hashes = []
    for m in re.finditer(rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.S):
        hashes.append("'sha256-" + base64.b64encode(hashlib.sha256(m.group(1)).digest()).decode() + "'")
    return CSP + ("; script-src 'self' " + " ".join(hashes) if hashes else "")


class HttpError(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message


def _role(user, *roles):
    if user["role"] not in roles:
        raise Forbidden(f"this needs the role: {' or '.join(roles)}")


def make_app(db_path: str | Path, static_dir: str | Path | None = None, engine: Engine | None = None, host: str = "127.0.0.1", port: int = 8720,
             start_worker: bool = True):
    db = Database(db_path)
    store = Store(db, engine or Engine())
    worker = export.Worker(store)
    folders, dicom = feeds.FolderFeeds(store), feeds.DicomFeed(store)
    store.folders, store.dicom = folders, dicom
    store.hl7in = hl7in.Listener(store)
    static = Path(static_dir).resolve() if static_dir else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "cardiotic-server"
        protocol_version = "HTTP/1.1"

        # ------------------------------------------------------------ plumbing
        def log_message(self, fmt, *args):  # request lines only: no bodies, no patient data
            log.info("%s %s", self.address_string(), fmt % args)

        def _headers(self, code, ctype, length, extra=(), csp=CSP):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Frame-Options", "DENY")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()

        def _json(self, code, payload, extra=()):
            body = json.dumps(payload, default=float).encode()
            self._headers(code, "application/json", len(body), [("Cache-Control", "no-store"), *extra])
            self.wfile.write(body)

        def _bytes(self, code, data, ctype, extra=()):
            self._headers(code, ctype, len(data), [("Cache-Control", "no-store"), *extra])
            self.wfile.write(data)

        def _body(self, limit) -> bytes:
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise HttpError(400, "bad Content-Length") from None
            if n < 0:
                raise HttpError(400, "bad Content-Length")
            if n > limit:
                raise HttpError(413, f"body larger than {limit} bytes")
            self._read = True
            return self.rfile.read(n)

        def _json_body(self) -> dict:
            raw = self._body(MAX_JSON)
            try:
                v = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise HttpError(400, "body must be JSON") from None
            if not isinstance(v, dict):
                raise HttpError(400, "body must be a JSON object")
            return v

        def _token(self):
            h = self.headers.get("Authorization", "")
            if h.startswith("Bearer "):
                return h[7:].strip(), "bearer"
            c = SimpleCookie(self.headers.get("Cookie", ""))
            return (c[COOKIE].value, "cookie") if COOKIE in c else (None, None)

        def _user(self, mutating: bool):
            token, how = self._token()
            user = auth.session_user(db, token)
            if mutating and how == "cookie" and self.headers.get("X-Requested-With") != "cardiotic":
                raise HttpError(403, "missing X-Requested-With header")
            self._tok = token
            return user

        def _dispatch(self, method):
            self._read = False
            try:
                self._dispatch_inner(method)
            finally:
                try:
                    self._drain()
                except OSError:
                    self.close_connection = True

        def _drain(self):
            """Keep-alive connections: a body nobody read (logout, a refused upload) must not be parsed as the next request."""
            if self._read:
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n > MAX_JSON or n < 0:
                self.close_connection = True
            elif n > 0:
                self.rfile.read(n)

        def _dispatch_inner(self, method):
            u = urlparse(self.path)
            path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if path.startswith("/api/"):
                    self._api(method, path[4:], q)
                elif method == "GET" and static:
                    self._static(path)
                else:
                    raise HttpError(404, "not found")
            except HttpError as e:
                self._json(e.code, {"error": e.message})
            except auth.AuthError as e:
                self._json(401, {"error": str(e)})
            except Forbidden as e:
                self._json(403, {"error": str(e)})
            except NotFound as e:
                self._json(404, {"error": f"not found: {e}"})
            except Conflict as e:
                self._json(409, {"error": str(e)})
            except (InputError, ValueError) as e:
                self._json(400, {"error": str(e)})
            except (BrokenPipeError, ConnectionResetError):  # the browser went away (page closed or reloaded): nothing to answer
                self.close_connection = True
            except Exception:  # never leak internals or patient data
                log.exception("request failed")
                try:
                    self._json(500, {"error": "internal error; see the server log"})
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

        def do_GET(self): self._dispatch("GET")
        def do_POST(self): self._dispatch("POST")
        def do_PUT(self): self._dispatch("PUT")
        def do_PATCH(self): self._dispatch("PATCH")
        def do_DELETE(self): self._dispatch("DELETE")

        # ------------------------------------------------------------ static web app
        def _static(self, path):
            root = static
            rel = path.lstrip("/") or "index.html"
            f = (root / rel).resolve()
            if root not in f.parents and f != root or not f.is_file():
                f = root / "index.html"  # single-page app: unknown paths go to the app
                if not f.is_file():
                    raise HttpError(404, "web app not installed")
            data = f.read_bytes()
            immutable = "assets/" in rel
            self._headers(200, mimetypes.guess_type(f.name)[0] or "application/octet-stream", len(data),
                          [("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-cache")],
                          csp=_csp_for_page(data) if f.suffix == ".html" else CSP)
            self.wfile.write(data)

        # ------------------------------------------------------------ API
        def _api(self, method, path, q):
            m = re.fullmatch
            if method == "GET" and path == "/health":
                oidc = db.get_setting("auth", {}).get("oidc", {})
                return self._json(200, {"status": "ok", "models_verified": True, "site_name": store.site()["siteName"],  # the sign-in page shows these
                                        "sso": oidc.get("display_name") or "single sign-on" if oidc.get("enabled") else None})
            if method == "POST" and path in ("/login", "/login/totp"):
                b = self._json_body()
                res = (auth.login(db, str(b.get("username", "")), str(b.get("password", ""))) if path == "/login"
                       else auth.login_totp(db, str(b.get("challenge", "")), str(b.get("code", ""))))
                if "token" not in res:
                    return self._json(200, res)
                return self._json(200, res, [("Set-Cookie", self._cookie(res["token"]))])
            if method == "GET" and path == "/auth/oidc/start":
                return self._oidc_start(q)
            if method == "GET" and path == "/auth/oidc/callback":
                return self._oidc_callback(q)
            user = self._user(method != "GET")
            if user.get("scope") == "enrol" and path not in ("/me", "/me/totp/setup", "/me/totp/enable", "/logout"):
                raise Forbidden("set up two-factor sign-in first (required at this hospital)")
            if method == "POST" and path == "/logout":
                auth.logout(db, self._tok, user)
                return self._json(200, {"ok": True}, [("Set-Cookie", f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")])
            if method == "GET" and path == "/me":
                return self._json(200, {"user": {**user, "enrol_2fa": user.get("scope") == "enrol"}, "site": store.site()})
            if method == "POST" and path == "/me/totp/setup":
                return self._json(200, auth.totp_setup(db, user, f"Cardiotic AI ({store.site()['siteName']})"))
            if method == "POST" and path == "/me/totp/enable":
                auth.totp_enable(db, user, str(self._json_body().get("code", "")), self._tok)
                return self._json(200, {"ok": True})
            if path == "/auth-settings":
                _role(user, "admin")
                return self._auth_settings(method, user)
            if method == "GET" and path == "/models":
                return self._json(200, store.engine.info())
            if method == "GET" and path == "/catalog":
                return self._json(200, store.catalog())
            if method == "GET" and (g := m(r"/ecg/(E\d+)", path)):
                return self._json(200, store.recording(g[1], "ecg12"))
            if method == "GET" and (g := m(r"/holter/(H\d+)", path)):
                return self._json(200, store.recording(g[1], "holter"))
            if method == "GET" and (g := m(r"/holter/(H\d+)/signal", path)):
                return self._bytes(200, store.holter_signal(g[1]), "application/octet-stream")
            if method == "GET" and path == "/reviews":
                return self._json(200, store.reviews())
            if (g := m(r"/reviews/([EH]\d+)", path)):
                if method == "GET":
                    return self._json(200, store.review(g[1]))
                if method == "PUT":
                    b = self._json_body()
                    return self._json(200, store.update_review(user, g[1], {k: v for k, v in b.items() if k not in ("version", "audit")}, b.get("version"), b["audit"][:100] if isinstance(b.get("audit"), str) else None))
            if method == "POST" and (g := m(r"/reviews/([EH]\d+)/sign", path)):
                b = self._json_body()
                return self._json(200, store.sign(user, g[1], b.get("note"), b.get("version")))
            if method == "POST" and path == "/upload":
                data = self._body(MAX_UPLOAD)
                if not data:
                    raise HttpError(400, "the request body must be the ECG file")
                h = self.headers
                fs = h.get("X-Fs")
                try:
                    fs = float(fs) if fs else None
                except ValueError:
                    raise HttpError(400, "X-Fs must be a number") from None
                rec = store.add_file(user, data, filename=os.path.basename(h.get("X-Filename", ""))[:200], fs=fs, units=h.get("X-Units"), mrn=h.get("X-Patient-MRN"),
                                     location=h.get("X-Location", "")[:100], ordered_by=h.get("X-Ordered-By", "")[:100])
                return self._json(201, rec)
            if method == "POST" and path == "/patients":
                b = self._json_body()
                return self._json(201, store.create_patient(user, str(b.get("mrn", "")), str(b.get("name", "")), str(b.get("sex", "")), b.get("birth_date")))
            if method == "POST" and (g := m(r"/recordings/([EH]\d+)/patient", path)):
                return self._json(200, store.assign_patient(user, g[1], str(self._json_body().get("mrn", ""))))
            if method == "GET" and path == "/audit":
                _role(user, "admin", "cardiologist")
                rows = db.conn().execute("SELECT at, user, action, target FROM audit ORDER BY id DESC LIMIT ?", (min(int(q.get("limit", 300)), 2000),)).fetchall()
                return self._json(200, [dict(r) for r in rows])
            if method == "GET" and path == "/audit/verify":
                _role(user, "admin")
                return self._json(200, db.verify_audit())
            if method == "GET" and path == "/settings":
                return self._json(200, store.site())
            if method == "PUT" and path == "/settings":
                return self._json(200, store.update_site(user, self._json_body()))
            if path == "/his":
                _role(user, "admin")
                if method == "GET":
                    return self._json(200, db.get_setting("his", {"enabled": False}))
                if method == "PUT":
                    b = self._json_body()
                    inb = b.get("inbound", {}) if isinstance(b.get("inbound"), dict) else {}
                    his = {"enabled": bool(b.get("enabled")), "host": str(b.get("host", "")).strip(), "port": int(b.get("port", 2575)), "facility": str(b.get("facility", ""))[:40],
                           "application": str(b.get("application", "HIS"))[:40], "attach_pdf": bool(b.get("attach_pdf", True)),
                           "inbound": {"enabled": bool(inb.get("enabled")), "port": int(inb.get("port", 2576))}}
                    if not 0 < his["inbound"]["port"] < 65536:
                        raise ValueError("inbound port must be 1-65535")
                    if his["enabled"] and not his["host"]:
                        raise ValueError("host is required to enable the HIS connection")
                    if not 0 < his["port"] < 65536:
                        raise ValueError("port must be 1-65535")
                    db.set_setting("his", his)
                    try:
                        store.hl7in.apply(his["inbound"])
                    except OSError as e:
                        raise ValueError(f"HL7 listener could not start on port {his['inbound']['port']}: {e}") from None
                    db.audit(user["name"], "Changed HIS connection", f"{his['host']}:{his['port']} enabled={his['enabled']}")
                    return self._json(200, his)
            if path == "/feeds":
                _role(user, "admin", "technician", "cardiologist")
                if method == "GET":
                    return self._json(200, {**db.get_setting("feeds", {"folders": [], "dicom": {"enabled": False, "port": 11112, "ae_title": "CARDIOTIC"}}),
                                            "status": db.get_setting("feed_status", {}), "dicom_running": store.dicom.server is not None})
                if method == "PUT":
                    _role(user, "admin")
                    b = self._json_body()
                    folders_cfg = []
                    for f in b.get("folders", []):
                        name, fpath = str(f.get("name", "")).strip()[:60], str(f.get("path", "")).strip()
                        if not name or not fpath.startswith("/"):
                            raise ValueError("each folder feed needs a name and an absolute path")
                        folders_cfg.append({"name": name, "path": fpath, "location": str(f.get("location", ""))[:100], "enabled": bool(f.get("enabled", True))})
                    d = b.get("dicom", {})
                    dcfg = {"enabled": bool(d.get("enabled")), "port": int(d.get("port", 11112)), "ae_title": str(d.get("ae_title", "CARDIOTIC"))[:16].upper(),
                            "location": str(d.get("location", ""))[:100]}
                    if not 0 < dcfg["port"] < 65536:
                        raise ValueError("port must be 1-65535")
                    db.set_setting("feeds", {"folders": folders_cfg, "dicom": dcfg})
                    try:
                        store.dicom.apply(dcfg)
                    except OSError as e:
                        raise ValueError(f"DICOM receiver could not start on port {dcfg['port']}: {e}") from None
                    db.audit(user["name"], "Changed machine feeds", f"{len(folders_cfg)} folders, DICOM {'on' if dcfg['enabled'] else 'off'}")
                    return self._json(200, {"ok": True})
            if method == "GET" and path == "/outbox":
                _role(user, "admin", "cardiologist")
                rows = db.conn().execute("SELECT id, ecg_id, kind, status, attempts, last_error, created_at, sent_at FROM outbox ORDER BY id DESC LIMIT 200").fetchall()
                return self._json(200, [dict(r) for r in rows])
            if method == "POST" and (g := m(r"/outbox/(\d+)/retry", path)):
                _role(user, "admin")
                with db.tx() as c:
                    if c.execute("UPDATE outbox SET status='pending', next_try=0 WHERE id=? AND status!='sent'", (int(g[1]),)).rowcount == 0:
                        raise NotFound(g[1])
                    db.audit(user["name"], "Retried HIS delivery", g[1], c)
                return self._json(200, {"ok": True})
            if method == "GET" and (g := m(r"/report/(E\d+)\.pdf", path)):
                try:
                    data = export.report_pdf(store, g[1], allow_draft=True)
                except KeyError:
                    raise NotFound(g[1]) from None
                return self._bytes(200, data, "application/pdf", [("Content-Disposition", f'inline; filename="ECG-report-{g[1]}.pdf"')])
            if method == "GET" and (g := m(r"/report/(E\d+)\.(hl7|fhir\.json)", path)):
                _role(user, "admin", "cardiologist", "technician")
                try:
                    rep = export.report_content(store, g[1])
                except KeyError:
                    raise NotFound(g[1]) from None
                except ValueError as e:
                    raise Conflict(str(e)) from None
                if g[2] == "hl7":
                    his = db.get_setting("his", {})
                    return self._bytes(200, export.hl7_oru(rep, sending_facility=rep["site"][:20], receiving_facility=his.get("facility", ""), receiving_app=his.get("application", "HIS"),
                                                          pdf_bytes=export.report_pdf(store, g[1]) if his.get("attach_pdf", True) else None).encode("latin-1", "replace"), "text/plain; charset=iso-8859-1")
                return self._json(200, export.fhir_bundle(rep, export.report_pdf(store, g[1])))
            if path == "/users" or m(r"/users/[a-z0-9._-]+", path):
                _role(user, "admin")
                return self._users(method, path, user)
            raise HttpError(404, "not found")

        def _cookie(self, token: str) -> str:
            return f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.ABSOLUTE_SECONDS}" + ("; Secure" if SECURE else "")

        def _redirect(self, location: str, extra=()):
            self._headers(302, "text/plain", 0, [("Location", location), ("Cache-Control", "no-store"), *extra])

        def _oidc_start(self, q):
            import secrets as _s
            import time as _t
            from . import sso
            cfg = db.get_setting("auth", {}).get("oidc", {})
            if not cfg.get("enabled"):
                raise HttpError(404, "single sign-on is not configured")
            url, saved = sso.oidc_start(cfg)
            nxt = q.get("next", "/")
            saved["next"] = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
            with db.tx() as c:
                c.execute("DELETE FROM challenges WHERE expires < ?", (_t.time(),))
                c.execute("INSERT INTO challenges(token_hash, kind, data, expires) VALUES (?,?,?,?)", (auth._th(saved["state"]), "oidc", json.dumps(saved), _t.time() + 600))
            return self._redirect(url)

        def _oidc_callback(self, q):
            import time as _t
            from urllib.parse import quote
            from . import sso
            cfg = db.get_setting("auth", {}).get("oidc", {})
            with db.tx() as c:
                row = c.execute("SELECT * FROM challenges WHERE token_hash=? AND kind='oidc'", (auth._th(q.get("state", "")),)).fetchone()
                if row:
                    c.execute("DELETE FROM challenges WHERE token_hash=?", (row["token_hash"],))
            if not cfg.get("enabled") or row is None or row["expires"] < _t.time():
                return self._redirect("/login?error=" + quote("The sign-in expired; try again"))
            if q.get("error"):
                return self._redirect("/login?error=" + quote(f"The identity provider refused: {q.get('error_description') or q['error']}"[:200]))
            saved = json.loads(row["data"])
            try:
                info = sso.oidc_finish(cfg, q.get("code", ""), saved)
                token, _ = auth.oidc_session(db, info)
            except (ValueError, auth.AuthError) as e:
                db.audit("identity provider", "Sign-in refused", str(e)[:120])
                return self._redirect("/login?error=" + quote(str(e)[:200]))
            return self._redirect(saved.get("next", "/"), [("Set-Cookie", self._cookie(token))])

        def _auth_settings(self, method, admin):
            cfg = db.get_setting("auth", {})
            masked = lambda d, k: {**d, k: "********" if d.get(k) else ""}  # noqa: E731
            if method == "GET":
                return self._json(200, {"require_2fa": bool(cfg.get("require_2fa")), "ldap": masked(cfg.get("ldap", {}), "bind_password"),
                                        "oidc": masked(cfg.get("oidc", {}), "client_secret")})
            if method != "PUT":
                raise HttpError(405, "method not allowed")
            b = self._json_body()
            new = {"require_2fa": bool(b.get("require_2fa", cfg.get("require_2fa", False)))}
            for kind, secret in (("ldap", "bind_password"), ("oidc", "client_secret")):
                d = b.get(kind, cfg.get(kind, {})) or {}
                if not isinstance(d, dict):
                    raise ValueError(f"{kind} must be an object")
                if d.get(secret) == "********":
                    d = {**d, secret: cfg.get(kind, {}).get(secret, "")}
                if d.get("enabled"):
                    need = ("url",) if kind == "ldap" else ("issuer", "client_id", "redirect_uri")
                    missing = [k for k in need if not d.get(k)]
                    if kind == "ldap" and not (d.get("user_dn_template") or (d.get("bind_dn") and d.get("base_dn"))):
                        missing.append("user_dn_template or bind_dn + base_dn")
                    if missing:
                        raise ValueError(f"{kind}: missing {', '.join(missing)}")
                    roles = d.get("role_groups" if kind == "ldap" else "role_map", {})
                    if not roles:
                        raise ValueError(f"{kind}: map at least one group or claim value to a role")
                new[kind] = d
            db.set_setting("auth", new)
            db.audit(admin["name"], "Changed sign-in settings", f"2FA required={new['require_2fa']}, LDAP={'on' if new['ldap'].get('enabled') else 'off'}, OIDC={'on' if new['oidc'].get('enabled') else 'off'}")
            return self._json(200, {"ok": True})

        def _users(self, method, path, admin):
            if method == "GET" and path == "/users":
                rows = db.conn().execute("SELECT id, username, name, role, title, active, source, totp_enabled AS two_factor FROM users ORDER BY name").fetchall()
                return self._json(200, [dict(r) for r in rows])
            if method == "POST" and path == "/users":
                b = self._json_body()
                uid = auth.create_user(db, str(b.get("username", "")), str(b.get("name", "")), str(b.get("role", "")), str(b.get("password", "")), str(b.get("title", "")))
                db.audit(admin["name"], "Created user", f"{b.get('username')} ({b.get('role')})")
                return self._json(201, {"id": uid})
            if method == "PATCH":
                uname = path.rsplit("/", 1)[1]
                b = self._json_body()
                if "password" in b:
                    auth.set_password(db, uname, str(b["password"]))
                    db.audit(admin["name"], "Reset password", uname)
                if b.get("reset_totp"):
                    with db.tx() as c:
                        if c.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE username=?", (uname,)).rowcount == 0:
                            raise NotFound(uname)
                        db.audit(admin["name"], "Reset two-factor sign-in", uname, c)
                if "active" in b:
                    if uname == admin["username"] and not b["active"]:
                        raise Conflict("you cannot deactivate your own account")
                    with db.tx() as c:
                        if c.execute("UPDATE users SET active=? WHERE username=?", (1 if b["active"] else 0, uname)).rowcount == 0:
                            raise NotFound(uname)
                        if not b["active"]:
                            c.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=?)", (uname,))
                        db.audit(admin["name"], "Activated user" if b["active"] else "Deactivated user", uname, c)
                return self._json(200, {"ok": True})
            raise HttpError(405, "method not allowed")

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    if start_worker:
        worker.start()
        folders.start()
        try:
            dicom.apply(db.get_setting("feeds", {}).get("dicom", {}))
        except OSError as e:  # port in use: the server still runs; Integrations shows the error
            log.error("DICOM receiver could not start: %s", e)
        try:
            store.hl7in.apply(db.get_setting("his", {}).get("inbound", {}))
        except OSError as e:
            log.error("HL7 listener could not start: %s", e)
    return httpd, store, worker
