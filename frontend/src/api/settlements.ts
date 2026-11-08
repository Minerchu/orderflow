import api from './client'
import type { SettlementPreview, SettlementOut, SettlementFilter } from '@/types'

export async function previewSettlement(filter: SettlementFilter) {
  const { data } = await api.post<SettlementPreview>('/api/settlements/preview', filter)
  return data
}

export async function listSettlements() {
  const { data } = await api.get<SettlementOut[]>('/api/settlements')
  return data
}

export async function getSettlement(id: string) {
  const { data } = await api.get<SettlementOut>(`/api/settlements/${id}`)
  return data
}

export async function createSettlement(filter: SettlementFilter & { note?: string }) {
  const { data } = await api.post<SettlementOut>('/api/settlements', filter)
  return data
}

export async function confirmSettlement(id: string) {
  const { data } = await api.post<SettlementOut>(`/api/settlements/${id}/confirm`)
  return data
}

export async function cancelSettlement(id: string) {
  const { data } = await api.post<SettlementOut>(`/api/settlements/${id}/cancel`)
  return data
}

export async function exportSettlement(id: string) {
  const { data } = await api.get(`/api/settlements/${id}/export`, { responseType: 'blob' })
  return data as Blob
}

export function exportSettlementUrl(id: string) {
  const base = import.meta.env.VITE_API_BASE || ''
  return `${base}/api/settlements/${id}/export`
}
