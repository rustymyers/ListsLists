#!/bin/sh
set -eu
[ $# -eq 1 ] || { echo "usage: $0 backup.sql.gz" >&2; exit 2; }
BACKUP=$1
[ -f "$BACKUP" ] || { echo "backup not found" >&2; exit 2; }
echo "WARNING: this replaces the current listslists database. Stop app traffic first." >&2
podman compose exec -T db dropdb -U listslists --if-exists listslists
podman compose exec -T db createdb -U listslists listslists
gzip -dc "$BACKUP" | podman compose exec -T db psql -U listslists -d listslists
echo "Database restored. Restore matching app-data/app-secrets archives manually, then run migrations."
