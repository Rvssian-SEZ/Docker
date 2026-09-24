#!/bin/sh
# Backs up the two things that actually hold state: the Postgres database
# (db_data volume, via pg_dump rather than a filesystem copy so it's
# consistent and portable) and the file storage volume (app_storage, plain
# tar since it's just uploaded files). Run from the directory containing
# docker-compose.yml.
#
# Usage: ./scripts/backup.sh [output_dir]   (default: ./backups)
set -eu

OUT_DIR="${1:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"

POSTGRES_USER="$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2- || echo coffer)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2- || echo coffer)"

echo "Dumping database..."
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT_DIR/db-$STAMP.sql.gz"

echo "Archiving app_storage..."
docker run --rm \
  -v "$(basename "$(pwd)")_app_storage:/data:ro" \
  -v "$(pwd)/$OUT_DIR:/backup" \
  alpine tar czf "/backup/storage-$STAMP.tar.gz" -C /data .

echo "Done: $OUT_DIR/db-$STAMP.sql.gz, $OUT_DIR/storage-$STAMP.tar.gz"
echo "Restore db with:      gunzip -c $OUT_DIR/db-$STAMP.sql.gz | docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB"
echo "Restore storage into a running app_storage volume by extracting the tarball into it."
