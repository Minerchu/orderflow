import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import router from '@/router'
import { authStore } from '@/store/auth'

export const TOKEN_KEY = 'orderflow_token'

const baseURL = import.meta.env.VITE_API_BASE || ''

export const api: AxiosInstance = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = authStore().token
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      authStore().clear()
      if (router.currentRoute.value.name !== 'login') {
        router.push({ name: 'login' })
      }
    }
    // Normalize error message from FastAPI {"detail": "..."} shape.
    const detail = error?.response?.data?.detail
    if (detail) error.message = typeof detail === 'string' ? detail : JSON.stringify(detail)
    return Promise.reject(error)
  },
)

export default api
