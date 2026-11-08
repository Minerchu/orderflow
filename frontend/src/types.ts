// Mirrors the backend Pydantic schemas. Decimal amounts arrive as strings.

export type Role = 'admin' | 'partner' | 'worker' | 'dispatcher'

export interface User {
  id: number
  username: string
  role: Role
  telegram_user_id?: string | null
  telegram_username?: string | null
  display_name?: string | null
  preferred_language: string
  is_active: boolean
  created_at: string
  last_login_at?: string | null
  assigned_chat_ids?: string[]
  default_chat_id?: string | null
  allowed_product_ids?: number[]
  telegram_bound?: boolean
}

export interface TokenOut {
  access_token: string
  token_type: string
  user: User
}

export interface AttachmentOut {
  id: number
  order_id: number
  original_filename?: string | null
  mime_type?: string | null
  file_size: number
  created_at: string
}

export interface OrderEventOut {
  id: number
  order_id: number
  event_type: string
  from_status?: string | null
  to_status?: string | null
  actor_user_id?: number | null
  telegram_user_id?: string | null
  telegram_username?: string | null
  note?: string | null
  created_at: string
}

export interface Order {
  id: number
  order_number: string
  product_id?: number | null
  product_name_snapshot?: string | null
  amount?: string | null
  currency: string
  email?: string | null
  login_method?: string | null
  account?: string | null
  account_info?: string | null
  note?: string | null
  order_status: string
  financial_status: string
  dispatcher_settlement_status: string
  created_by_user_id?: number | null
  order_owner_id?: number | null
  accepted_by_user_id?: number | null
  completed_by_user_id?: number | null
  failed_by_user_id?: number | null
  closed_by_user_id?: number | null
  telegram_chat_id?: string | null
  telegram_message_id?: string | null
  telegram_message_is_media?: boolean
  telegram_send_status?: string | null
  telegram_sent_at?: string | null
  created_at: string
  updated_at: string
  accepted_at?: string | null
  completed_at?: string | null
  failed_at?: string | null
  closed_at?: string | null
  failure_reason?: string | null
  failure_note?: string | null
  amount_confirmed: boolean
  amount_confirmed_by?: number | null
  amount_confirmed_at?: string | null
  attachments: AttachmentOut[]
  accepted_by_username?: string | null
  completed_by_username?: string | null
  created_by_username?: string | null
}

export interface Product {
  id: number
  name: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface WebhookStatus {
  registered: boolean
  matches_expected?: boolean
  current_url?: string
  expected_url?: string
  pending_update_count?: number
  last_error_message?: string | null
  code: string
  /** Public base URL currently configured on the server. */
  app_base_url?: string
  /** Pre-flight: is that URL usable as a Telegram webhook? */
  config_ok?: boolean
  config_reason?: string
}

export interface PaymentCountRow {
  currency: string
  amount?: string | null
  quantity: number
}

export interface IneligibleOrder {
  order_id: number
  order_number: string
  currency: string
  amount?: string | null
  order_status: string
  financial_status: string
  reason: string
}

export interface SettlementPreview {
  eligible_order_count: number
  payment_counts: PaymentCountRow[]
  ineligible_orders: IneligibleOrder[]
  already_settled_count: number
  reserved_count: number
  excluded_count: number
}

export interface SettlementOut {
  id: number
  settlement_id: string
  status: string
  settlement_type?: string
  dispatcher_user_id?: number | null
  order_count: number
  filter_conditions: Record<string, unknown>
  created_by_user_id?: number | null
  confirmed_by_user_id?: number | null
  start_date?: string | null
  end_date?: string | null
  note?: string | null
  created_at: string
  confirmed_at?: string | null
}

export interface SettlementFilter {
  start_date?: string | null
  end_date?: string | null
  product?: string | null
  currency?: string | null
  amount?: string | null
  partner?: string | null
  order_status?: string | null
  financial_status?: string | null
  settlement_type?: string | null
  dispatcher_user_id?: number | null
}

export interface AuditLog {
  id: number
  actor_type: string
  actor_user_id?: number | null
  action: string
  entity_type: string
  entity_id: string
  detail?: string | null
  created_at: string
}

export interface SystemSettings {
  default_currency: string
  supported_currencies: string[]
  default_language: string
  telegram_message_language: string
  show_order_id_in_group: boolean
  show_credentials_in_group: boolean
  show_password_in_group: boolean
  allow_any_group_member_to_complete: boolean
  allow_any_group_member_to_fail: boolean
  allow_any_group_member_to_reopen: boolean
  allow_any_group_member_to_close: boolean
  storage_backend: string
  max_upload_size_mb: number
  telegram_configured: boolean
  default_chat_id: string
  allowed_chat_ids: string
  admin_telegram_user_ids: string
  allowed_chat_count: number
}

export interface TelegramSettingsPayload {
  bot_token?: string
  default_chat_id: string
  allowed_chat_ids: string
  admin_telegram_user_ids: string
}

export interface TelegramTestResult {
  ok: boolean
  stage: string
  code: string
  bot_token_configured: boolean
  default_chat_id: string
  tested_chat_id: string
  proxy_configured: boolean
  bot_username?: string
  bot_name?: string
  chat_title?: string
  chat_type?: string
  message_id?: number
}
