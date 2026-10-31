"""Recordings that arrive without anyone uploading them.

Folder feed: ECG carts and management systems (GE MUSE, Philips TraceMaster, Schiller SEMA…) export each
recording as a file into a shared folder. Every few seconds the feed imports files whose size has stopped
changing, then moves each one to `processed/` (or `failed/` with a `.reason.txt` next to it).

DICOM feed: carts that send DICOM (C-STORE) reach a receiver on this server (default AE title CARDIOTIC,
port 11112); 12-lead, general and ambulatory ECG waveform objects are accepted.

Both go through the same reading, analysis, duplicate check and audit as an upload; the audit names the feed.
Status per feed (last recording, counts, last error) is shown under Settings → Integrations.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from .db import now
from .store import Conflict

log = logging.getLogger("cardiotic_server.feeds")
STABLE_POLLS = 2  # a file must keep the same size this many polls before it is imported
IGNORED = (".tmp", ".part", ".crdownload", ".swp", ".lock")


def _bump(store, feed: str, ok: bool, detail: str) -> None:
    st = store.db.get_setting("feed_status", {})
    s = st.get(feed, {"received": 0, "failed": 0})
    if ok:
        s["received"] += 1
        s["last_received"] = now()
    else:
        s["failed"] += 1
        s["last_error"] = detail[:300]
        s["last_error_at"] = now()
    st[feed] = s
    store.db.set_setting("feed_status", st)


def import_bytes(store, feed: str, data: bytes, filename: str, location: str = "") -> tuple[bool, str]:
    """Import one recording from a machine feed. Returns (imported, message)."""
    from cardiotic_engine.api import InputError
    actor = {"id": 0, "username": f"feed:{feed}", "name": f"Machine feed: {feed}", "role": "technician", "title": ""}
    try:
        rec = store.add_file(actor, data, filename=filename, location=location)
        _bump(store, feed, True, rec["id"])
        return True, rec["id"]
    except Conflict as e:  # the same ECG sent twice is not an error for the sender
        _bump(store, feed, True, str(e))
        return True, str(e)
    except (InputError, ValueError) as e:
        _bump(store, feed, False, f"{filename}: {e}")
        store.db.audit(actor["name"], "Machine feed refused a file", f"{filename}: {str(e)[:120]}")
        return False, str(e)


class FolderFeeds(threading.Thread):
    def __init__(self, store, interval: float = 3.0):
        super().__init__(daemon=True, name="folder-feeds")
        self.store, self.interval, self._stop_evt = store, interval, threading.Event()
        self._seen: dict[str, tuple[int, int]] = {}  # path -> (size, polls unchanged)

    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.wait(self.interval):
            try:
                self.poll()
            except Exception:
                log.exception("folder feed poll failed")

    def poll(self) -> int:
        done = 0
        for feed in self.store.db.get_setting("feeds", {}).get("folders", []):
            if not feed.get("enabled", True):
                continue
            inbox = Path(feed["path"])
            if not inbox.is_dir():
                _bump(self.store, feed["name"], False, f"folder {inbox} is not reachable")
                continue
            for f in sorted(inbox.iterdir()):
                if not f.is_file() or f.name.startswith(".") or f.name.lower().endswith(IGNORED):
                    continue
                size = f.stat().st_size
                prev = self._seen.get(str(f))
                polls = prev[1] + 1 if prev and prev[0] == size else 1
                self._seen[str(f)] = (size, polls)
                if polls < STABLE_POLLS:
                    continue  # still being written
                ok, msg = import_bytes(self.store, feed["name"], f.read_bytes(), f.name, feed.get("location", ""))
                dest = inbox / ("processed" if ok else "failed")
                dest.mkdir(exist_ok=True)
                target = dest / f.name
                if target.exists():
                    target = dest / f"{f.stem}-{int(time.time())}{f.suffix}"
                shutil.move(str(f), target)
                if not ok:
                    target.with_name(target.name + ".reason.txt").write_text(msg + "\n")
                self._seen.pop(str(f), None)
                done += 1
        return done


class DicomFeed:
    """DICOM C-STORE receiver for ECG waveform objects (pynetdicom)."""

    def __init__(self, store):
        self.store, self.server, self.config = store, None, None

    def apply(self, cfg: dict) -> None:
        """Start, stop or restart to match the settings."""
        if cfg == self.config and (self.server is not None) == bool(cfg.get("enabled")):
            return
        self.stop()
        self.config = dict(cfg)
        if cfg.get("enabled"):
            self.start(int(cfg.get("port", 11112)), cfg.get("ae_title", "CARDIOTIC"), cfg.get("host", "0.0.0.0"))

    def start(self, port: int, ae_title: str, host: str = "0.0.0.0") -> None:
        from pynetdicom import AE, evt
        from pynetdicom.sop_class import AmbulatoryECGWaveformStorage, GeneralECGWaveformStorage, TwelveLeadECGWaveformStorage, Verification

        ae = AE(ae_title=ae_title)
        for sop in (TwelveLeadECGWaveformStorage, GeneralECGWaveformStorage, AmbulatoryECGWaveformStorage, Verification):
            ae.add_supported_context(sop)

        def on_store(event):
            ds = event.dataset
            ds.file_meta = event.file_meta
            buf = io.BytesIO()
            ds.save_as(buf, enforce_file_format=True)
            calling = event.assoc.requestor.ae_title.strip() if hasattr(event.assoc.requestor.ae_title, "strip") else str(event.assoc.requestor.ae_title)
            ok, msg = import_bytes(self.store, f"DICOM {calling or 'unknown'}", buf.getvalue(), f"{getattr(ds, 'SOPInstanceUID', 'dicom')}.dcm",
                                   (self.config or {}).get("location", ""))
            return 0x0000 if ok else 0xC000  # Success / Cannot understand

        self.server = ae.start_server((host, port), block=False, evt_handlers=[(evt.EVT_C_STORE, on_store)])
        log.info("DICOM receiver %s listening on %s:%d", ae_title, host, port)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server = None
