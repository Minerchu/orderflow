#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OrderFlow — back up the PostgreSQL database and the uploads volume.
#
#   ./scripts/backup.sh                 -> backups/orderflow_<ts>/
#   ./scripts/backup.sh /mnt/nas/backup -> custom destination
#
# Produces:
#   db.sql          pg_dump (plain SQL, gzip-compressed as db.sql.gz if gzip)
#   uploads.tar.gz  the attachment volume
# with a final integrity check on the dump.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

log()  { printf '\033[1;34m[backup]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not found on PATH."
if docker compose version >/dev/null 2>&1; then DC=(docker compose);
elif command -v docker-compose >/dev/null 2>&1; then DC=(docker-compose);
else die "docker compose not found."; fi

[ -f .env ] || die ".env not found; run ./scripts/deploy.sh first."

# Load POSTGRES_* / DB settings from .env.
set -a; . ./.env; set +a
DB_USER="${POSTGRES_USER:-orderflow}"
DB_NAME="${POSTGRES_DB:-orderflow}"

TS="$(date +%Y%m%d_%H%M%S)"
DEST="${1:-$PWD/backups/orderflow_${TS}}"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"

log "destination: $DEST"

# --- 1. Database dump ---------------------------------------------------
log "dumping database '$DB_NAME' as user '$DB_USER'..."
"${DC[@]}" exec -T db pg_dump \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    --clean --if-exists --no-owner --no-privileges \
  > "$DEST/db.sql"

# An empty or truncated dump is worse than no backup.
if [ ! -s "$DEST/db.sql" ]; then
  die "db.sql is empty — dump failed."
fi
if ! grep -q 'CREATE TABLE\|PostgreSQL database dump' "$DEST/db.sql"; then
  log "warning: db.sql does not look like a pg_dump output; inspect it."
fi
log "db.sql: $(wc -c < "$DEST/db.sql") bytes"

# --- 2. Uploads volume --------------------------------------------------
log "archiving uploads volume..."
# The volume is mounted at /data/uploads inside the backend container.
if "${DC[@]}" exec -T backend sh -c 'test -d /data/uploads && [ -n "$(ls -A /data/uploads 2>/dev/null)" ]'; then
  "${DC[@]}" exec -T backend tar -czf - -C /data uploads > "$DEST/uploads.tar.gz"
  log "uploads.tar.gz: $(wc -c < "$DEST/uploads.tar.gz") bytes"
else
  log "uploads volume is empty; writing an empty archive for completeness."
  tar -czf "$DEST/uploads.tar.gz" --files-from /dev/null 2>/dev/null || \
    printf '' | gzip > "$DEST/uploads.tar.gz"
fi

# --- 3. Manifest --------------------------------------------------------
{
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "database=$DB_NAME"
  echo "db_user=$DB_USER"
  echo "app_env=${APP_ENV:-}"
  echo "storage_backend=${STORAGE_BACKEND:-local}"
  echo "files=db.sql,uploads.tar.gz"
} > "$DEST/MANIFEST.txt"

log "done."
echo
echo "  $DEST"
echo "    ├── db.sql"
echo "    ├── uploads.tar.gz"
echo "    └── MANIFEST.txt"
echo
echo "Restore with: ./scripts/restore.sh \"$DEST\""
