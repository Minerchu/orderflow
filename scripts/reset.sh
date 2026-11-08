#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OrderFlow — full reset, then redeploy from scratch.
#
#   ./scripts/reset.sh            ask before deleting anything (recommended)
#   ./scripts/reset.sh --yes      skip the prompt
#   ./scripts/reset.sh --keep-db  wipe containers/images but KEEP the database
#
# !! DESTRUCTIVE !!  Removes the `pgdata` and `uploads` volumes, i.e. every
# order, settlement and uploaded screenshot. A backup is taken automatically
# before anything is deleted.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

log()  { printf '\033[1;34m[reset]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

ASSUME_YES=0
KEEP_DB=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)   ASSUME_YES=1 ;;
    --keep-db)  KEEP_DB=1 ;;
    -h|--help)  sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

command -v docker >/dev/null 2>&1 || die "docker not found on PATH."
if docker compose version >/dev/null 2>&1; then DC=(docker compose)
elif docker-compose version >/dev/null 2>&1; then DC=(docker-compose)
else die "docker compose not found."; fi

[ -f .env ] || die ".env not found. Run ./scripts/deploy.sh first."

# --- 1. Back up before destroying --------------------------------------
if [ -x ./scripts/backup.sh ]; then
  log "backing up current data (this is your only safety net)..."
  ./scripts/backup.sh "$ROOT/backups/pre_reset_$(date +%Y%m%d_%H%M%S)" \
    || warn "backup failed -- continuing is now IRREVERSIBLE."
else
  warn "scripts/backup.sh not executable; skipping backup."
fi

# --- 2. Confirm ---------------------------------------------------------
if [ "$ASSUME_YES" -ne 1 ]; then
  echo
  warn "This will PERMANENTLY DELETE:"
  warn "  - all containers, images and the network of this stack"
  warn "  - volume 'pgdata'  -> every order, settlement and setting"
  warn "  - volume 'uploads' -> every uploaded screenshot"
  if [ "$KEEP_DB" -eq 1 ]; then
    warn "  (--keep-db given: the database volume is PRESERVED)"
  fi
  echo
  printf 'Type "RESET" to continue: '
  read -r answer
  [ "$answer" = "RESET" ] || die "aborted."
fi

# --- 3. Tear down --------------------------------------------------------
log "stopping and removing containers..."
"${DC[@]}" down --remove-orphans

if [ "$KEEP_DB" -eq 1 ]; then
  log "removing images only (database preserved)..."
  "${DC[@]}" rm -f >/dev/null 2>&1 || true
else
  log "removing volumes (orders / uploads)..."
  # Named volumes are only removed with -v or an explicit name.
  "${DC[@]}" down -v --remove-orphans || true
fi

# Belt-and-braces: drop any volume still attached to this compose project.
PROJECT="$(basename "$ROOT" | tr '[:upper:]' '[:lower:]]' | tr -c 'a-z0-9_-' '-')"
if [ "$KEEP_DB" -eq 0 ]; then
  for v in "${PROJECT}_pgdata" "${PROJECT}_uploads" "orderflow_pgdata" "orderflow_uploads"; do
    docker volume rm "$v" >/dev/null 2>&1 && log "removed volume $v" || true
  done
fi

log "removing built images..."
docker image rm -f "$(docker compose images -q 2>/dev/null)" >/dev/null 2>&1 || true

echo
log "reset complete."

# --- 4. Report what is left, so leftovers are obvious -------------------
echo
log "检查是否清干净："
LEFT_C="$(docker ps -a --filter "name=orderflow" --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
LEFT_V="$(docker volume ls --filter "name=orderflow" --format '{{.Name}}' 2>/dev/null | tr '\n' ' ')"
LEFT_I="$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -i orderflow | tr '\n' ' ')"

if [ -n "$LEFT_C" ]; then
  warn "仍有容器:${LEFT_C}"
  warn "手动清除： docker rm -f ${LEFT_C}"
else
  log "  容器：已清空"
fi

if [ -n "$LEFT_V" ]; then
  warn "仍有数据卷:${LEFT_V}"
  if [ "$KEEP_DB" -eq 1 ]; then
    warn "这是预期的（--keep-db 保留了数据库）。"
  else
    warn "手动清除： docker volume rm ${LEFT_V}"
  fi
else
  log "  数据卷：已清空"
fi

if [ -n "$LEFT_I" ]; then
  warn "仍有镜像:${LEFT_I}"
  warn "手动清除： docker image rm -f ${LEFT_I}"
else
  log "  镜像：已清空"
fi

echo
if [ -n "$LEFT_C" ] || { [ -n "$LEFT_V" ] && [ "$KEEP_DB" -eq 0 ]; } || [ -n "$LEFT_I" ]; then
  warn "如需彻底重装，请按上面提示手动清除残留后，再执行 deploy.sh。"
else
  log "已彻底清空，可以执行： ./scripts/deploy.sh"
fi