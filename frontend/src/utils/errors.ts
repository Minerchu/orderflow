/**
 * Human-readable explanations for backend error codes.
 *
 * The backend previously reported every Telegram problem as
 * "telegram_send_failed", which told the admin nothing. It now returns
 * specific codes; this map turns them into a cause + suggested fix.
 */

const MESSAGES: Record<string, { text: string; fix: string }> = {
  telegram_not_configured: {
    text: '尚未配置 Bot Token',
    fix: '请到「系统设置」填写 Bot Token 并保存。',
  },
  telegram_unauthorized: {
    text: 'Bot Token 无效',
    fix: 'Token 填错或已被撤销。请到「系统设置」重新粘贴 BotFather 给的 Token。',
  },
  telegram_chat_not_found: {
    text: '找不到该群组',
    fix: '群组 ID 填错了，或机器人不在这个群里。请确认 ID 并先把机器人拉进群。',
  },
  telegram_bot_not_admin: {
    text: '机器人权限不足，无法发消息',
    fix: '请把机器人设为群管理员，并开启「可发送消息」权限。',
  },
  telegram_send_forbidden: {
    text: '机器人被禁止在该群发言',
    fix: '检查群里的「已屏蔽」名单，或解除对该机器人的限制。',
  },
  telegram_bot_blocked: {
    text: '机器人被踢出或拉黑了该群',
    fix: '请重新把机器人邀请进群，并授予发言权限。',
  },
  telegram_rate_limited: {
    text: '发送太频繁，被 Telegram 限流',
    fix: '请稍等几十秒后重试。',
  },
  telegram_message_too_long: {
    text: '消息内容太长',
    fix: '请减少文字或图片数量后重试。',
  },
  telegram_invalid_payload: {
    text: '消息内容格式不合法',
    fix: '请检查填写的内容中是否有异常字符。',
  },
  telegram_copy_text_too_long: {
    text: '一键复制按钮的内容太长',
    fix: 'Telegram 的复制按钮最多 256 个字符，超长内容（如支付链接）会整条消息被拒。该行已不再生成复制按钮，内容仍会显示在消息正文里，可手动复制。',
  },
  telegram_bad_request: {
    text: 'Telegram 拒绝了这条消息',
    fix: '通常是内容格式或长度不合规。请检查账号信息、备注等文本；服务器日志里有 Telegram 的原始报错。',
  },
  telegram_credentials_unavailable: {
    text: '无法读取该订单的密码',
    fix: '加密密钥可能已变更，需重新填写密码后再发送。',
  },
  telegram_network_error: {
    text: '服务器无法连接 Telegram',
    fix: '服务器需要出网代理。请在 .env 配置 TELEGRAM_PROXY（如 socks5://127.0.0.1:1080）后重启。',
  },
  telegram_network_timeout: {
    text: '连接 Telegram 超时',
    fix: '服务器出网不通或代理过慢，请检查 TELEGRAM_PROXY 配置。',
  },
  telegram_invalid_response: {
    text: 'Telegram 返回异常',
    fix: '请到「系统设置」点「测试连接」查看详细诊断。',
  },
  no_chat_id: {
    text: '没有设置默认群组',
    fix: '请到「系统设置」填写默认群组 ID，之后发单就不用再选了。',
  },
  telegram_send_failed: {
    text: '发送失败',
    fix: '请到「系统设置」点「测试连接」定位具体原因。',
  },
  empty_order: {
    text: '订单内容为空',
    fix: '请至少填写金额或备注后再发送。',
  },
  product_migration_required: {
    text: '数据库结构未更新',
    fix: '缺少数据库迁移。请在服务器执行：docker compose exec -T backend alembic upgrade head',
  },
  product_name_exists: {
    text: '该类型名称已存在',
    fix: '换一个名称，或直接编辑已有的类型。',
  },
  product_name_required: {
    text: '请填写类型名称',
    fix: '名称是必填项。',
  },
  product_not_found: {
    text: '类型不存在',
    fix: '该类型可能已被删除，请刷新页面。',
  },
  product_inactive: {
    text: '该类型已停用',
    fix: '请在产品类型页面启用后再使用。',
  },
  amount_required: {
    text: '订单金额不能为空',
    fix: '管理员和发单员发单都必须填写金额。',
  },
  amount_invalid: {
    text: '金额必须大于 0',
    fix: '请填写正确的金额后再提交。',
  },
  unsupported_currency: {
    text: '不支持的币种',
    fix: '目前仅支持 INR 与 USD。',
  },
  webhook_requires_https: {
    text: '需要 HTTPS 公网地址',
    fix: 'Telegram 只接受 HTTPS。请在「按钮回调」里填写你已配好证书的域名，保存后会自动注册。',
  },
  webhook_host_not_public: {
    text: '该地址不是公网地址',
    fix: 'localhost / 127.0.0.1 无法被 Telegram 访问，请填写你的真实域名。',
  },
  webhook_base_url_missing: {
    text: '未配置公网地址',
    fix: '请在「按钮回调」里填写你的 HTTPS 域名。',
  },
  webhook_base_url_invalid: {
    text: '地址格式不正确',
    fix: '请填写形如 https://order.example.com 的地址。',
  },
}

/** Turn an axios/FastAPI error into a readable message. */
export function describeSendError(e: any): string {
  const status = e?.response?.status
  const raw = e?.response?.data?.detail || e?.message || ''
  const code = typeof raw === 'string' ? raw : ''
  // Some backend codes carry context after a colon, e.g.
  // "webhook_requires_https:http://localhost". Match on the code only.
  const key = code.split(':')[0]
  const entry = MESSAGES[key]
  if (entry) {
    // Echo the offending value so the admin sees what is actually configured.
    const suffix = key === 'webhook_requires_https' && code.includes(':')
      ? `（当前值：${code.slice(code.indexOf(':') + 1)}）`
      : ''
    return `${entry.text}${suffix} —— ${entry.fix}`
  }
  // Cloudflare replaces the body of a 5xx response with its own error page
  // ("error code: 502"), so the real reason never reaches the browser. Say so
  // in Chinese instead of leaking that English string.
  if (typeof status === 'number' && status >= 500) {
    return '服务器处理失败，Cloudflare 未把具体原因传回 —— 请稍后重试；若反复出现，请到服务器日志查看 Telegram 原始报错。'
  }
  if (code) return code
  return '发送失败，请稍后重试。'
}

/** Explanations for the settings health-check endpoint. */
export function describeDiagCode(code: string): string {
  const key = (code || '').split(':')[0]
  const entry = MESSAGES[key]
  return entry ? `${entry.text} —— ${entry.fix}` : code
}