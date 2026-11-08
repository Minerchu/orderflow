#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OrderFlow — 无痕升级（数据零丢失）
#
#   ./scripts/upgrade.sh              # 完整升级（推荐）
#   ./scripts/upgrade.sh --no-backup  # 跳过升级前备份（不推荐）
#
# 设计原则：镜像与数据彻底解耦。
#   * 数据库在具名 volume `orderflow_pgdata` 里
#   * 上传的图片在具名 volume `orderflow_uploads` 里
#   * 升级只重建镜像 + 跑 alembic 迁移，**从不** down -v、从不删卷
#
# 流程：备份 -> 记录旧镜像 ID -> 重建镜像 -> 起容器 -> 迁移 -> 校验 -> 报告
# 失败时提示用 ./scripts/rollback.sh 一键回滚。
# 可重复执行（幂等）。
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

log()  { printf '\033[1;34m[upgrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

DO_BACKUP=1
for arg in "$@"; do
  case "$arg" in
    --no-backup) DO_BACKUP=0 ;;
    -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

[ -f .env ] || die ".env not found. Run ./scripts/deploy.sh first."

command -v docker >/dev/null 2>&1 || die "docker not found on PATH."
if docker compose version >/dev/null 2>&1; then DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then DC=(docker-compose)
else die "docker compose not found."; fi

# --- 0. 确认关键配置键 -------------------------------------------------
MISSING=""
grep -q '^APP_BASE_URL=' .env || MISSING="${MISSING} APP_BASE_URL"
grep -q '^AUTO_REGISTER_WEBHOOK=' .env || MISSING="${MISSING} AUTO_REGISTER_WEBHOOK"
if [ -n "$MISSING" ]; then
  warn "missing config keys in .env:${MISSING}"
  warn "without APP_BASE_URL the group buttons will NOT work (no webhook)."
  warn "add e.g.: APP_BASE_URL=https://your-domain.com"
fi

# --- 1. 记录升级前的状态（回滚要用） -----------------------------------
STATE_DIR="$ROOT/.upgrade-state"
mkdir -p "$STATE_DIR"
log "recording pre-upgrade state -> $STATE_DIR/pre_upgrade.env"
BACKEND_IMG="$("${DC[@]}" images -q backend 2>/dev/null | head -1 || true)"
FRONTEND_IMG="$("${DC[@]}" images -q frontend 2>/dev/null | head -1 || true)"
REV_BEFORE="$("${DC[@]}" exec -T backend alembic current 2>/dev/null | awk '{print $1}' | tr -d '\r' || true)"
{
  echo "# 升级前状态快照 $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "BACKEND_IMAGE_ID=${BACKEND_IMG:-<none>}"
  echo "FRONTEND_IMAGE_ID=${FRONTEND_IMG:-<none>}"
  echo "ALEMBIC_REVISION_BEFORE=${REV_BEFORE:-<unknown>}"
  echo "GIT_DESCRIBE=$(git describe --tags --always 2>/dev/null || echo '<no-git>')"
} > "$STATE_DIR/pre_upgrade.env"
log "alembic revision before: ${REV_BEFORE:-unknown}"

# --- 2. 升级前备份（数据库 + 上传图片）--------------------------------
if [ "$DO_BACKUP" -eq 1 ]; then
  if [ -x ./scripts/backup.sh ]; then
    log "creating a pre-upgrade backup (this is your rollback point)..."
    if ./scripts/backup.sh; then
      # 记住这次备份路径，回滚时直接引用
      LATEST_BKP="$(ls -dt "$ROOT"/backups/orderflow_* 2>/dev/null | head -1 || true)"
      [ -n "$LATEST_BKP" ] && echo "PRE_UPGRADE_BACKUP=$LATEST_BKP" >> "$STATE_DIR/pre_upgrade.env"
      log "backup: ${LATEST_BKP:-<unknown>}"
    else
      warn "backup FAILED. 升级到一半若出问题将无法回到现状。"
      if [ -t 0 ]; then
        printf 'Continue anyway? type "yes": '
        read -r a; [ "$a" = "yes" ] || die "aborted by user."
      else
        die "backup failed and no TTY to confirm; aborting."
      fi
    fi
  else
    warn "scripts/backup.sh not executable; skipping backup."
  fi
