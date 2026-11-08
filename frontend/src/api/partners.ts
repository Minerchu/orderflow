import api from './client'
import type { User, Order, SettlementOut, PaymentCountRow } from '@/types'

export interface PartnerGroup { chat_id: string; order_count: number }
export interface PartnerCountRow extends PaymentCountRow { checked: boolean; checked_at?: string | null }
export interface PartnerSettlementRow { id: number; settlement_id: string; settled_at: string; order_count: number }
export interface PartnerSettlementDetails {
  settlement_id: string
  settled_at: string
  order_count: number
  orders: Order[]
}

// ---- Admin: partner management ----
export interface PartnerPayload {
  username: string
  password: string
  telegram_user_id?: string | null
  telegram_username?: string | null
  preferred_language?: string
}

export async function listPartners() {
  const { data } = await api.get<User[]>('/api/admin/partners')
  return data
}

export async function createPartner(payload: PartnerPayload) {
  const { data } = await api.post<User>('/api/admin/partners', payload)
  return data
}

export async function setPartnerActive(id: number, isActive: boolean) {
  const { data } = await api.patch<User>(`/api/admin/partners/${id}`, { is_active: isActive })
  return data
}

export async function partnerGroups() {
  const { data } = await api.get<PartnerGroup[]>('/api/admin/partners/chat-groups')
  return data
}

export async function updatePartnerAccess(id: number, chatIds: string[], isActive: boolean) {
  const { data } = await api.put(`/api/admin/partners/${id}/access`, { chat_ids: chatIds, is_active: isActive })
  return data
}

// ---- Partner self endpoints ----
export interface PartnerDashboard {
  completed_orders: number
  unsettled: number
  settled: number
  processing: number
  failed: number
  payment_counts: { currency: string; amount: string | null; quantity: number }[]
}

export async function partnerDashboard() {
  const { data } = await api.get<PartnerDashboard>('/api/partner/dashboard')
  return data
}

export async function workerGroups() {
  const { data } = await api.get<PartnerGroup[]>('/api/partner/groups')
  return data
}

export async function partnerOrders(params: { chat_id?: string; order_status?: string; financial_status?: string } = {}) {
  const { data } = await api.get<Order[]>('/api/partner/orders', { params })
  return data
}

export async function partnerSettlements() {
  const { data } = await api.get<SettlementOut[]>('/api/partner/settlements')
  return data
}

export async function partnerPaymentCounts(chatId?: string) {
  const { data } = await api.get<PartnerCountRow[]>('/api/partner/payment-counts', { params: chatId ? { chat_id: chatId } : {} })
  return data
}

export async function checkPartnerPaymentCount(chatId: string, currency: string, amount: string) {
  const { data } = await api.post('/api/partner/payment-counts/check', { chat_id: chatId, currency, amount })
  return data
}

export async function partnerSettledHistory(chatId?: string) {
  const { data } = await api.get<PartnerSettlementRow[]>('/api/partner/settlement-history', {
    params: chatId ? { chat_id: chatId } : {},
  })
  return data
}

export async function partnerSettledDetails(batchId: number, chatId?: string) {
  const { data } = await api.get<PartnerSettlementDetails>(`/api/partner/settlement-history/${batchId}`, {
    params: chatId ? { chat_id: chatId } : {},
  })
  return data
}
