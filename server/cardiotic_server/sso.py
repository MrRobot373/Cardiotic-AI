"""Sign-in beyond local passwords: two-factor codes (TOTP, RFC 6238), Active Directory / LDAP, OpenID Connect.

Configuration (Settings → Security, stored in settings "auth"):
  ldap:  {enabled, url, base_dn, user_filter, bind_dn, bind_password | user_dn_template, role_groups: {role: group DN}}
  oidc:  {enabled, display_name, issuer, client_id, client_secret, redirect_uri, role_claim, role_map: {claim value: role}}
  require_2fa: users signing in with a password must use a TOTP code (OIDC sign-ins rely on the provider's MFA)
A directory or provider user gets the role its groups / claims map to; with no mapped role, sign-in is refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
import urllib.parse
import urllib.request

ROLE_ORDER = ("cardiologist", "technician", "admin")  # if several groups match, the first role here wins


# ------------------------------------------------------------------ TOTP (RFC 6238, SHA-1, 6 digits, 30 s)
def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_verify(secret: str, code: str, last_step: int, at: float | None = None) -> int | None:
    """The time step the code belongs to (±1 step for clock drift), or None. Steps at or before last_step
    are refused so a code cannot be used twice."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    now_step = int((at or time.time()) // 30)
    for step in (now_step - 1, now_step, now_step + 1):
        if step > last_step and hmac.compare_digest(totp_at(secret, step), code):
            return step
    return None


def totp_uri(secret: str, username: str, issuer: str) -> str:
    label = urllib.parse.quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits=6&period=30"


# ------------------------------------------------------------------ LDAP / Active Directory
def _role_from_groups(groups: list[str], role_groups: dict[str, str]) -> str | None:
    norm = {g.lower().replace(" ", "") for g in groups}
    for role in ROLE_ORDER:
        dn = role_groups.get(role)
        if dn and dn.lower().replace(" ", "") in norm:
            return role
    return None


def ldap_authenticate(cfg: dict, username: str, password: str, server=None, strategy=None) -> dict | None:
    """Bind as the user; returns {username, name, title, role} or None (wrong password, no mapped role).
    `server`/`strategy` are for tests (ldap3 MOCK_SYNC)."""
    import ldap3
    from ldap3.utils.conv import escape_filter_chars

    if not password:  # an empty password would be an anonymous bind on many directories
        return None
    srv = server or ldap3.Server(cfg["url"], connect_timeout=5, get_info=ldap3.NONE)
    kw = {"client_strategy": strategy} if strategy else {}
    attrs = ["cn", "displayName", "title", "memberOf", "mail"]
    if cfg.get("bind_dn"):  # find the user with a service account, then bind as the user
        svc = ldap3.Connection(srv, cfg["bind_dn"], cfg.get("bind_password", ""), receive_timeout=10, **kw)
        if not svc.bind():
            raise RuntimeError(f"the service account cannot bind to the directory: {svc.result.get('description')}")
        svc.search(cfg["base_dn"], cfg.get("user_filter", "(sAMAccountName={username})").format(username=escape_filter_chars(username)), attributes=attrs)
        if not svc.entries:
            svc.unbind()
            return None
        entry = svc.entries[0]
        user_dn = entry.entry_dn
        svc.unbind()
    else:
        user_dn = cfg["user_dn_template"].format(username=username)
        entry = None
    conn = ldap3.Connection(srv, user_dn, password, receive_timeout=10, **kw)
    if not conn.bind():  # wrong password (or locked in the directory)
        return None
    if entry is None:
        conn.search(user_dn, "(objectClass=*)", search_scope=ldap3.BASE, attributes=attrs)
        entry = conn.entries[0] if conn.entries else None
    conn.unbind()
    if entry is None:
        return None
    vals = entry.entry_attributes_as_dict
    groups = [str(g) for g in vals.get("memberOf", [])]
    role = _role_from_groups(groups, cfg.get("role_groups", {}))
    if role is None:
        return None
    first = lambda k: str(vals[k][0]) if vals.get(k) else ""  # noqa: E731
    return {"username": username.lower(), "name": first("displayName") or first("cn") or username, "title": first("title"), "role": role}


