# OrderFlow 前端（Vue 3 + TypeScript + Vite + Element Plus）

Telegram 订单管理与结算系统的 Web 界面。与本仓库 `../backend` 配套使用。

## 快速开始

```bash
npm install
npm run dev     # http://127.0.0.1:5173
```

开发模式下 `/api` 由 Vite 代理到后端（默认 `http://localhost:8000`），
因此本地无需处理 CORS。要改后端地址，编辑 `.env`：

```
VITE_API_PROXY_TARGET=http://localhost:8000
```

生产构建：

```bash
npm run build      # vue-tsc 类型检查 + vite build
npm run preview    # 本地预览 dist/
```

若把 `dist/` 部署到与后端不同的域名，请设置：

```
VITE_API_BASE=https://your-backend.example.com
```

## 目录结构

```
src/
├── api/            # 按模块封装的接口调用（axios 实例在 client.ts）
├── i18n/           # 中英文文案（en.ts / zh-CN.ts）
├── layouts/        # MainLayout：侧边菜单 + 顶栏 + 语言切换
├── router/         # 路由 + 登录/角色守卫
├── store/          # Pinia：auth（token & 当前用户）
├── utils/format.ts # 状态标签颜色、金额/时间格式化
├── views/
│   ├── LoginView.vue
│   ├── DashboardView.vue        # 管理员/伙伴两种仪表盘
│   ├── admin/                   # 订单/产品/伙伴/结算/审计/设置
│   └── partner/                 # 我的订单/我的结算
└── types.ts        # 与后端 Pydantic schema 对齐的类型
```

## 权限与安全

- 登录 token 存 `localStorage`；axios 拦截器自动附带 `Authorization: Bearer`。
- 收到 401 自动清空会话并跳转登录页。
- 路由按角色守卫（`meta.role`），但**真正的权限由后端强制校验**，前端只做展示。
- 附件下载与 Excel 导出走带 token 的请求（`blob`）或后端签发的短时签名 URL，
  因为浏览器直链（`window.open` / `<img>`）无法携带 `Authorization` 头。

## 关键业务约定（与后端一致）

- 金额以字符串形式传输（后端 `Decimal` 序列化为 string），展示时直接拼接币种。
- 结算「收款次数」严格按 `(币种, 金额)` 计数，**不求和、不换算、不出现合计列**。
- 订单状态与财务状态分两列展示，互不混淆。
- 语言切换只翻译标签，不影响金额与币种。

## 已验证

- `npx vue-tsc --noEmit` 通过（0 错误）
- `npx vite build` 通过
- dev server 正常服务页面，`/api` 代理到后端返回预期状态码
