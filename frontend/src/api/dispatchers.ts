import api from './client'
import type { Order, Product, SettlementOut, User } from '@/types'

export interface DispatcherPayload {
  username?: string
  password?: string
  display_name?: string | null
  preferred_language?: string
  chat_ids?: string[]
  default_chat_id?: string | null
  product_ids?: number[]
  is_active?: boolean
}

export interface DispatcherProfile {
  id: number
  username: string
  display_name?: string | null
  role: string
  is_active: boolean
  preferred_language: string
  default_chat_id?: string | null
  chat_ids: string[]
  allowed_product_ids: number[]
  products: Product[]
  telegram_user_id?: string | null
  telegram_username?: string | null
  telegram_bound: boolean
}

export interface BindToken {
  token: string
  expires_in: number
  bot_username?: string | null
  deep_link?: string | null
  command: string
}

// ---- Admin: dispatcher management ----
export async function listDispatchers(): Promise<User[]> {
  const { data } = await api.get<User[]>('/api/admin/dispatchers')
  return data
}

export async function createDispatcher(payload: DispatcherPayload) {
  const { data } = await api.post<User>('/api/admin/dispatchers', payload)
  return data
}

export async function updateDispatcher(id: number, payload: DispatcherPayload) {
  const { data } = await api.put<User>(`/api/admin/dispatchers/${id}`, payload)
  return data
}

export async function unbindDispatcherTelegram(id: number) {
  await api.post(`/api/admin/dispatchers/${id}/unbind-telegram`)
}

// ---- Dispatcher self ----
export async function dispatcherProfile() {
  const { data } = await api.get<DispatcherProfile>('/api/dispatcher/profile')
  return data
}

export async function dispatcherProducts() {
  const { data } = await api.get<Product[]>('/api/dispatcher/products')
  return data
}

export async function dispatcherOrders(params: { order_status?: string } = {}) {
  const { data } = await api.get<Order[]>('/api/dispatcher/orders', { params })
  return data
}

export async function createBindToken() {
  const { data } = await api.post<BindToken>('/api/dispatcher/telegram/bind-token')
  return data
}

export async function unbindTelegram() {
  await api.delete('/api/dispatcher/telegram/bind')
}

export async function dispatcherSettlements() {
  const { data } = await api.get<SettlementOut[]>('/api/dispatcher/settlements')
  return data
}
