# OrderFlow 后端运行 / 部署说明

> 范围：本说明只覆盖**后端**（FastAPI + SQLAlchemy 2.0 + Alembic）。
> 前端（Vue3 项目壳）与 Docker / Nginx 暂未实现，见文末「未完成项」。

OrderFlow 是一套「Telegram 订单管理与结算系统」：后台建单 → 机器人把订单推送到白名单群组 →
群成员按钮接单 / 完成 / 失败 → 网页实时同步 → 按「币种 + 金额」统计成功收款**次数** → 结算批次 + Excel 导出。

---

## 1. 技术栈

| 层 | 选型 |
| --- | --- |
| Web 框架 | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0（声明式 `Mapped` / `mapped_column`） |
| 迁移 | Alembic 1.13（已生成初始迁移 `7333717e53eb`） |
| 校验 | Pydantic v2 |
| 数据库 | 生产 PostgreSQL（`psycopg[binary]` 3.2）；开发/测试零依赖 SQLite 回退 |
| 机器人 | `python-telegram-bot` 21.5；Webhook + 内联键盘 + 事务发件箱（outbox） |
| Excel | openpyxl 3.1 |
| 安全 | bcrypt 密码哈希、Fernet 凭据加密、itsdangerous 签名会话 / 签名文件 URL |

---

## 2. 环境准备

- Python 3.13（本项目已用隔离 venv：`~/.workbuddy/binaries/python/envs/orderflow`）。
- 本机无 Docker、无本地 PostgreSQL —— 因此开发/测试默认走 **SQLite**，生产再切 PostgreSQL。
- 切换数据库只需改 `.env` 的 `DATABASE_URL`，代码层无需改动。

---

## 3. 安装依赖

```bash
cd orderflow/backend

# 用隔离 venv（推荐）
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
```

> 已验证：在 Python 3.13 + 上述 venv 下，`pytest -q` 全绿（20 passed）。

---

## 4. 配置环境变量

复制样例并填真实值（**切勿提交 `.env`**）：

```bash
cp .env.example .env
```

关键项：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./orderflow.db`（开发）或 `postgresql+psycopg://...`（生产） | SQLite |
| `APP_SECRET_KEY` | JWT/签名密钥；**生产必须改** | `replace_me` |
| `SESSION_SECRET` | 会话令牌签名密钥；**生产必须改** | `replace_me_session` |
| `TELEGRAM_BOT_TOKEN` | 机器人 token；生产必填 | 空 |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook 回调的 secret token，用于校验来源 | 空 |
| `TELEGRAM_ALLOWED_CHAT_IDS` | 白名单群组 chat_id 列表，逗号分隔 | 空 |
| `ALLOW_ANY_GROUP_MEMBER_TO_COMPLETE` | 是否允许群内**任意成员**完成订单（无需注册） | `false` |
| `STORAGE_BACKEND` | `local` 或 `s3`；图片落地自有存储而非仅 Telegram file_id | `local` |
| `LOCAL_STORAGE_PATH` | 本地存储目录（需可写） | `/app/data/uploads` |
| `TELEGRAM_DRY_RUN` | 仅测试/本地演示：无 token 时用内存客户端，**生产禁止开启** | `false` |

生产启动时，`config.validate_required()` 会拒绝使用默认密钥 / 缺失 bot token /
在 production 下开启 `TELEGRAM_DRY_RUN`。

> **重要**：未配置 `TELEGRAM_BOT_TOKEN` 时调用「发送到群组」会返回
> `400 telegram_not_configured`，**不会**假装发送成功（否则订单会卡在 pending 而群里永远收不到）。

---

## 5. 数据库初始化

**方式 A — Alembic 迁移（推荐，生产一致）：**

```bash
# 首次建表
alembic upgrade head

# 以后模型变更后
alembic revision --autogenerate -m "描述"
alembic upgrade head
```

**方式 B — 开发快捷（`init-admin` 会顺带 `create_all`）：**

```bash
python -m app.cli init-admin --username admin --password 你的强密码
```

两种方式都会生成全部 12 张表：`users, orders, order_attachments, order_events, products,
settlement_batches, settlement_items, telegram_outbox, telegram_updates, audit_logs,
login_attempts, alembic_version`。已验证 `alembic upgrade head` 干净通过、无重复索引。

---

## 6. 初始化管理员

```bash
python -m app.cli init-admin --username admin --password 你的强密码
```

密码以 bcrypt 哈希入库，绝不落明文、绝不进日志。

---

## 7. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：`GET /health` → `{"status":"ok"}`（已验证返回正常）。

API 路由（共 42 条）按模块挂在 `/api/...`：
`auth, orders, products, attachments, settlements, partner, telegram, admin`。

---

## 8. Telegram Webhook 配置（接入机器人时）

