#!/bin/sh
# Tests the built image the way a hospital runs it (docker compose: read-only, no capabilities, named volume):
# start-up checks, the whole reading flow in a browser (with a screenshot per step), persistence across a
# restart, backup with audit verification, and refusal of a tampered model file.
#   deploy/container_test.sh [screenshot-dir]
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SHOTS=${1:-$ROOT/deploy/test-screenshots}
# its own compose project, volume and port: never touches a real installation's data
export COMPOSE_PROJECT_NAME=cardiotic-acceptance CARDIOTIC_PORT=8729
URL=http://127.0.0.1:$CARDIOTIC_PORT
PW="correct horse battery"
cd "$ROOT"
ok() { echo "PASS  $*"; }

docker compose down -v >/dev/null 2>&1 || true
docker compose up -d --no-build >/dev/null
for i in $(seq 1 60); do curl -fs $URL/api/health >/dev/null 2>&1 && break; sleep 1; done
curl -fs $URL/api/health | grep -q '"models_verified": true' && ok "container up, models verified"
[ "$(docker compose exec -T cardiotic id -u)" = "10001" ] && ok "runs as non-root user 10001"
! docker compose exec -T cardiotic sh -c 'touch /opt/x' 2>/dev/null && ok "root filesystem is read-only"
for u in "arao|Dr. Ananya Rao|cardiologist|Consultant cardiologist" "rsawant|Rohit Sawant|technician|ECG technician" "kdesai|Kiran Desai|admin|IT administrator"; do
  IFS='|' read -r user name role title <<EOU
$u
EOU
  docker compose exec -T -e CARDIOTIC_NEW_PASSWORD="$PW" cardiotic cardiotic-server create-user "$user" "$name" "$role" --title "$title" >/dev/null
done
ok "users created with the CLI inside the container"
TOKEN=$(curl -fs $URL/api/login -H 'Content-Type: application/json' -d "{\"username\":\"kdesai\",\"password\":\"$PW\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -fs -X PUT $URL/api/settings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"siteName":"Pulse Care"}' >/dev/null && ok "site name set"

python3 frontend/e2e-server/make_files.py >/dev/null
rm -rf "$SHOTS" && mkdir -p "$SHOTS"
if ! (cd frontend && E2E_SERVER_URL=$URL SHOTS_DIR="$SHOTS" npx playwright test -c playwright.server.config.ts --reporter=line); then
  echo "FAIL  browser flow; server log:"; docker compose logs --tail 80; exit 1
fi
ok "browser flow against the container ($(ls "$SHOTS" | wc -l) screenshots in $SHOTS)"

docker compose restart >/dev/null
for i in $(seq 1 60); do curl -fs $URL/api/health >/dev/null 2>&1 && break; sleep 1; done
TOKEN=$(curl -fs $URL/api/login -H 'Content-Type: application/json' -d "{\"username\":\"arao\",\"password\":\"$PW\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -fs $URL/api/reviews -H "Authorization: Bearer $TOKEN" | grep -q '"status": "signed"' && ok "signed report survives a restart (data on the volume)"

docker compose exec -T cardiotic cardiotic-server backup /data/backup-test.db >/dev/null
docker compose exec -T cardiotic cardiotic-server --db /data/backup-test.db verify-audit | grep -q "'ok': True" && ok "backup written and its audit chain verifies"

docker compose exec -T cardiotic python - <<'PY' && ok "optional libraries present in the image (LDAP, OpenID signature check, DICOM receiver, PDF/image digitiser, Philips XLI)"
import ldap3, cryptography, pynetdicom, pypdf, PIL, sierraecg, pydicom
PY
MODEL=$(docker compose exec -T cardiotic python -c 'import cardiotic_engine, pathlib; print(pathlib.Path(cardiotic_engine.__file__).parent / "models" / "quality_net_v0.3.onnx")' | tr -d '\r')
head -c 4096 /dev/urandom > /tmp/tampered.onnx
set +e
docker run --rm -v /tmp/tampered.onnx:"$MODEL":ro cardiotic:0.1.0 serve > /tmp/tamper.log 2>&1
CODE=$?
set -e
[ "$CODE" = "3" ] && grep -q "INTEGRITY CHECK FAILED" /tmp/tamper.log && ok "tampered model file refused (exit code 3)"
docker compose down -v >/dev/null
echo "all container checks passed"
