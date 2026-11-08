import { createI18n } from 'vue-i18n'
import en from './en'
import zhCN from './zh-CN'

export type AppLocale = 'en' | 'zh-CN'

export const LOCALE_STORAGE_KEY = 'orderflow_locale'

function detectLocale(): AppLocale {
  const saved = localStorage.getItem(LOCALE_STORAGE_KEY)
  if (saved === 'en' || saved === 'zh-CN') return saved
  // First visit: a Chinese browser should not land on an English login page.
  return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh-CN' : 'en'
}

const stored: AppLocale = detectLocale()

export const i18n = createI18n({
  legacy: false,
  locale: stored,
  fallbackLocale: 'en',
  messages: {
    en,
    'zh-CN': zhCN,
  },
})

export function setLocale(locale: AppLocale) {
  i18n.global.locale.value = locale
  localStorage.setItem(LOCALE_STORAGE_KEY, locale)
}

export function currentLocale(): AppLocale {
  return (i18n.global.locale.value as AppLocale) || 'en'
}

export default i18n
