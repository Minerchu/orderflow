# OrderFlow — Telegram 订单管理与结算系统

Web 后台建单 → Telegram 机器人推送到白名单群组 → 群成员按钮接单 / 完成 / 失败 →
网页实时同步 → 按「币种 + 金额」统计**成功收款次数** → 结算批次 + Excel 导出 + 权限与审计。

<p align="center">
  <img src="docs/assets/login-hero.png" alt="OrderFlow 登录页" width="720" />
</p>

<p align="center">
  <a href="https://minerchu.github.io/orderflow/">在线展示页</a> ·
  <a href="https://github.com/Minerchu/orderflow">GitHub</a>
</p>

[![CI](https://github.com/Minerchu/orderflow/actions/workflows/ci.yml/badge.svg)](https://github.com/Minerchu/orderflow/actions/workflows/ci.yml)

```
┌────────────┐   :80    ┌──────────────┐   :8000   ┌────────────┐
│  frontend  │ ───────▶ │   backend    │ ────────▶ │    db      │
│  nginx     │  /api/*  │   uvicorn    │  psycopg  │ postgres16 │
│  Vue3 SPA  │          │   FastAPI    │           │            │
└────────────┘          └──────────────┘           └────────────┘
                          │        ▲
                     uploads 卷    │ webhook
                                  │
                          ┌───────────────┐
                          │ Telegram Bot  │
                          └───────────────┘
```

---

## 目录结构

```
orderflow/
├── docker-compose.yml        # db + backend + frontend 编排
├── .env.example              # 环境变量模板（复制为 .env）
├── scripts/
│   ├── deploy.sh             # 一键部署（生成密钥、构建、迁移、建管理员）
│   ├── backup.sh             # 备份数据库 + 上传文件卷
│   └── restore.sh            # 还原（含还原前自动安全备份）
├── backend/                  # FastAPI + SQLAlchemy2 + Alembic
│   ├── Dockerfile
│   ├── scripts/docker-entrypoint.sh   # serve / migrate / init-admin / shell
│   └── README.md             # 后端详细文档
└── frontend/                 # Vue3 + TS + Vite + Element Plus
    ├── Dockerfile            # node 构建 → nginx 托管
    ├── nginx.conf            # SPA fallback + /api 反代
    └── README.md             # 前端详细文档
```

---

## 快速部署（Docker Compose）

### 前置条件

- Docker Engine 24+ 与 Compose v2（`docker compose`）
- 服务器可访问外网（拉取基础镜像；之后可离线）

### 一键部署

```bash
git clone https://github.com/Minerchu/orderflow.git && cd orderflow
cp .env.example .env          # 或直接跳过，deploy.sh 会自动创建
./scripts/deploy.sh
```

`deploy.sh` 会自动完成：

1. 创建 `.env`，并把 `APP_SECRET_KEY` / `SESSION_SECRET` 生成为 64 位随机串
2. 构建镜像、启动容器
3. 等待后端健康检查通过
4. 执行 `alembic upgrade head`
5. 初始化管理员（`ADMIN_PASSWORD` 环境变量 / `.env` / 交互输入）

完成后访问 `http://<服务器IP>:80`（端口由 `.env` 的 `HTTP_PORT` 决定）。

### 手动分步（等价）

```bash
cp .env.example .env
# 编辑 .env：POSTGRES_PASSWORD、APP_SECRET_KEY、SESSION_SECRET 必须改

docker compose up -d --build

# 建管理员
docker compose exec backend python -m app.cli init-admin \
    --username admin --password '<强密码>'
```

### 常用命令

```bash
docker compose ps                     # 查看状态与健康
docker compose logs -f backend        # 跟踪后端日志
docker compose restart backend        # 重启后端
docker compose down                   # 停止（保留数据卷）
docker compose down -v                # 停止并删除数据（危险！）
```

---

## 在线展示

- GitHub Pages：<https://minerchu.github.io/orderflow/>

展示页源码在 `docs/`，由 GitHub Pages 从 `main` 分支的 `/docs` 目录发布。

---

## 移动端发单使用说明（v2）

- 订单页顶部「新建并发单」及手机底部醒目按钮均可打开表单，弹窗适配手机宽度和底部安全区。
- 可填写产品名称、邮箱、账号、密码、登录方式、备注、金额及图片；支持先存草稿或上传后直接发单。产品名称可作为图片名称/说明，最多选择 6 张 JPG、PNG、WebP 图片。
- 默认只发送已填写内容，不附加系统订单号、不显示空字段或默认币种占位。例如只填邮箱及备注 `code send`，群消息仅显示这两项；只填产品名称并上传图片，则仅显示图片和名称。明确选择登录方式时才显示登录方式。
- **填写的账号和密码默认会发送到目标群，群成员可见。** 请只填写已获授权共享的业务凭据。`SHOW_CREDENTIALS_IN_GROUP=false` 关闭账号展示，`SHOW_PASSWORD_IN_GROUP=false` 关闭密码展示；`SHOW_ORDER_ID_IN_GROUP=true` 可恢复系统订单号。已有 `.env` 的显式值优先，需要自行同步这些开关。
- 图片上传给 Telegram 时传递原始文件名，但 Telegram 图片客户端不保证展示该文件名，需要可见名称时填写产品名称。长文本分条完整发送，只有最后一条带操作按钮。
- 草稿首发带接单按钮；无业务内容且无图片拒绝发送。所有消息和图片响应均须成功，才会标记订单为已发送。
- 创建后如果图片上传或发送失败，会进入已建订单详情，不再次创建订单。请检查附件列表，补传缺失图片，再在该订单详情重试；已上传附件仍保留。
- **部分图片或文本成功后再失败，重试可能重复发送已送达的内容。** Telegram 多消息发送不具备事务回滚；本实现不承诺端到端 exactly-once。创建请求本身若服务器成功但响应丢失，也应先刷新订单列表检查，避免手动重复建单。
- 本项目已在 Docker Compose 环境完成真实构建与部署。生产环境的 `.env`、Bot Token、数据库密码不会提交到仓库。

## 配置说明

所有配置集中在根目录 `.env`（模板见 `.env.example`）。

### 必填

| 变量 | 说明 |
| --- | --- |
| `POSTGRES_PASSWORD` | 数据库密码，会被拼进后端 `DATABASE_URL` |
| `APP_SECRET_KEY` | 凭据加密（Fernet）密钥；变动会导致已加密的密码无法解密 |
| `SESSION_SECRET` | 会话令牌 / 签名文件 URL 密钥；变动会使所有登录失效 |

> 这两个密钥用 `./scripts/deploy.sh` 会自动生成；
> 手动生成：`python -c "import secrets;print(secrets.token_urlsafe(48))"`

### Telegram

首次部署时可以不在 `.env` 填 Bot Token 和群组 ID。系统启动后使用管理员账号登录网页，进入：

```text
系统设置 → Telegram 配置
```

可直接填写并保存：Bot Token、默认群组 ID、允许的群组 ID、管理员 Telegram 用户 ID。Bot Token 使用 `APP_SECRET_KEY` 加密后存入数据库，网页不会回显明文；以后修改群组参数或 Token 无需重建容器。页面 Token 留空表示保留已保存值。

环境变量仍可作为数据库尚未配置时的回退：

| 变量 | 说明 |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | 可选回退 Token；数据库已保存 Token 时优先使用数据库值 |
| `TELEGRAM_DEFAULT_CHAT_ID` | 可选回退默认群组 ID |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook 来源校验，建议在 `.env` 设置强随机值 |
| `TELEGRAM_ALLOWED_CHAT_IDS` | 可选回退白名单群组，逗号分隔，如 `-100123,-100456` |
| `ADMIN_TELEGRAM_USER_IDS` | 可选回退管理员 Telegram 用户 ID |

如果数据库和环境变量都没有 Bot Token，发送订单会返回 400，不会产生“假发送成功”。

### 群成员权限（后端强制，前端仅展示）

`ALLOW_ANY_GROUP_MEMBER_TO_COMPLETE` / `_FAIL` / `_REOPEN` / `_CLOSE`
默认 `false`；开启后白名单群内**任意成员**无需注册即可操作对应按钮。

### 存储

`STORAGE_BACKEND=local`（挂载 `uploads` 卷）或 `s3`（配 `S3_*`）。
图片**持久化在自己的存储**里，不依赖 Telegram 的 file_id。

---

## 备份与还原

```bash
# 备份到 backups/orderflow_<时间戳>/
./scripts/backup.sh

# 备份到指定位置（如 NAS）
./scripts/backup.sh /mnt/nas/orderflow-backups

# 还原（会先自动做一次安全备份）
./scripts/restore.sh backups/orderflow_20260101_030000
./scripts/restore.sh <dir> --yes     # 跳过确认
```

备份内容：`db.sql`（pg_dump）、`uploads.tar.gz`（附件卷）、`MANIFEST.txt`。

**建议加到 crontab**（每天凌晨 3 点）：

```cron
0 3 * * * cd /opt/orderflow && ./scripts/backup.sh /mnt/nas/orderflow-backups >> /var/log/orderflow-backup.log 2>&1
```

---

## 升级

```bash
git pull
./scripts/deploy.sh --pull     # 重新构建并滚动重启，自动跑迁移
```

数据在 `pgdata` / `uploads` 两个命名卷里，升级不会丢。

---

## 全新重装（清空所有数据）

> ⚠️ **这会删除全部订单、结算记录、上传的图片和所有设置，不可撤销。**
> 脚本会先自动备份，但请确认备份目录后再继续。

### 最省事：一条命令

```bash
# 1. 用新代码覆盖服务器（先保留好旧的 .env，步骤 3 会重建）
# 2. 备份 + 清空 + 重新部署
./scripts/reset.sh          # 会先备份，再问你确认
./scripts/deploy.sh
```

`reset.sh` 会依次执行：备份数据 → 停容器 → **删数据卷** → 删镜像 → 提示你输入 `RESET` 确认。
`deploy.sh` 会重建镜像、启动、跑迁移、创建管理员。

### 面板里手动操作

1. **备份**：面板 → 数据库 → 导出 PostgreSQL（保险起见）
2. **删容器**：应用商店 / 容器列表 → 删掉 orderflow 的 3 个容器（`orderflow_db`、`orderflow_backend`、`orderflow_frontend`）
3. **删数据卷**（面板 → 容器 → 数据卷）：
   - `orderflow_pgdata`（数据库，**删掉＝订单全没**）
   - `orderflow_uploads`（上传的图片）
   - 想保留数据库就只删 `uploads`；也可以用 `./scripts/reset.sh --keep-db`
4. **换新代码**：删除服务器上的旧目录，只保留 `.env`（里面的 `APP_SECRET_KEY` 决定了已加密的密码能否解开；全新安装则可以不要）
5. **全新部署**：
   ```bash
   cp .env.example .env
   # 至少改这几项：
   #   POSTGRES_PASSWORD / APP_SECRET_KEY / SESSION_SECRET  三个随机强密码
   #   APP_BASE_URL=https://你的域名
   #   TELEGRAM_PROXY=socks5://...（服务器不能直连 Telegram 时必填）
   ./scripts/deploy.sh
   ```
6. **初始化**：访问 `http://你的域名`，用 `deploy.sh` 里设置的管理员账号登录

### 不确定数据要不要留？

| 想要的效果 | 命令 |
|---|---|
| 彻底重装，数据不要 | `./scripts/reset.sh --yes` |
| 只清容器和图片，**保留订单** | `./scripts/reset.sh --keep-db` |
| 只想升级，不动数据 | `./scripts/upgrade.sh` |

---

## 从旧版本升级到 v4（重要）

v4 修改了 `products` 表结构：**产品类型只剩「名称 + 启用」**，
删除了编码、默认币种、默认登录方式以及 4 个从未生效的开关列。
**只替换代码文件而不跑数据库迁移，会导致「新建类型」报HTTP 500。**

### 用宝塔 / 1Panel 等面板升级

面板操作对应下面的命令，顺序一致：

1. **备份**：面板 → 数据库 → 导出 PostgreSQL；或执行 `./scripts/backup.sh`
2. **替换代码**：上传新文件覆盖，**保留服务器上的 `.env`**（里面是密钥和数据库密码）
3. **重建镜像**（关键，不能只「重启」）：
   ```bash
   docker compose build
   docker compose up -d
   ```
4. **应用迁移**：
   ```bash
   docker compose exec -T backend alembic upgrade head
   ```

   > **注意**：`upgrade head` 输出「没有待执行迁移」并不等于结构就对了。
   > Alembic 只比对版本号，已经跑过的迁移**永不重跑**。请核对实际结构：
   > ```bash
   > docker compose exec -T backend python -c "from sqlalchemy import create_engine,inspect;import os;print(sorted(c['name'] for c in inspect(create_engine(os.environ['DATABASE_URL'])).get_columns('products')))"
   > ```
   > 正确输出：`['created_at', 'id', 'is_active', 'name', 'updated_at']`
5. **浏览器强刷**（Ctrl/Cmd + F5）。nginx 已对 `index.html` 设了不缓存、
   对 `/assets/` 设了长期缓存，所以**不需要手动清缓存**，强刷即可拿到新界面。

### 关于「删除容器」和缓存

- **可以删容器和镜像**，业务数据存在两个命名卷里（`pgdata`、`uploads`），删了不会丢。
- **千万不要执行 `docker compose down -v`**，`-v` 会删除数据卷＝删库。
- 其实不必手动删容器：`docker compose build && docker compose up -d`
  会自动替换容器。
- Docker 构建缓存无需清理，Docker 会按文件哈希判断哪些层失效，只重建变化的部分。
  若怀疑缓存异常，用 `docker compose build --no-cache`（较慢，一般不需要）。

### 一键脚本

```bash
./scripts/upgrade.sh          # 升级（自动备份 → 重建镜像 → 迁移 → 校验 → 体检）
./scripts/rollback.sh         # 出问题一键回滚到升级前
```

`upgrade.sh` 会自动：检查配置项缺失 → **备份数据库和图片** → 记录升级前状态
→ 重建镜像（**不碰数据卷**）→ 跑迁移 → 校验表结构和新列 → 打印各表行数。

> 📖 **完整升级 / 迁移 / 备份 / 回滚方案见 [`docs/UPGRADE_AND_USAGE.md`](docs/UPGRADE_AND_USAGE.md)**
> ——包含"为什么升级不丢数据"的原理、换服务器迁移步骤、crontab 定时备份、
> 以及本次修复的 7 个问题对照表。

---

## 生产注意事项

1. **HTTPS**：Compose 只监听 80。生产请在前面再加一层反向代理
   （Caddy / Traefik / 云负载均衡）终结 TLS，并把 `/` 转给本栈的 `:80`。
2. **Webhook（按钮能否生效的关键）**
   群里点「接单 / 完成 / 失败」时，Telegram 只会把请求发给你**注册过**的地址。
   仅有一个 `/api/telegram/webhook` 接口是不够的——没注册，按钮就是完全没反应。

   - 把 `.env` 的 `APP_BASE_URL` 设成公网地址（如 `https://order.example.com`）
   - 或直接在「系统设置 → 按钮回调」填域名并点「保存并注册」——**存进数据库，改完立即生效，不用重启**
   - 保持 `AUTO_REGISTER_WEBHOOK=true`，后端启动时会自动调用 `setWebhook`
   - `TELEGRAM_WEBHOOK_SECRET` 保证只有 Telegram 能触发该接口

   设置页会显示当前状态：地址是否匹配、是否有积压的更新、Telegram 侧的报错。
   若公网地址仍是 `http://localhost`，页面会直接标红并显示当前值——
   这正是「按钮点了没反应」的头号原因（Telegram 只接受 HTTPS 公网地址）。
3. **服务器出网**：若服务器无法直连 `api.telegram.org`，配置
   `TELEGRAM_PROXY=socks5://user:pass@host:1080`，否则发单和按钮都会失败。
4. **不要把 5432 / 8000 暴露到公网**（compose 里默认未发布这两个端口）。
5. **密钥备份**：`APP_SECRET_KEY` 丢失会导致订单里加密的账号密码永久不可解。
6. 后端启动时会校验配置，`APP_ENV=production` 下若仍用默认密钥或开启
   `TELEGRAM_DRY_RUN` 会**拒绝启动**。

---

## 本地开发（不用 Docker）

```bash
# 后端：SQLite 零依赖
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.cli init-admin --username admin --password admin123
uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev        # /api 自动代理到 :8000
```

测试：`cd backend && pytest -q`，详见 `backend/README.md`。

---

## 核心业务规则（任务书硬性要求）

- 结算统计按 `(币种, 金额)` 计**成功收款次数**：**不求和、不换算、不出现合计列**
- 订单状态（draft/pending/processing/completed/failed/closed）与财务状态
  （unsettled/reserved/settled/excluded）**严格分离**
- 结算：预留（行锁）→ 确认（幂等，重复确认报错）→ 取消（释放预留）
- 白名单群任意成员可接单，无需注册；接单用**原子条件更新**防并发抢单
- 图片持久化到自有存储，按 partner 隔离访问
- 所有权限由**后端强制校验**，前端只做展示
- 群消息只展示**已填写**字段，不出现 `N/A` 占位
