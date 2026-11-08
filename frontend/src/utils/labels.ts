// Centralised i18n keys for enum values.
//
// Every status/reason/event shown in the UI goes through these maps so the
// Chinese locale never falls back to raw English enum names.

export const ORDER_STATUS_KEYS: Record<string, string> = {
  draft: 'orders.statusDraft',
  pending: 'orders.statusPending',
  processing: 'orders.statusProcessing',
  completed: 'orders.statusCompleted',
  failed: 'orders.statusFailed',
  closed: 'orders.statusClosed',
}

export const FINANCIAL_STATUS_KEYS: Record<string, string> = {
  unsettled: 'orders.financialUnsettled',
  reserved: 'orders.financialReserved',
  settled: 'orders.financialSettled',
  excluded: 'orders.financialExcluded',
}

export const TELEGRAM_STATUS_KEYS: Record<string, string> = {
  pending: 'orders.tgPending',
  sent: 'orders.tgSent',
  failed: 'orders.tgFailed',
}

export const SETTLEMENT_STATUS_KEYS: Record<string, string> = {
  draft: 'settlements.statusDraft',
  confirmed: 'settlements.statusConfirmed',
  cancelled: 'settlements.statusCancelled',
}

export const EVENT_TYPE_KEYS: Record<string, string> = {
  create: 'orders.eventCreate',
  send: 'orders.eventSend',
  accept: 'orders.eventAccept',
  complete: 'orders.eventComplete',
  fail: 'orders.eventFail',
  reopen: 'orders.eventReopen',
  close: 'orders.eventClose',
  void: 'orders.eventVoid',
  admin_status_change: 'orders.eventAdminStatusChange',
}

export const ACTOR_TYPE_KEYS: Record<string, string> = {
  admin: 'audit.actorAdmin',
  partner: 'audit.actorPartner',
  telegram: 'audit.actorTelegram',
  system: 'audit.actorSystem',
}

export const ENTITY_TYPE_KEYS: Record<string, string> = {
  order: 'audit.entityOrder',
  user: 'audit.entityUser',
  telegram_group: 'audit.entityTelegramGroup',
  settlement: 'audit.entitySettlement',
}

export const AUDIT_ACTION_KEYS: Record<string, string> = {
  order_create: 'audit.actionOrderCreate',
  order_update: 'audit.actionOrderUpdate',
  order_status_override: 'audit.actionOrderStatusOverride',
  order_fail: 'audit.actionOrderFail',
  settlement_reserve: 'audit.actionSettlementReserve',
  settlement_confirm: 'audit.actionSettlementConfirm',
  settlement_cancel: 'audit.actionSettlementCancel',
  partner_access_update: 'audit.actionPartnerAccessUpdate',
  payment_count_check: 'audit.actionPaymentCountCheck',
  attachment_delete: 'audit.actionAttachmentDelete',
  telegram_login_pending: 'audit.actionTelegramLoginPending',
}

export const CHAT_TYPE_KEYS: Record<string, string> = {
  private: 'settings.chatTypePrivate',
  group: 'settings.chatTypeGroup',
  supergroup: 'settings.chatTypeSupergroup',
  channel: 'settings.chatTypeChannel',
}

export function orderStatusKey(value?: string | null): string {
  return (value && ORDER_STATUS_KEYS[value]) || 'orders.statusDraft'
}

export function financialStatusKey(value?: string | null): string {
  return (value && FINANCIAL_STATUS_KEYS[value]) || 'orders.financialUnsettled'
}

export function telegramStatusKey(value?: string | null): string {
  return (value && TELEGRAM_STATUS_KEYS[value]) || 'orders.tgPending'
}

export function settlementStatusKey(value?: string | null): string {
  return (value && SETTLEMENT_STATUS_KEYS[value]) || 'settlements.statusDraft'
}

export function eventTypeKey(value?: string | null): string {
  return (value && EVENT_TYPE_KEYS[value]) || value || ''
}

export function failureReasonKey(value?: string | null): string {
  const map: Record<string, string> = {
    account_not_eligible: 'orders.reasonAccount',
    invalid_account: 'orders.reasonInvalid',
    recharge_failed: 'orders.reasonRecharge',
    other: 'orders.reasonOther',
  }
  return (value && map[value]) || value || ''
}

export function actorTypeKey(value?: string | null): string {
  return (value && ACTOR_TYPE_KEYS[value]) || value || ''
}

export function entityTypeKey(value?: string | null): string {
  return (value && ENTITY_TYPE_KEYS[value]) || value || ''
}

export function auditActionKey(value?: string | null): string {
  return (value && AUDIT_ACTION_KEYS[value]) || value || ''
}

export function chatTypeKey(value?: string | null): string {
  return (value && CHAT_TYPE_KEYS[value]) || value || ''
}

export function languageLabel(value?: string | null): string {
  return value === 'zh-CN' ? 'settings.languageChinese' : 'settings.languageEnglish'
}
