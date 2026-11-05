"""Load and soak test for a running Cardiotic server: many readers at once while ECGs are uploaded and signed.

    python3 deploy/loadtest.py --url http://127.0.0.1:8720 --admin kdesai --readers 20 --uploaders 3 --minutes 5

It creates its own technician and cardiologist (test-load-*), uploads copies of one real ECG (each with a tiny change so
it counts as a new recording), has the readers poll the worklist and open ECGs like a busy department, and has the
cardiologist sign what arrives. It prints latency percentiles per action and any failures, and exits 1 if
errors > 0 or the 95th percentile of a read exceeds --max-p95 seconds. Use a test installation, not a live one.
Needs only the standard library plus numpy (for the sample ECG).
"""

from __future__ import annotations

import argparse
import getpass
import itertools
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine" / "tests"))
import ingest_writers as w  # noqa: E402


class Api:
    def __init__(self, url):
        self.url, self.token = url.rstrip("/"), None

    def call(self, method, path, body=None, raw=None, headers=None):
        h = dict(headers or {})
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        data = raw
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        t = time.perf_counter()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url + "/api" + path, data=data, method=method, headers=h), timeout=120) as r:
                payload = r.read()
                return r.status, (json.loads(payload) if "json" in r.headers.get("Content-Type", "") else payload), time.perf_counter() - t
        except urllib.error.HTTPError as e:
            return e.code, e.read(), time.perf_counter() - t

    def login(self, user, pw):
        c, out, _ = self.call("POST", "/login", {"username": user, "password": pw})
        assert c == 200 and "token" in out, (user, c, out)
        self.token = out["token"]


class Stats:
    def __init__(self):
        self.lat, self.errors, self.lock = {}, [], threading.Lock()

    def add(self, name, code, sec, ok=(200, 201)):
        with self.lock:
            self.lat.setdefault(name, []).append(sec)
            if code not in ok:
                self.errors.append(f"{name}: HTTP {code}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--admin", required=True, help="an administrator user name (the password is asked for, or $CARDIOTIC_LOAD_ADMIN_PASSWORD)")
    ap.add_argument("--readers", type=int, default=10)
    ap.add_argument("--uploaders", type=int, default=2)
    ap.add_argument("--minutes", type=float, default=2)
    ap.add_argument("--poll", type=float, default=5.0, help="seconds between a reader's refreshes (the web app refreshes every 20 s; 1 is a stress test)")
    ap.add_argument("--max-p95", type=float, default=2.0, help="seconds")
    a = ap.parse_args()
    pw_admin = os.environ.get("CARDIOTIC_LOAD_ADMIN_PASSWORD") or getpass.getpass("Administrator password: ")
    pw = "Load-test-password-1"
    adm = Api(a.url)
    adm.login(a.admin, pw_admin)
    for u, role in (("test-load-tech", "technician"), ("test-load-doc", "cardiologist")):
        c, out, _ = adm.call("POST", "/users", {"username": u, "name": f"Load {role}", "role": role, "password": pw})
        if c == 201:  # first sign-in would demand a new password: set the final one directly through the first-login route
            t = Api(a.url)
            t.login(u, pw)
            t.call("POST", "/me/password", {"current": pw, "new": pw + "x"})
        elif c != 400:
            print("cannot create", u, c, out)
            return 2
    pw2 = pw + "x"
    ecg = np.load(ROOT / "engine" / "tests" / "fixtures" / "fixtures.npz")["ecg12"]
    stats, stop, end = Stats(), threading.Event(), time.time() + a.minutes * 60
    counter = itertools.count(int.from_bytes(os.urandom(3), 'big'))
    ids: list[str] = []
    ids_lock = threading.Lock()

    def uploader(k):
        c = Api(a.url)
        c.login("test-load-tech", pw2)
        n = 0
        while time.time() < end and not stop.is_set():
            n += 1
            with ids_lock:
                uid = next(counter)
            x = np.roll(ecg, uid % 5000, axis=1) * (0.8 + 0.4 * ((uid // 5000) % 100) / 100)  # a different recording every time, in every run
            code, out, sec = c.call("POST", "/upload", raw=w.dicom_file(x, 500), headers={"X-Filename": "load.dcm", "X-Patient-MRN": f"LOAD-{k}-{n % 50}"})
            stats.add("upload+analyse", code, sec)
            if code == 201:
                with ids_lock:
                    ids.append(out["id"])
            time.sleep(0.5)

    def reader(k):
        c = Api(a.url)
        c.login("test-load-doc", pw2)
        while time.time() < end and not stop.is_set():
            code, _, sec = c.call("GET", "/catalog")
            stats.add("worklist (catalog)", code, sec)
            code, _, sec = c.call("GET", "/reviews")
            stats.add("reviews", code, sec)
            with ids_lock:
                pick = ids[k % len(ids)] if ids else None
            if pick:
                code, _, sec = c.call("GET", f"/ecg/{pick}")
                stats.add("open ECG", code, sec)
            time.sleep(a.poll)

    def signer():
        c = Api(a.url)
        c.login("test-load-doc", pw2)
        done = set()
        while time.time() < end and not stop.is_set():
            with ids_lock:
                todo = [i for i in ids if i not in done]
            for rid in todo[:3]:
                done.add(rid)
                code, d, sec = c.call("GET", f"/ecg/{rid}")
                f = [s["statement"] for s in d["analysis"]["result"]["statements"] if not s["statement"].startswith("SUPER_")]
                c.call("PUT", f"/reviews/{rid}", {"decisions": {x: "accepted" for x in f}})
                code, _, sec = c.call("POST", f"/reviews/{rid}/sign", {"password": pw2})
                stats.add("sign", code, sec)
            time.sleep(1.0)

    threads = [threading.Thread(target=uploader, args=(k,)) for k in range(a.uploaders)] + [threading.Thread(target=reader, args=(k,)) for k in range(a.readers)] + [threading.Thread(target=signer)]
    t0 = time.time()
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(f"\n{a.readers} readers + {a.uploaders} uploaders + 1 signer for {time.time() - t0:.0f} s\n")
    print(f"{'action':24}{'count':>7}{'median':>9}{'p95':>9}{'max':>9}")
    worst = 0.0
    for name, v in sorted(stats.lat.items()):
        v = sorted(v)
        p95 = v[min(len(v) - 1, int(0.95 * len(v)))]
        if name not in ("upload+analyse", "sign"):
            worst = max(worst, p95)
        print(f"{name:24}{len(v):>7}{statistics.median(v):>9.3f}{p95:>9.3f}{v[-1]:>9.3f}")
    print(f"\nerrors: {len(stats.errors)}" + ("" if not stats.errors else "  e.g. " + "; ".join(sorted(set(stats.errors))[:5])))
    bad = bool(stats.errors) or worst > a.max_p95
    print("FAIL" if bad else "PASS", f"(read p95 worst {worst:.3f} s, limit {a.max_p95} s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
