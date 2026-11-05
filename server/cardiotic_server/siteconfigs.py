"""Per-site operating points (statement thresholds) managed from Settings, with history.

The site's cardiology lead approves a configuration file (made with `cardiotic-engine site-config`, see engine/siteconfig.py).
An administrator uploads it here; it is checked against the exact statement model in use and refused otherwise.
Activating a version switches the thresholds at once and records who did it; the previous versions stay available, so a
change can be rolled back. The model weights are never touched. An environment-configured file (CARDIOTIC_SITE_CONFIG)
takes precedence and is shown read-only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from cardiotic_engine.api import SiteConfigError

from .db import now

log = logging.getLogger("cardiotic_server.siteconfigs")
FIELDS = "id, uploaded_at, uploaded_by, sha256, site_id, config_version, approved_by, approved_at, statements, activated_at, activated_by, deactivated_at"


def env_managed() -> bool:
    return bool(os.environ.get("CARDIOTIC_SITE_CONFIG"))


def active_id(db) -> int | None:
    r = db.conn().execute("SELECT id FROM site_configs WHERE activated_at IS NOT NULL AND deactivated_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return r["id"] if r else None


def listing(store) -> dict:
    rows = [dict(r) for r in store.db.conn().execute(f"SELECT {FIELDS} FROM site_configs ORDER BY id DESC")]
    act = active_id(store.db)
    for r in rows:
        r["active"] = r["id"] == act
    info = store.engine.info()
    model = f"{store.engine._m.manifest['models']['ecg12']['name']}_{store.engine._m.manifest['models']['ecg12']['version']}"
    return {"model": model, "env_managed": env_managed(), "active_info": info.get("site_config"), "versions": rows}


def upload(store, admin: dict, raw: bytes) -> dict:
    site = store.engine.check_site_config(raw)  # SiteConfigError: wrong model, not signed off, bad thresholds
    digest = hashlib.sha256(raw).hexdigest()
    with store.db.tx() as c:
        if c.execute("SELECT 1 FROM site_configs WHERE sha256=?", (digest,)).fetchone():
            from .store import Conflict
            raise Conflict("this exact file was uploaded before")
        cur = c.execute("INSERT INTO site_configs(uploaded_at, uploaded_by, sha256, raw, site_id, config_version, approved_by, approved_at, statements) VALUES (?,?,?,?,?,?,?,?,?)",
                        (now(), admin["name"], digest, raw.decode("utf-8"), str(site["site_id"]), str(site["config_version"]), str(site["approved_by"]), str(site["approved_at"]), len(site["statements"])))
        store.db.audit(admin["name"], "Uploaded site threshold file", f"{site['site_id']} v{site['config_version']} approved by {site['approved_by']}", c)
    return {"id": cur.lastrowid}


def activate(store, admin: dict, cid: int) -> dict:
    from .store import Conflict, NotFound
    if env_managed():
        raise Conflict("thresholds are set by the server's CARDIOTIC_SITE_CONFIG file; change it there")
    r = store.db.conn().execute("SELECT * FROM site_configs WHERE id=?", (cid,)).fetchone()
    if r is None:
        raise NotFound(cid)
    store.engine.apply_site_config(r["raw"].encode("utf-8"))  # raises SiteConfigError before anything is recorded
    with store.db.tx() as c:
        c.execute("UPDATE site_configs SET deactivated_at=? WHERE activated_at IS NOT NULL AND deactivated_at IS NULL", (now(),))
        c.execute("UPDATE site_configs SET activated_at=?, activated_by=?, deactivated_at=NULL WHERE id=?", (now(), admin["name"], cid))
        store.db.audit(admin["name"], "Activated site thresholds", f"{r['site_id']} v{r['config_version']} ({r['statements']} statements)", c)
    return listing(store)


def deactivate(store, admin: dict) -> dict:
    from .store import Conflict
    if env_managed():
        raise Conflict("thresholds are set by the server's CARDIOTIC_SITE_CONFIG file; change it there")
    store.engine.apply_site_config(None)
    with store.db.tx() as c:
        c.execute("UPDATE site_configs SET deactivated_at=? WHERE activated_at IS NOT NULL AND deactivated_at IS NULL", (now(),))
        store.db.audit(admin["name"], "Site thresholds off", "back to the model's own thresholds", c)
    return listing(store)


def restore_on_start(store) -> None:
    """At start-up the active version (if any) is applied again; if it no longer fits the model it is switched off and the audit says so."""
    if env_managed():
        return
    cid = active_id(store.db)
    if cid is None:
        return
    r = store.db.conn().execute("SELECT * FROM site_configs WHERE id=?", (cid,)).fetchone()
    try:
        store.engine.apply_site_config(r["raw"].encode("utf-8"))
    except SiteConfigError as e:
        log.error("active site thresholds refused at start-up: %s", e)
        store.engine.apply_site_config(None)  # back to the model's own thresholds, whatever was loaded before
        with store.db.tx() as c:
            c.execute("UPDATE site_configs SET deactivated_at=? WHERE id=?", (now(), cid))
            store.db.audit("system", "Site thresholds switched off at start-up", f"{r['site_id']} v{r['config_version']}: {str(e)[:100]}", c)
