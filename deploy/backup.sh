#!/usr/bin/env bash
# Nightly SQLite backup, run via cron (/etc/cron.d/cairn-backup, installed
# by provision.sh) as the cairn user. Uses SQLite's own .backup command for
# a safe, consistent snapshot even while the app is writing to the DB —
# unlike a plain cp, which can grab a half-written page mid-transaction.
# Retention is enforced by a GCS bucket lifecycle rule (see TODO.md 10.5),
# not by this script.
set -euo pipefail

APP_DIR="/opt/cairn"
STAMP="$(date +%F)"
SNAPSHOT="/tmp/cairn-$STAMP.db"

set -a
. /etc/cairn/cairn.env
set +a

if [[ -z "${CAIRN_BACKUP_BUCKET:-}" ]]; then
  echo "CAIRN_BACKUP_BUCKET not set in /etc/cairn/cairn.env — skipping backup" >&2
  exit 1
fi

sqlite3 "$APP_DIR/cairn.db" ".backup '$SNAPSHOT'"
gcloud storage cp "$SNAPSHOT" "gs://${CAIRN_BACKUP_BUCKET}/cairn-$STAMP.db"
rm -f "$SNAPSHOT"

echo "Backed up cairn.db to gs://${CAIRN_BACKUP_BUCKET}/cairn-$STAMP.db"
