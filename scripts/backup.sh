#!/bin/sh
set -eu
DEST=${1:-./backups}
STAMP=$(date -u +%Y%m%d-%H%M%S)
mkdir -p "$DEST"
podman compose exec -T db pg_dump -U listslists -d listslists | gzip > "$DEST/listslists-$STAMP.sql.gz"
podman run --rm -v listslists_app_data:/source:ro -v "$(cd "$DEST" && pwd)":/backup alpine tar czf "/backup/app-data-$STAMP.tar.gz" -C /source .
echo "Created recovery set $STAMP in $DEST"
