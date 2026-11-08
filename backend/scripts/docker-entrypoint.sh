#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OrderFlow backend container entrypoint.
#
#   serve            wait for DB -> alembic upgrade -> uvicorn (default)
#   migrate          wait for DB -> alembic upgrade -> exit
#   init-admin       wait for DB -> alembic upgrade -> create admin -> exit
#   shell            drop into bash
#
# The admin credentials are read from ADMIN_USERNAME / ADMIN_PASSWORD.
# ---------------------------------------------------------------------------
set -euo pipefail

PORT="${PORT:-8000}"
DB_WAIT_RETRIES="${DB_WAIT_RETRIES:-60}"
DB_WAIT_INTERVAL="${DB_WAIT_INTERVAL:-2}"

log() { printf '[entrypoint] %s\n' "$*" >&2; }

# --- Wait until the database accepts connections -------------------------
wait_for_db() {
  if [ -z "${DATABASE_URL:-}" ]; then
    log "DATABASE_URL is not set; skipping DB wait."
    return 0
  fi
  log "waiting for database..."
  local i=0
  while ! python -m app.scripts_wait_db; do
    i=$((i + 1))
    if [ "$i" -ge "$DB_WAIT_RETRIES" ]; then
      log "database not reachable after $((DB_WAIT_RETRIES * DB_WAIT_INTERVAL))s; giving up."
      exit 1
    fi
    sleep "$DB_WAIT_INTERVAL"
  done
  log "database is up."
}

run_migrations() {
  log "running alembic upgrade head..."
  # Surface the resulting revision. If the app later reports schema errors
  # (e.g. "database structure not updated"), this line tells you whether the
  # migration actually ran for THIS build.
  alembic upgrade head
  local rev
  rev="$(alembic current 2>/dev/null | awk '{print $1}' || true)"
  log "migrations applied. current revision: ${rev:-unknown}"
}

create_admin() {
  local user="${ADMIN_USERNAME:-admin}"
  local pass="${ADMIN_PASSWORD:-}"
  if [ -z "$pass" ]; then
    log "ADMIN_PASSWORD is empty; skipping admin creation."
    return 0
  fi
  log "ensuring admin '$user' exists..."
  python -m app.cli init-admin --username "$user" --password "$pass"
}

case "${1:-serve}" in
  serve)
    wait_for_db
    run_migrations
    log "starting uvicorn on 0.0.0.0:${PORT}"
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --proxy-headers --forwarded-allow-ips '*'
    ;;
  migrate)
    wait_for_db
    run_migrations
    ;;
  init-admin)
    wait_for_db
    run_migrations
    create_admin
    ;;
  shell)
    exec bash
    ;;
  *)
    # Allow `docker run <image> <arbitrary command>`.
    exec "$@"
    ;;
esac