# ------------------------------------------------------------------ OpenID Connect (authorization code + PKCE)
_cache: dict[str, tuple[float, dict]] = {}


def _get_json(url: str, ttl: float = 3600) -> dict:
    hit = _cache.get(url)
    if hit and hit[0] > time.time():
        return hit[1]
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
    _cache[url] = (time.time() + ttl, data)
    return data


def oidc_discovery(cfg: dict) -> dict:
    return _get_json(cfg["issuer"].rstrip("/") + "/.well-known/openid-configuration")


def oidc_start(cfg: dict) -> tuple[str, dict]:
    """(authorize URL, state data to keep server-side)."""
    disc = oidc_discovery(cfg)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    q = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"], "scope": cfg.get("scope", "openid profile email"),
         "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    return disc["authorization_endpoint"] + "?" + urllib.parse.urlencode(q), {"state": state, "nonce": nonce, "verifier": verifier}


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_id_token(cfg: dict, token: str, nonce: str) -> dict:
    """RS256 signature against the provider's keys, then issuer, audience, expiry and nonce."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        h64, p64, s64 = token.split(".")
        header, claims = json.loads(_b64d(h64)), json.loads(_b64d(p64))
    except ValueError:
        raise ValueError("malformed ID token") from None
    if header.get("alg") != "RS256":
        raise ValueError(f"ID token algorithm {header.get('alg')} is not accepted (RS256 only)")
    keys = _get_json(oidc_discovery(cfg)["jwks_uri"])["keys"]
    jwk = next((k for k in keys if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"), None)
    if jwk is None:
        _cache.pop(oidc_discovery(cfg)["jwks_uri"], None)  # the provider may have rotated its keys
        keys = _get_json(oidc_discovery(cfg)["jwks_uri"])["keys"]
        jwk = next((k for k in keys if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"), None)
    if jwk is None:
        raise ValueError("ID token signed with an unknown key")
    pub = rsa.RSAPublicNumbers(int.from_bytes(_b64d(jwk["e"]), "big"), int.from_bytes(_b64d(jwk["n"]), "big")).public_key()
    try:
        pub.verify(_b64d(s64), f"{h64}.{p64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        raise ValueError("ID token signature is not valid") from None
    aud = claims.get("aud")
    if claims.get("iss") != oidc_discovery(cfg)["issuer"]:
        raise ValueError("ID token from another issuer")
    if cfg["client_id"] not in (aud if isinstance(aud, list) else [aud]):
        raise ValueError("ID token for another application")
    if float(claims.get("exp", 0)) < time.time() - 60:
        raise ValueError("ID token expired")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("ID token nonce does not match")
    return claims


def oidc_finish(cfg: dict, code: str, saved: dict) -> dict:
    """Exchange the code; returns {username, name, title, role} or raises ValueError."""
    disc = oidc_discovery(cfg)
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": cfg["redirect_uri"],
                                   "client_id": cfg["client_id"], "client_secret": cfg.get("client_secret", ""), "code_verifier": saved["verifier"]}).encode()
    req = urllib.request.Request(disc["token_endpoint"], data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            tok = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"the identity provider refused the sign-in ({e.code})") from None
    claims = verify_id_token(cfg, tok.get("id_token", ""), saved["nonce"])
    values = claims.get(cfg.get("role_claim", "roles"), [])
    values = values if isinstance(values, list) else [values]
    role_map = cfg.get("role_map", {})
    roles = {role_map[v] for v in map(str, values) if v in role_map}
    role = next((r for r in ROLE_ORDER if r in roles), None)
    if role is None:
        raise ValueError("your account has no Cardiotic AI role; ask the administrator")
    username = str(claims.get("preferred_username") or claims.get("email") or claims["sub"]).lower()
    return {"username": username, "name": str(claims.get("name") or username), "title": "", "role": role}
