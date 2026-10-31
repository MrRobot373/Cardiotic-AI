#!/bin/sh
# Consistent backup of the database while the server runs. Run from cron: 0 2 * * * /opt/cardiotic/deploy/backup.sh /backup/cardiotic
# Keep copies off the server. The file contains patient data: protect and encrypt it like the database itself.
set -eu
DEST="${1:?usage: backup.sh DIRECTORY}"
mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$DEST/cardiotic-$STAMP.db"
cardiotic-server --db "${CARDIOTIC_DB:-/var/lib/cardiotic/cardiotic.db}" backup "$OUT"
cardiotic-server --db "$OUT" verify-audit
gzip "$OUT"
find "$DEST" -name 'cardiotic-*.db.gz' -mtime +30 -delete
echo "backup: $OUT.gz"
