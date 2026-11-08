import { defineStore } from 'pinia'
import { ref } from 'vue'
import api, { TOKEN_KEY } from '@/api/client'
import type { TokenOut, User } from '@/types'
import { setLocale, LOCALE_STORAGE_KEY } from '@/i18n'

export const authStore = defineStore('auth', () => {
  const token = ref<string>('')
  const user = ref<User | null>(null)

  /** The admin sets each account's language in the panel; honour it on login
   *  instead of leaving the UI at whatever the browser had before. */
  function applyPreferredLocale(u: User | null) {
    const lang = u?.preferred_language
    if (lang === 'zh-CN' || lang === 'en') setLocale(lang)
  }

  function hydrate() {
    const saved = localStorage.getItem(TOKEN_KEY)
    if (saved) {
      token.value = saved
      // Best-effort: refetch profile so we have the user object + role.
      api
        .get<User>('/api/auth/me')
        .then((r) => {
          user.value = r.data
          // A fresh browser has no stored choice yet -> use the account's
          // language. An explicit pick from the header switch wins afterwards.
          if (!localStorage.getItem(LOCALE_STORAGE_KEY)) applyPreferredLocale(r.data)
        })
        .catch(() => clear())
    }
  }

  async function login(username: string, password: string): Promise<User> {
    const r = await api.post<TokenOut>('/api/auth/login', { username, password })
    token.value = r.data.access_token
    user.value = r.data.user
    localStorage.setItem(TOKEN_KEY, token.value)
    applyPreferredLocale(r.data.user)
    return r.data.user
  }

  function setSession(accessToken: string, profile: User) {
    token.value = accessToken
    user.value = profile
    localStorage.setItem(TOKEN_KEY, accessToken)
    applyPreferredLocale(profile)
  }

  function clear() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
  }

  function logout() {
    clear()
  }

  const isAdmin = () => user.value?.role === 'admin'
  const isPartner = () => user.value?.role === 'partner' || user.value?.role === 'worker'
  const isDispatcher = () => user.value?.role === 'dispatcher'

  return { token, user, hydrate, login, setSession, clear, logout, isAdmin, isPartner, isDispatcher }
})