else
  warn "backup skipped (--no-backup)."
fi

# --- 3. 重建镜像（代码变了，不是简单重启）------------------------------
log "rebuilding images (data volumes are NOT touched)..."
"${DC[@]}" build

log "recreating containers (volumes preserved)..."
# 关键：只 up -d，绝不 down -v / rm volumes
"${DC[@]}" up -d

# --- 4. 等后端健康 ----------------------------------------------------
log "waiting for backend to become healthy..."
for _ in $(seq 1 60); do
  status="$("${DC[@]}" ps --format json backend 2>/dev/null | grep -o '"Health":"[a-z]*"' | head -1 | cut -d'"' -f4 || true)"
  [ "$status" = "healthy" ] && break
  sleep 2
done

# --- 5. 显式跑迁移 ----------------------------------------------------
log "applying migrations..."
"${DC[@]}" exec -T backend alembic upgrade head

REV_AFTER="$("${DC[@]}" exec -T backend alembic current 2>/dev/null | awk '{print $1}' | tr -d '\r' || true)"
log "current schema revision: ${REV_AFTER:-unknown}"
echo "ALEMBIC_REVISION_AFTER=${REV_AFTER:-<unknown>}" >> "$STATE_DIR/pre_upgrade.env"

# --- 6. 校验：products 表结构 + 新列存在 -------------------------------
# 已发布的 alembic revision 不会重跑，"upgrade head" 报无事可做
# 并不能证明结构与代码一致，所以这里直接检查列。
log "verifying schema (products + orders.telegram_message_is_media)..."
if ! "${DC[@]}" exec -T backend python - <<'PY'
from sqlalchemy import create_engine, inspect
import os, sys
engine = create_engine(os.environ["DATABASE_URL"])
insp = inspect(engine)
problems = []

cols = {c["name"] for c in insp.get_columns("products")}
expected = {"id", "name", "is_active", "created_at", "updated_at"}
if expected - cols:
    problems.append(f"products missing columns: {sorted(expected - cols)}")
if cols - expected:
    problems.append(f"products leftover columns: {sorted(cols - expected)}")

ocols = {c["name"] for c in insp.get_columns("orders")}
if "telegram_message_is_media" not in ocols:
    problems.append("orders missing telegram_message_is_media (image-order fix)")

if problems:
    for p in problems:
        print(f"[verify] FAIL - {p}")
    sys.exit(1)
print("[verify] OK - schema matches the code.")
PY
then
  die "schema verification failed. Roll back with: ./scripts/rollback.sh"
fi

# --- 7. 数据完整性体检 -------------------------------------------------
log "sanity-checking existing data (row counts)..."
"${DC[@]}" exec -T backend python - <<'PY' || warn "row-count check reported an issue (see above)."
from sqlalchemy import create_engine, text
import os
engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as c:
    for tbl in ("orders", "order_events", "order_attachments", "users", "products"):
        try:
            n = c.execute(text(f"SELECT count(*) FROM {tbl}")).scalar()
            print(f"[data] {tbl}: {n} rows")
        except Exception as e:
            print(f"[data] {tbl}: (skip) {type(e).__name__}")
PY

echo
log "done. 数据卷未被触碰，订单/图片全部保留。"
echo "    1. 打开 设置 -> 按钮回调（Webhook），确认状态是「已注册」。"
echo "       If not, click 注册 Webhook."
echo "    2. 打开 设置 -> 测试连接 -> 发送测试消息，确认能发单。"
echo "    3. 打开任意一条【有图片的】订单，在群里点「接单」验证已修复。"
echo "    Logs    : ${DC[*]} logs -f backend"
echo "    Rollback: ./scripts/rollback.sh"
