export const ORDER_STATUSES = ['draft', 'pending', 'processing', 'completed', 'failed', 'closed']
export const FINANCIAL_STATUSES = ['unsettled', 'reserved', 'settled', 'excluded']
export const SETTLEMENT_STATUSES = ['draft', 'confirmed', 'cancelled']

// el-tag type per status
export function orderStatusTag(status: string): 'info' | 'warning' | 'success' | 'danger' | 'primary' {
  switch (status) {
    case 'completed':
      return 'success'
    case 'processing':
      return 'warning'
    case 'failed':
      return 'danger'
    case 'closed':
      return 'info'
    case 'pending':
      return 'primary'
    default:
      return 'info'
  }
}

export function financialStatusTag(status: string): 'info' | 'warning' | 'success' | 'danger' | 'primary' {
  switch (status) {
    case 'settled':
      return 'success'
    case 'reserved':
      return 'warning'
    case 'excluded':
      return 'info'
    default:
      return 'primary'
  }
}

export function settlementStatusTag(status: string): 'info' | 'success' | 'danger' {
  switch (status) {
    case 'confirmed':
      return 'success'
    case 'cancelled':
      return 'danger'
    default:
      return 'info'
  }
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (isNaN(d.getTime())) return value
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: displayTimezone.value,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(d)
  const part = (type: string) => parts.find((item) => item.type === type)?.value || ''
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`
}

export function formatAmount(amount?: string | null, currency?: string): string {
  if (amount === null || amount === undefined || amount === '') return '-'
  return `${amount} ${currency || ''}`.trim()
}
import { ref } from 'vue'

export type DisplayTimezone = 'Asia/Kolkata' | 'Asia/Shanghai'
const TIMEZONE_KEY = 'orderflow_display_timezone'
const initialTimezone = (() => {
  if (typeof localStorage === 'undefined') return 'Asia/Shanghai'
  const saved = localStorage.getItem(TIMEZONE_KEY)
  return saved === 'Asia/Kolkata' ? 'Asia/Kolkata' : 'Asia/Shanghai'
})()
export const displayTimezone = ref<DisplayTimezone>(initialTimezone)

export function setDisplayTimezone(value: DisplayTimezone) {
  displayTimezone.value = value
  if (typeof localStorage !== 'undefined') localStorage.setItem(TIMEZONE_KEY, value)
}

