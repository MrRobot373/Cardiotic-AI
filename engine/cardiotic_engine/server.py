"""HTTP service for on-premise installs (standard library only; put TLS and authentication in front of it,
e.g. the hospital's reverse proxy, as the deployment guide requires).

  GET  /v1/health   liveness + model integrity
  GET  /v1/models   engine version, model versions and SHA-256
  POST /v1/ecg12    {"fs": 500, "units": "mV", "leads": {"I": [...], "II": [...], ...}}
  POST /v1/rhythm   {"fs": 360, "units": "mV", "lead": "II", "signal": [...]}
  POST /v1/file     the raw bytes of an ECG file (CSV, EDF, HL7 aECG, GE MUSE XML, DICOM, SCP-ECG); optional
                    headers X-Fs (Hz) and X-Units (mV|uV) for files that do not state them

Errors are JSON: {"error": "..."} with 400 (bad input), 404, 405, 413 (too large) or 500.
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from cardiotic_engine.api import Engine, InputError

MAX_BODY = int(os.environ.get("CARDIOTIC_ENGINE_MAX_BODY", str(256 * 1024 * 1024)))  # a 24 h Holter at 250 Hz fits
log = logging.getLogger("cardiotic_engine")


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o).__name__)


def make_handler(engine: Engine):
    class Handler(BaseHTTPRequestHandler):
        server_version = "cardiotic-engine"

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, default=_json_default).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # no request bodies (patient data) in logs
            log.info("%s %s", self.address_string(), fmt % args)

        def do_GET(self):
            if self.path == "/v1/health":
                self._send(200, {"status": "ok", "models_verified": True})
            elif self.path == "/v1/models":
                self._send(200, engine.info())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path not in ("/v1/ecg12", "/v1/rhythm", "/v1/file"):
                self._send(404, {"error": "not found"})
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n <= 0:
                self._send(400, {"error": "a JSON body with Content-Length is required"})
                return
            if n > MAX_BODY:
                self._send(413, {"error": f"body larger than {MAX_BODY} bytes"})
                return
            try:
                if self.path == "/v1/file":  # raw file body; optional X-Fs / X-Units for formats that do not state them
                    fs = self.headers.get("X-Fs")
                    self._send(200, engine.analyze_file(self.rfile.read(n), float(fs) if fs else None, self.headers.get("X-Units")))
                    return
                req = json.loads(self.rfile.read(n))
                if not isinstance(req, dict):
                    raise InputError("body must be a JSON object")
                if self.path == "/v1/ecg12":
                    out = engine.analyze_ecg12(req.get("leads"), req.get("fs"), req.get("units", "mV"))
                else:
                    out = engine.analyze_rhythm(req.get("signal"), req.get("fs"), req.get("units", "mV"), req.get("lead"))
                self._send(200, out)
            except (InputError, json.JSONDecodeError, ValueError) as e:
                self._send(400, {"error": str(e)})
            except Exception:  # never leak internals or data in the response
                log.exception("analysis failed")
                self._send(500, {"error": "internal error; see the engine log"})

        def do_PUT(self):
            self._send(405, {"error": "method not allowed"})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8710, engine: Engine | None = None) -> ThreadingHTTPServer:
    engine = engine or Engine()
    httpd = ThreadingHTTPServer((host, port), make_handler(engine))
    log.info("cardiotic-engine listening on %s:%d", host, port)
    return httpd
