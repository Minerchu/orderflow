#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OrderFlow — one-shot deployment helper.
#
#   ./scripts/deploy.sh            build + start + migrate + create admin
#   ./scripts/deploy.sh --no-admin skip admin creation
#   ./scripts/deploy.sh --pull     pull newer base images first
#
# Idempotent: safe to re-run. Reads secrets from .env (creating a strong one
# from .env.example if missing) and the admin password from ADMIN_PASSWORD,
# .env, or an interactive prompt.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

CREATE_ADMIN=1
PULL=0
for arg in "$@"; do
  case "$arg" in
    --no-admin) CREATE_ADMIN=0 ;;
    --pull)     PULL=1 ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

random_secret() {
  # Works with a local python3 or a throwaway container.
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets;print(secrets.token_urlsafe(48))'
  elif command -v python >/dev/null 2>&1; then
    python -c 'import secrets;print(secrets.token_urlsafe(48))'
  else
    docker run --rm python:3.13-slim python -c 'import secrets;print(secrets.token_urlsafe(48))'
  fi
}

# --- 1. Ensure .env exists, with real secrets ----------------------------
# Done BEFORE the Docker check so secrets are prepared even if Docker still
# needs installing.
if [ ! -f .env ]; then
  log "no .env found; creating one from .env.example"
  cp .env.example .env
fi

# Replace placeholder secrets in place.
if grep -q '^APP_SECRET_KEY=change_me' .env; then
  log "generating APP_SECRET_KEY"
  s="$(random_secret)"
  # Use a temp file so the replacement is portable across sed variants.
  awk -v v="$s" 'BEGIN{FS=OFS="="} /^APP_SECRET_KEY=/{print "APP_SECRET_KEY="v; next} {print}' .env > .env.tmp && mv .env.tmp .env
fi
if grep -q '^SESSION_SECRET=change_me' .env; then
  log "generating SESSION_SECRET"
  s="$(random_secret)"
  awk -v v="$s" 'BEGIN{FS=OFS="="} /^SESSION_SECRET=/{print "SESSION_SECRET="v; next} {print}' .env > .env.tmp && mv .env.tmp .env
fi

# --- 2. Require Docker --------------------------------------------------
command -v docker >/dev/null 2>&1 || die "docker not found on PATH. Install Docker, then re-run (secrets in .env are already prepared)."

# Prefer `docker compose` (v2); fall back to `docker-compose` (v1).
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  die "docker compose plugin (or docker-compose) not found."
fi

# --- 3. Remind about the DB password ------------------------------------
if grep -q '^POSTGRES_PASSWORD=change_me' .env; then
  warn "POSTGRES_PASSWORD is still the placeholder."
  warn "Edit .env and set a strong value, then re-run. Continuing in 5s..."
  sleep 5
fi

# --- 4. Build & start ---------------------------------------------------
if [ "$PULL" -eq 1 ]; then
  log "pulling base images"
  "${DC[@]}" pull --ignore-buildable || warn "pull failed (offline?); continuing with local cache."
fi

log "building images"
"${DC[@]}" build

log "starting containers"
"${DC[@]}" up -d

# --- 5. Wait for the backend to report healthy --------------------------
log "waiting for the backend to become healthy..."
for i in $(seq 1 60); do
  status="$("${DC[@]}" ps --format json backend 2>/dev/null | grep -o '"Health":"[a-z]*"' | head -1 | cut -d'"' -f4 || true)"
  if [ "$status" = "healthy" ]; then
    log "backend is healthy."
    break
  fi
  if [ "$i" -eq 60 ]; then
    warn "backend did not report healthy in time; check: ${DC[*]} logs backend"
  fi
  sleep 2
done

# --- 6. Migrations (explicit; the entrypoint also runs them) ------------
log "applying database migrations"
"${DC[@]}" exec -T backend alembic upgrade head

# --- 7. Create the first admin -----------------------------------------
if [ "$CREATE_ADMIN" -eq 1 ]; then
  ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
  if [ -z "${ADMIN_PASSWORD:-}" ]; then
    # reuse one from .env if present, otherwise prompt
    ADMIN_PASSWORD="$(grep -E '^ADMIN_PASSWORD=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
  fi
  if [ -z "${ADMIN_PASSWORD:-}" ]; then
    if [ -t 0 ]; then
      printf 'Admin username [%s]: ' "$ADMIN_USERNAME"
      read -r input_user || true
      ADMIN_USERNAME="${input_user:-$ADMIN_USERNAME}"
      printf 'Admin password (input hidden): '
      read -rs ADMIN_PASSWORD || true
      echo
    fi
  fi
  if [ -n "${ADMIN_PASSWORD:-}" ]; then
    log "creating admin '$ADMIN_USERNAME' (safe to re-run)"
    "${DC[@]}" exec -T \
      -e ADMIN_USERNAME="$ADMIN_USERNAME" \
      -e ADMIN_PASSWORD="$ADMIN_PASSWORD" \
      backend python -m app.cli init-admin \
        --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD"
  else
    warn "no admin password supplied; create one later with:"
    warn "  ${DC[*]} exec backend python -m app.cli init-admin --username admin --password '<pw>'"
  fi
fi

# --- 8. Report ----------------------------------------------------------
HTTP_PORT="$(grep -E '^HTTP_PORT=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
HTTP_PORT="${HTTP_PORT:-80}"

echo
log "done."
echo "    Web UI : http://localhost:${HTTP_PORT}"
echo "    Logs   : ${DC[*]} logs -f backend"
echo "    Stop   : ${DC[*]} down"
echo "    Backup : ./scripts/backup.sh"
