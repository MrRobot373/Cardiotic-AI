"""Request-level protections that do not belong to one account: sign-in rate limits per network address,
read-access logging, and network allow-lists for the machine and HIS ports."""

from __future__ import annotations

import ipaddress
import os
import ssl
import threading
import time
from collections import deque

# Sign-in attempts from one address: more than LIMIT failures within WINDOW seconds blocks that address for BLOCK seconds.
# (Accounts have their own lockout; this stops one machine trying many accounts.)
LIMIT, WINDOW, BLOCK = int(os.environ.get("CARDIOTIC_LOGIN_IP_LIMIT", "20")), 600, 900
VIEW_DEDUPE_SECONDS = 300  # the same person re-opening the same record within 5 minutes is one audit entry


class RateLimited(Exception):
    """Too many failed sign-ins from this address (429)."""


class LoginLimiter:
    def __init__(self, limit: int | None = None, window: float | None = None, block: float | None = None):
        self.limit, self.window, self.block = limit or LIMIT, window or WINDOW, block or BLOCK
        self._fails: dict[str, deque] = {}
        self._blocked: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, ip: str) -> None:
        with self._lock:
            until = self._blocked.get(ip, 0)
            if until > time.time():
                raise RateLimited(f"too many failed sign-ins from this computer; try again in {int((until - time.time()) // 60) + 1} minutes")
            if until:
                self._blocked.pop(ip, None)

    def failed(self, ip: str) -> bool:
        """Record a failure; True when the address is now blocked."""
        t = time.time()
        with self._lock:
            q = self._fails.setdefault(ip, deque())
            q.append(t)
            while q and q[0] < t - self.window:
                q.popleft()
            if len(q) > self.limit:
                self._blocked[ip] = t + self.block
                q.clear()
                return True
            if len(self._fails) > 10000:  # bounded memory under a spray from many addresses
                for k in [k for k, v in self._fails.items() if not v or v[-1] < t - self.window]:
                    self._fails.pop(k, None)
            return False

    def succeeded(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


def trusted_proxies() -> list:
    return [ipaddress.ip_network(x.strip(), strict=False) for x in os.environ.get("CARDIOTIC_TRUSTED_PROXIES", "127.0.0.1/32,::1/128").split(",") if x.strip()]


def client_ip(peer: str, forwarded_for: str | None, proxies=None) -> str:
    """The browser's address. X-Forwarded-For is believed only when the connection comes from a trusted reverse proxy
    (CARDIOTIC_TRUSTED_PROXIES, default: this machine), and then only its right-most entry the proxy added."""
    proxies = trusted_proxies() if proxies is None else proxies
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if forwarded_for and any(peer_ip in n for n in proxies):
        last = forwarded_for.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            return peer
    return peer


class ViewLog:
    """Read access to patient data is audited (who opened which recording or report). Repeats inside
    VIEW_DEDUPE_SECONDS are folded into the first entry so the log stays readable."""

    def __init__(self, db, window: float = VIEW_DEDUPE_SECONDS):
        self.db, self.window = db, window
        self._last: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def record(self, user: dict, action: str, target: str) -> bool:
        key, t = (user["username"], action, target), time.time()
        with self._lock:
            if self._last.get(key, 0) > t - self.window:
                return False
            self._last[key] = t
            if len(self._last) > 50000:
                for k in [k for k, v in self._last.items() if v < t - self.window]:
                    self._last.pop(k, None)
        self.db.audit(user["name"], action, target)
        return True


# ---------------------------------------------------------------- network allow-lists (DICOM, HL7)
def parse_networks(values) -> list:
    """['10.1.2.3', '10.20.0.0/16'] -> networks; raises ValueError naming a bad entry."""
    out = []
    for v in values or []:
        v = str(v).strip()
        if not v:
            continue
        try:
            out.append(ipaddress.ip_network(v, strict=False))
        except ValueError:
            raise ValueError(f"{v!r} is not an IP address or network (e.g. 10.1.2.3 or 10.1.0.0/16)") from None
    return out


def address_allowed(addr: str, networks: list) -> bool:
    """An empty list allows every address (the hospital network's firewall decides)."""
    if not networks:
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in networks)


def server_tls_context(cfg: dict) -> ssl.SSLContext | None:
    """TLS for a listening port: {"enabled", "cert", "key", "ca"}; with "ca", senders must present a certificate it signed."""
    if not cfg or not cfg.get("enabled"):
        return None
    for k in ("cert", "key"):
        if not cfg.get(k) or not os.path.isfile(cfg[k]):
            raise ValueError(f"TLS {k} file not found: {cfg.get(k) or '(not set)'}")
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cfg["cert"], cfg["key"])
    if cfg.get("ca"):
        if not os.path.isfile(cfg["ca"]):
            raise ValueError(f"TLS ca file not found: {cfg['ca']}")
        ctx.load_verify_locations(cfg["ca"])
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def client_tls_context(cfg: dict) -> ssl.SSLContext | None:
    """TLS to the HIS: {"enabled", "ca" (trust), "cert"/"key" (our certificate, if the HIS asks), "verify_hostname"}."""
    if not cfg or not cfg.get("enabled"):
        return None
    ctx = ssl.create_default_context(cafile=cfg["ca"] if cfg.get("ca") else None)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = bool(cfg.get("verify_hostname", True))
    if cfg.get("cert") and cfg.get("key"):
        ctx.load_cert_chain(cfg["cert"], cfg["key"])
    return ctx


def tls_settings(d: dict | None) -> dict:
    """Validated TLS block from a settings request (paths are checked when the port starts)."""
    d = d if isinstance(d, dict) else {}
    out = {"enabled": bool(d.get("enabled"))}
    for k in ("cert", "key", "ca"):
        v = str(d.get(k, "")).strip()
        if v and not v.startswith("/"):
            raise ValueError(f"TLS {k} must be an absolute file path")
        out[k] = v
    if "verify_hostname" in d:
        out["verify_hostname"] = bool(d["verify_hostname"])
    if out["enabled"] and "verify_hostname" not in d and not (out["cert"] and out["key"]):
        pass
    return out
