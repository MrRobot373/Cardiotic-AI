#!/bin/sh
# Proves an install from a clean environment works, the same steps as the Dockerfile's Python layer and the
# systemd install: fresh virtual environment, core packages only (no PyTorch), real server, real upload.
#   deploy/smoke_test.sh [path-to-frontend-dist]
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'kill ${PID:-} 2>/dev/null || true; rm -rf "$WORK"' EXIT
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q "$ROOT/ml" "$ROOT/engine" "$ROOT/server" "pydicom>=2.4"
! "$WORK/venv/bin/python" -c "import torch" 2>/dev/null || { echo "PyTorch must not be needed at run time"; exit 1; }
export CARDIOTIC_DB="$WORK/cardiotic.db" CARDIOTIC_NEW_PASSWORD="correct-horse-battery-1"
S="$WORK/venv/bin/cardiotic-server"
"$S" init
"$S" create-user tester "Smoke Tester" technician
"$WORK/venv/bin/cardiotic-engine" verify > /dev/null
STATIC=${1:-$ROOT/frontend/dist}
"$S" serve --host 127.0.0.1 --port 8799 ${STATIC:+--static "$STATIC"} > "$WORK/server.log" 2>&1 &
PID=$!
for i in $(seq 1 40); do curl -fs http://127.0.0.1:8799/api/health > /dev/null 2>&1 && break; sleep 0.5; done
"$WORK/venv/bin/python" - "$ROOT" <<'PY'
import json, sys, urllib.request
sys.path.insert(0, sys.argv[1] + "/engine/tests")
import numpy as np, ingest_writers as w
base = "http://127.0.0.1:8799"
def call(path, data=None, headers=None):
    req = urllib.request.Request(base + path, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    return json.loads(urllib.request.urlopen(req).read())
tok = call("/api/login", json.dumps({"username": "tester", "password": "correct-horse-battery-1"}).encode())["token"]
ecg = np.load(sys.argv[1] + "/engine/tests/fixtures/fixtures.npz")["ecg12"]
rec = call("/api/upload", w.dicom_file(ecg, 500), {"Authorization": f"Bearer {tok}"})
cat = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/catalog", headers={"Authorization": f"Bearer {tok}"})).read())
assert cat["ecgs"] and cat["ecgs"][0]["id"] == rec["id"] and cat["ecgs"][0]["measurements"]["ok"]
print("smoke test passed:", rec["id"], len(cat["ecgs"][0]["statements"]), "findings")
PY
curl -fs http://127.0.0.1:8799/ | grep -q "<div id=\"root\">" && echo "web app served"
"$S" backup "$WORK/b.db" && "$S" --db "$WORK/b.db" verify-audit
