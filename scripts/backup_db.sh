#!/usr/bin/env bash
# Backup the local SQLite or remote Postgres DB. Detects from $DATABASE_URL.
#
# Usage:
#   ./scripts/backup_db.sh [output_dir]
#
# Output: <dir>/beyond_fit_<utc_timestamp>.{sqlite|sql.gz}

set -euo pipefail

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"
TS=$(date -u +%Y%m%dT%H%M%SZ)

DB_URL="${DATABASE_URL:-sqlite:///./beyond_fit.db}"

if [[ "$DB_URL" == sqlite:* ]]; then
    SRC="${DB_URL#sqlite:///}"
    SRC="${SRC#./}"
    DEST="$OUT_DIR/beyond_fit_${TS}.sqlite"
    cp -v "$SRC" "$DEST"
    echo "✅ SQLite backup: $DEST"
elif [[ "$DB_URL" == postgresql:* || "$DB_URL" == postgres:* ]]; then
    DEST="$OUT_DIR/beyond_fit_${TS}.sql.gz"
    pg_dump "$DB_URL" | gzip > "$DEST"
    echo "✅ Postgres backup: $DEST"
else
    echo "❌ Unsupported DATABASE_URL: $DB_URL"
    exit 1
fi
