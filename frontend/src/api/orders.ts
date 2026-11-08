import api from './client'
import type { Order, OrderEventOut, AttachmentOut, SettlementFilter } from '@/types'

export interface OrderCreatePayload {
  product_id?: number | null
  order_owner_id?: number | null
  product_name?: string | null
  amount?: string | null
  currency?: string
  email?: string | null
  password?: string | null
  login_method?: string | null
  account?: string | null
  account_info?: string | null
  note?: string | null
}

export interface OrderUpdatePayload {
  product_id?: number | null
  product_name?: string | null
  amount?: string | null
  currency?: string | null
  email?: string | null
  password?: string | null
  login_method?: string | null
  account?: string | null
  account_info?: string | null
  note?: string | null
  /** Admin-only: force the order into another state. */
  order_status?: string
  failure_reason?: string
  amount_confirmed?: boolean
  exclude_from_settlement?: boolean
  financial_status?: string | null
}

export async function listOrders(params: { order_status?: string; currency?: string; owner_id?: number; page?: number; page_size?: number }) {
  const { data } = await api.get<Order[]>('/api/orders', { params })
  return data
}

export async function getOrder(id: number) {
  const { data } = await api.get<Order>(`/api/orders/${id}`)
  return data
}

export async function createOrder(payload: OrderCreatePayload) {
  const { data } = await api.post<Order>('/api/orders', payload)
  return data
}

export async function updateOrder(id: number, payload: OrderUpdatePayload) {
  const { data } = await api.patch<Order>(`/api/orders/${id}`, payload)
  return data
}

/** Push an order to the group.
 *
 *  By default this SYNCS IN PLACE -- it rewrites the existing group message
 *  with the order's current state and does not post a duplicate. */
export async function sendOrder(id: number, chatId?: string, forceNew = false) {
  const { data } = await api.post<Order>(`/api/orders/${id}/send`, null, {
    params: {
      ...(chatId ? { chat_id: chatId } : {}),
      ...(forceNew ? { force_new: true } : {}),
    },
  })
  return data
}

/** Re-post the order as a BRAND-NEW group message (the original stays behind).
 *  Use only when the original message was deleted or must be re-pushed. */
export async function retrySend(id: number, chatId?: string) {
  const { data } = await api.post<Order>(`/api/orders/${id}/retry-send`, null, {
    params: chatId ? { chat_id: chatId } : {},
  })
  return data
}

export async function orderEvents(id: number) {
  const { data } = await api.get<OrderEventOut[]>(`/api/orders/${id}/events`)
  return data
}

// ---- Attachments ----
export async function listAttachments(orderId: number) {
  const { data } = await api.get<AttachmentOut[]>(`/api/orders/${orderId}/attachments`)
  return data
}

export async function uploadAttachment(orderId: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<AttachmentOut>(`/api/orders/${orderId}/attachments`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function deleteAttachment(attachmentId: number) {
  await api.delete(`/api/attachments/${attachmentId}`)
}

/** Ask the backend to mint a short-lived signed URL for an attachment.
 * Needed because browser-initiated downloads (<img>/window.open) cannot send
 * the Authorization header. */
export async function attachmentSignedUrl(attachmentId: number) {
  const { data } = await api.get<{ url: string; expires_in: number }>(
    `/api/attachments/${attachmentId}/url`,
  )
  return data.url
}

export function attachmentDownloadUrl(attachmentId: number) {
  const base = import.meta.env.VITE_API_BASE || ''
  return `${base}/api/attachments/${attachmentId}/download`
}

// Re-export so callers can build filters uniformly.
export type { SettlementFilter }
