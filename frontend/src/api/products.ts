import api from './client'
import type { Product } from '@/types'

/** A product type is just a name. */
export interface ProductPayload {
  name: string
  is_active?: boolean
}

export async function listProducts() {
  const { data } = await api.get<Product[]>('/api/products')
  return data
}

export async function createProduct(payload: ProductPayload) {
  const { data } = await api.post<Product>('/api/products', payload)
  return data
}

export async function updateProduct(id: number, payload: Partial<ProductPayload>) {
  const { data } = await api.patch<Product>(`/api/products/${id}`, payload)
  return data
}

export async function deleteProduct(id: number) {
  await api.delete(`/api/products/${id}`)
}