1. 在 `.env` 填 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_WEBHOOK_SECRET`、`TELEGRAM_ALLOWED_CHAT_IDS`。
2. 把外部可达地址指向 `POST /api/telegram/webhook`（已用 secret token 校验来源）。
3. 群组消息只展示**已填写**字段（不出现 `N/A` 占位）；白名单内任意成员可按钮接单。
4. 回调幂等：已处理的 `update_id` 记入 `telegram_updates`，重复投递不会重复接单。
5. 并发接单用**原子条件 `UPDATE ... RETURNING`**，SQLite / PostgreSQL 行为一致，避免「两人同时抢单」。

---

## 9. 运行测试

```bash
pytest -q
```

覆盖：`test_orders.py`（建单/权限）、`test_telegram.py`（机器人回调）、
`test_business_rules.py`（核心财务规则 + 回归）。

**端到端烟雾测试**（需先启动后端并初始化 admin）：

```bash
python scripts/smoke_e2e.py
```

覆盖 33 项真实 HTTP 校验：登录 / 设置 / 产品 / 伙伴 / 建单 / 发送 / 事件 /
金额确认 / 结算预览·创建·导出·取消 / 伙伴隔离与 403 / 审计日志。
（脚本用 `httpx(trust_env=False)`，不受 shell 代理影响。）

**重点验证的业务规则**（均为任务书硬性要求）：

- 按 `(币种, 金额)` 统计**成功收款次数**，**绝不求和、绝不跨币种换算、绝不出现合计列**。
- 订单状态（draft/pending/processing/completed/failed/closed）与财务状态
  （unsettled/reserved/settled/excluded）**严格分离**。
- 结算：reserve（行锁 `with_for_update`）→ confirm（幂等，重复确认抛错）→ cancel（释放预留）。
- 合作伙伴只能看自己名下的订单（后端强制 403，非前端隐藏）。
- 图片落地自有存储且按 partner 隔离访问（跨 partner 下载返回 403）；
  浏览器直链下载走 `/api/attachments/{id}/url` 签发的**短时签名 URL**（15 分钟）。
- 语言切换**不改**存储的金额 / 币种，只翻译标签。
- Excel 导出与网页预览**完全一致**，且全表无 Total/Subtotal/总额/合计。
- 未配置 bot token 时发送必须报错，**不得伪成功**。

---

## 10. 目录结构（后端）

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口、CORS、路由挂载、/health
│   ├── config.py            # pydantic-settings，读 .env
│   ├── cli.py               # init-admin 命令
│   ├── constants.py         # 状态/角色/币种常量
│   ├── core/                # security（bcrypt/Fernet/签名）、deps（鉴权依赖）
│   ├── db/                  # base / session / models
│   ├── schemas/             # Pydantic 入参出参
│   ├── api/                 # 各模块路由
│   └── services/            # orders / settlement / statistics / telegram_bot
├── migrations/              # Alembic（env.py + 初始迁移）
├── tests/                   # pytest 套件
├── requirements.txt
├── .env.example
└── README.md
```

---

## 11. 生产部署注意

1. 切 `DATABASE_URL` 到 PostgreSQL，`alembic upgrade head` 建表。
2. 改掉 `APP_SECRET_KEY` / `SESSION_SECRET`，填 `TELEGRAM_BOT_TOKEN`。
3. 存储若用 S3，设 `STORAGE_BACKEND=s3` 及对应密钥；否则保证 `LOCAL_STORAGE_PATH` 可写且已备份。
4. 反向代理（Nginx）终结 HTTPS，把 `/api/telegram/webhook` 转到 uvicorn；secret token 校验保证只有 Telegram 能触发。
5. 所有权限均后端校验，前端仅做展示。

---

## 12. 前端（Vue3 + TS + Vite + Element Plus）

前端位于同级目录 `../frontend`，已实现并与本后端联调通过。

```bash
cd ../frontend
npm install
npm run dev     # http://127.0.0.1:5173，/api 自动代理到 :8000
npm run build   # 类型检查 + 生产构建到 dist/
```

页面：

| 角色 | 页面 | 说明 |
| --- | --- | --- |
| 公共 | 登录 | 用户名/密码，token 存 localStorage，401 自动登出 |
| 管理员 | 仪表盘 | 产品/伙伴/结算概览 |
| 管理员 | 订单 | 建单、发送/重发到群、金额确认、排除、事件时间线、附件上传/下载 |
| 管理员 | 产品 | 增删改查 |
| 管理员 | 合作伙伴 | 新建、启用/停用 |
| 管理员 | 结算 | 筛选预览（收款次数，无合计）、创建批次、确认、取消、导出 Excel |
| 管理员 | 审计日志 | 全量操作留痕 |
| 管理员 | 系统设置 | 只读展示（含群权限开关状态，敏感值已脱敏） |
| 合作伙伴 | 我的订单 | 仅本人订单 + 收款次数统计 + 详情/事件/附件 |
| 合作伙伴 | 我的结算 | 仅涉及本人订单的结算批次 |

