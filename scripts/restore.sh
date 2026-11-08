#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OrderFlow — restore a backup produced by ./scripts/backup.sh
#
#   ./scripts/restore.sh backups/orderflow_20260101_030000
#   ./scripts/restore.sh <dir> --yes     skip the confirmation prompt
#
# !! DESTRUCTIVE !!  This drops and recreates every object in the target
# database (the dump is taken with --clean --if-exists) and replaces the
# uploads volume. Always take a fresh backup of the current state first.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

log()  { printf '\033[1;34m[restore]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

SRC="${1:-}"
[ -n "$SRC" ] || die "usage: $0 <backup-dir> [--yes]"
ASSUME_YES=0
[ "${2:-}" = "--yes" ] && ASSUME_YES=1

[ -d "$SRC" ] || die "backup dir not found: $SRC"
SRC="$(cd "$SRC" && pwd)"
[ -f "$SRC/db.sql" ] || die "missing $SRC/db.sql"

command -v docker >/dev/null 2>&1 || die "docker not found on PATH."
if docker compose version >/dev/null 2>&1; then DC=(docker compose);
elif command -v docker-compose >/dev/null 2>&1; then DC=(docker-compose);
else die "docker compose not found."; fi

[ -f .env ] || die ".env not found."
set -a; . ./.env; set +a
DB_USER="${POSTGRES_USER:-orderflow}"
DB_NAME="${POSTGRES_DB:-orderflow}"

if [ "$ASSUME_YES" -ne 1 ]; then
  echo
  warn "This will OVERWRITE database '$DB_NAME' and the uploads volume."
  warn "Source: $SRC"
  printf 'Type "yes" to continue: '
  read -r answer
  [ "$answer" = "yes" ] || die "aborted."
fi

# --- 0. Safety net: snapshot the current state before overwriting --------
SAFETY="backups/pre_restore_$(date +%Y%m%d_%H%M%S)"
log "taking a safety backup of the current state -> $SAFETY"
if ./scripts/backup.sh "$SAFETY" >/dev/null 2>&1; then
  log "safety backup written."
else
  warn "could not take a safety backup (stack may be down); continuing."
fi

# --- 1. Ensure the stack is up ------------------------------------------
log "starting containers..."
"${DC[@]}" up -d
log "waiting for the database..."
for _ in $(seq 1 60); do
  if "${DC[@]}" exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then break; fi
  sleep 2
done
"${DC[@]}" exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 \
  || die "database did not become ready."

# --- 2. Restore the database -------------------------------------------
log "restoring database from db.sql..."
"${DC[@]}" exec -T db psql \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    --set ON_ERROR_STOP=on \
  < "$SRC/db.sql"
log "database restored."

# --- 3. Restore uploads -------------------------------------------------
if [ -f "$SRC/uploads.tar.gz" ] && [ -s "$SRC/uploads.tar.gz" ]; then
  log "restoring uploads volume..."
  "${DC[@]}" exec -T backend sh -c 'rm -rf /data/uploads && mkdir -p /data/uploads'
  "${DC[@]}" exec -T backend tar -xzf - -C /data < "$SRC/uploads.tar.gz"
  log "uploads restored."
else
  warn "no uploads.tar.gz in backup; leaving the uploads volume as-is."
fi

# --- 4. Reconcile schema, restart the app -------------------------------
log "applying any newer migrations (backup may predate current code)..."
"${DC[@]}" exec -T backend alembic upgrade head || warn "migrations reported an issue; check logs."

log "restarting the backend..."
"${DC[@]}" restart backend

log "done. Verify by signing in and checking a few orders/settlements."
