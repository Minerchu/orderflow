import api from './client'
import type { AuditLog, SystemSettings, TelegramSettingsPayload, TelegramTestResult, WebhookStatus } from '@/types'

export async function listAuditLogs(limit = 200) {
  const { data } = await api.get<AuditLog[]>('/api/admin/audit-logs', { params: { limit } })
  return data
}

export async function getSettings() {
  const { data } = await api.get<SystemSettings>('/api/admin/settings')
  return data
}

export async function updateTelegramSettings(payload: TelegramSettingsPayload) {
  const { data } = await api.put<SystemSettings>('/api/admin/settings/telegram', payload)
  return data
}

/** Diagnose bot/network/group reachability before attempting a real send. */
export async function testTelegramConnection(payload: {
  chat_id?: string
  send_test_message?: boolean
}) {
  const { data } = await api.post<TelegramTestResult>('/api/admin/settings/telegram/test', payload)
  return data
}

/** Whether Telegram knows where to deliver button taps. */
export async function getWebhookStatus() {
  const { data } = await api.get<WebhookStatus>('/api/admin/settings/telegram/webhook')
  return data
}

/** Register the callback URL. Required for inline buttons to do anything. */
export async function registerWebhook(url?: string) {
  const { data } = await api.post<{ ok: boolean; url: string }>(
    '/api/admin/settings/telegram/webhook',
    { url: url ?? null },
  )
  return data
}

/** Persist the public base URL (used to build the webhook URL). */
export async function updatePublicBaseUrl(publicBaseUrl: string) {
  const { data } = await api.put<{ ok: boolean; public_base_url: string }>(
    '/api/admin/settings/public-url',
    { public_base_url: publicBaseUrl },
  )
  return data
}