国际化：中英文双语（右上角切换），语言只影响 UI/消息标签，**不影响金额与币种**。

---

## 13. 当前未完成项 / 限制

| 项 | 状态 | 说明 |
| --- | --- | --- |
| Docker / Compose / Dockerfile / Nginx | 未实现 | 本机无 Docker，开发用 SQLite + 双进程直跑 |
| 部署 / 备份还原脚本 | 待补 | 已在计划内 |
| Excel 汇总表 Product/Partner 可选列 | 未补 | 核心「汇总 + 详情 + 元信息」三表已齐 |
| 真实 Telegram 联调 | 待联调 | 逻辑用 MockTelegramClient + 33 项 HTTP 烟雾测试覆盖 |
| 前端单元测试 | 未补 | 目前靠 `vue-tsc` 类型检查 + 构建 + 手工联调 |

后端「可跑通」与前端「可登录可用」两轮均已完成：
测试 24 passed、烟雾测试 33 passed、前端类型检查与构建通过。

---

## 14. 群消息编辑与状态同步（2026-10 修复）

### 14.1 为什么要区分「文本消息」和「图片消息」

Telegram 的两条硬规则决定了这部分必须小心：

1. **单条消息的 caption 上限是 1024 个 UTF-16 单位**，正文（text）上限是 4096。
2. **带媒体的消息只能用 `editMessageCaption` 改**；对它调用 `editMessageText`
   会直接报 `there is no text in the message to edit`，静默失败。

因此订单表新增了一个布尔列 `telegram_message_is_media`，记录"群消息锚点是不是图片消息"。
`send_order_to_chat()` 返回 `SendResult(message_id, is_media)`，调用方把它写回订单。

### 14.2 发单时的按钮落点

```
有图片 + caption 放得下  →  按钮挂在【最后一张图片】上，锚点=该图片消息（is_media=True）
有图片 + caption 放不下  →  图片不带 caption，另发一条文字消息挂按钮，锚点=文字消息（is_media=False）
无图片                  →  文本分片发送，按钮挂最后一片，锚点=该文本消息（is_media=False）
```

**按钮只挂最后一条**：否则中途某张图片发送失败时，群里会留下一张"看着能接单、
其实订单没建成功"的图片。这是 `test_multi_photo_failure_not_success` 守住的约束。

### 14.3 状态变更如何回流到群里

```
群成员点按钮 → handle_callback() → 改库 → _refresh_group_message()
                                              ├─ is_media ? editMessageCaption
                                              └─ 否则     editMessageText
                                              └─ 都失败则退化为 editMessageReplyMarkup
后台改状态   → update_order()    → 改库 → sync_order_to_telegram() → 同上
```

- `sync_order_to_telegram()` 是**唯一**的后台→群同步入口，best-effort，**绝不回滚已保存的改动**。
- 只有"真正改变了群可见内容"才触发同步（`changed` 标记），避免原样保存也刷群。
- 未发过群的订单（无 `telegram_message_id`）→ 返回 `not_sent`，不报错。

### 14.4 失败原因选择的两阶段流程

```
点 ❌ 失败  →  editMessageReplyMarkup(原因键盘，含 ✖️ 取消)  →  answerCallbackQuery("请选择失败原因")
选原因     →  _do_fail()  →  写失败原因  →  _refresh_group_message()  →  恢复正确按钮
点 取消     →  _do_cancel_fail()  →  不改任何状态  →  _refresh_group_message()  →  恢复原按钮
```

**关键点**：无论走哪条路径，最后都调用 `_refresh_group_message()`。
之前只替换键盘、事后不恢复，导致"通知下面的按钮没有任何变化、不知道怎么操作"。

### 14.5 相关字段与端点

| 项 | 说明 |
| --- | --- |
| `orders.telegram_message_is_media` | 布尔，锚点是否图片消息（迁移 `b6d1f7a30e58`） |
| `PATCH /api/orders/{id}` | 编辑订单；改动群可见字段或状态时**自动同步**群消息 |
| `POST /api/orders/{id}/send` | 后台"同步到群"：原地重写现有群消息（不新发） |
| `POST /api/orders/{id}/retry-send` | 后台"重新发一条"：重新走一次发送，产生**新**群消息 |

> 两个端点当前实现相同（都会重发一条新消息）。UI 已把语义区分为
> 「同步到群」与「重新发一条」；若要严格区分，可让 `send` 走
> `sync_order_to_telegram()`（原地更新）、`retry-send` 走重发。


