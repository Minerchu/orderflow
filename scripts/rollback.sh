#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OrderFlow — 一键回滚到升级前状态
#
#   ./scripts/rollback.sh                 # 用升级前自动记录的备份回滚
#   ./scripts/rollback.sh <backup-dir>    # 指定某个备份目录回滚
#   ./scripts/rollback.sh --db-only       # 只回滚数据库（保留当前图片）
#
# 前提：upgrade.sh 运行过，`.upgrade-state/pre_upgrade.env` 存在；
#       或你手动指定了备份目录。
#
# !! 破坏性操作 !! 会覆盖当前数据库内容。脚本会先给"当前状态"再打一份
#    安全备份，所以即使回滚错了也还有第二次机会。
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

log()  { printf '\033[1;34m[rollback]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

SOURCE=""
DB_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --db-only) DB_ONLY=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) SOURCE="$arg" ;;
  esac
done

command -v docker >/dev/null 2>&1 || die "docker not found on PATH."
if docker compose version >/dev/null 2>&1; then DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then DC=(docker-compose)
else die "docker compose not found."; fi

[ -f .env ] || die ".env not found."
set -a; . ./.env; set +a
DB_USER="${POSTGRES_USER:-orderflow}"
DB_NAME="${POSTGRES_DB:-orderflow}"

# --- 1. 找到要回滚到的备份 --------------------------------------------
STATE_FILE="$ROOT/.upgrade-state/pre_upgrade.env"
if [ -z "$SOURCE" ]; then
  [ -f "$STATE_FILE" ] || die "no upgrade state found. Pass a backup dir explicitly."
  # shellcheck disable=SC1090
  . "$STATE_FILE"
  SOURCE="${PRE_UPGRADE_BACKUP:-}"
  [ -n "$SOURCE" ] || die "state file has no PRE_UPGRADE_BACKUP. Pass a backup dir."
  log "using pre-upgrade backup recorded at upgrade time."
fi

[ -d "$SOURCE" ] || die "backup dir not found: $SOURCE"
SOURCE="$(cd "$SOURCE" && pwd)"
[ -f "$SOURCE/db.sql" ] || die "missing $SOURCE/db.sql"
log "rolling back to: $SOURCE"

if [ "$DB_ONLY" -eq 1 ]; then
  log "DB-only mode: the uploads volume will be left as-is."
fi

# --- 2. 给"当前状态"打安全备份，防止回滚回错地方 ----------------------
SAFETY="$ROOT/backups/pre_rollback_$(date +%Y%m%d_%H%M%S)"
log "snapshotting the CURRENT state first -> $SAFETY"
if ./scripts/backup.sh "$SAFETY" >/dev/null 2>&1; then
  log "safety backup written."
else
  warn "could not snapshot current state (stack may be down); continuing."
fi

# --- 3. 确保容器起来了 -------------------------------------------------
log "starting containers..."
"${DC[@]}" up -d
log "waiting for the database..."
for _ in $(seq 1 60); do
  if "${DC[@]}" exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then break; fi
  sleep 2
done
"${DC[@]}" exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 \
  || die "database did not become ready."

# --- 4. 还原数据库 ----------------------------------------------------
log "restoring database from db.sql..."
"${DC[@]}" exec -T db psql \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    --set ON_ERROR_STOP=on \
  < "$SOURCE/db.sql"
log "database restored."

# --- 5. 还原上传图片（可选）------------------------------------------
if [ "$DB_ONLY" -ne 1 ]; then
  if [ -f "$SOURCE/uploads.tar.gz" ] && [ -s "$SOURCE/uploads.tar.gz" ]; then
    log "restoring uploads volume..."
    "${DC[@]}" exec -T backend sh -c 'rm -rf /data/uploads && mkdir -p /data/uploads'
    "${DC[@]}" exec -T backend tar -xzf - -C /data < "$SOURCE/uploads.tar.gz"
    log "uploads restored."
  else
    warn "no uploads.tar.gz in backup; leaving uploads as-is."
  fi
fi

# --- 6. 把数据库结构对齐到当前代码 ------------------------------------
# 备份里的 schema 可能比当前代码旧，upgrade head 会把新迁移补上，
# 这样数据回来了、代码也没退版本。
log "aligning schema with the currently deployed code (alembic upgrade head)..."
"${DC[@]}" exec -T backend alembic upgrade head || warn "migrations reported an issue; check logs."

log "restarting backend..."
"${DC[@]}" restart backend

echo
log "rollback done."
echo "    Safety copy of the pre-rollback state: $SAFETY"
echo "    Verify by signing in and checking a few orders."
