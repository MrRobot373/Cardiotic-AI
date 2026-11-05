#!/bin/sh
# Proves a backup can be restored, without touching the live system: unpack it into a temporary folder, check the database's
# own integrity, verify the audit chain with the audit key, list what it holds, and start a throw-away server on it.
# Run this every quarter and after changing the backup arrangements; keep the output with the hospital's records.
#   deploy/restore_drill.sh /backup/cardiotic/cardiotic-20261101-020000.db.gz [path-to-audit-key-file]
set -eu
BACKUP="${1:?usage: restore_drill.sh BACKUP.db.gz [AUDIT_KEY_FILE]}"
KEY="${2:-${CARDIOTIC_AUDIT_KEY_FILE:-}}"
WORK=$(mktemp -d)
trap 'kill ${PID:-} 2>/dev/null || true; rm -rf "$WORK"' EXIT
case "$BACKUP" in *.gz) gunzip -c "$BACKUP" > "$WORK/restore.db" ;; *) cp "$BACKUP" "$WORK/restore.db" ;; esac
[ -n "${CARDIOTIC_AUDIT_KEY:-}" ] || [ -n "$KEY" ] || { echo "FAIL  no audit key: give the key file as the second argument, or set CARDIOTIC_AUDIT_KEY"; exit 1; }
[ -z "$KEY" ] || export CARDIOTIC_AUDIT_KEY_FILE="$KEY"
python3 - "$WORK/restore.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
r = c.execute("PRAGMA integrity_check").fetchone()[0]
print("database integrity:", r)
sys.exit(0 if r == "ok" else 1)
PY
echo "PASS  database file is intact"
cardiotic-server --db "$WORK/restore.db" verify-audit | grep -q "'ok': True" && echo "PASS  audit chain verifies with the audit key" || { echo "FAIL  audit chain does not verify"; exit 1; }
python3 - "$WORK/restore.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
for label, sql in (("patients", "SELECT COUNT(*) FROM patients"), ("ECG recordings", "SELECT COUNT(*) FROM recordings WHERE kind='ecg12'"), ("Holter recordings", "SELECT COUNT(*) FROM recordings WHERE kind='holter'"),
                   ("signed reports", "SELECT COUNT(*) FROM reviews WHERE status='signed'"), ("users", "SELECT COUNT(*) FROM users"), ("audit entries", "SELECT COUNT(*) FROM audit"),
                   ("newest recording", "SELECT MAX(created_at) FROM recordings"), ("newest audit entry", "SELECT MAX(at) FROM audit")):
    print(f"      {label:20} {c.execute(sql).fetchone()[0]}")
PY
PORT=${DRILL_PORT:-8798}
CARDIOTIC_DB="$WORK/restore.db" cardiotic-server --db "$WORK/restore.db" serve --host 127.0.0.1 --port "$PORT" > "$WORK/server.log" 2>&1 &
PID=$!
for i in $(seq 1 40); do curl -fs "http://127.0.0.1:$PORT/api/health" > /dev/null 2>&1 && break; sleep 0.5; done
curl -fs "http://127.0.0.1:$PORT/api/health" | grep -q '"status": "ok"' && echo "PASS  a server starts on the restored database" || { echo "FAIL  server did not start"; cat "$WORK/server.log"; exit 1; }
echo "Restore drill complete: $(date -u +%Y-%m-%dT%H:%M:%SZ) from $BACKUP"
