import { createRouter, createWebHistory } from 'vue-router'
import { authStore } from '@/store/auth'

function landing(auth: ReturnType<typeof authStore>): string {
  if (auth.user?.role === 'admin') return '/admin/orders'
  if (auth.user?.role === 'dispatcher') return '/dispatcher/orders'
  return '/partner/orders'
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      redirect: () => landing(authStore()),
      children: [
        // Admin
        { path: 'admin/orders', name: 'admin-orders', component: () => import('@/views/admin/OrdersView.vue'), meta: { role: 'admin' } },
        { path: 'admin/products', name: 'admin-products', component: () => import('@/views/admin/ProductsView.vue'), meta: { role: 'admin' } },
        { path: 'admin/partners', name: 'admin-partners', component: () => import('@/views/admin/PartnersView.vue'), meta: { role: 'admin' } },
        { path: 'admin/dispatchers', name: 'admin-dispatchers', component: () => import('@/views/admin/DispatchersView.vue'), meta: { role: 'admin' } },
        { path: 'admin/settlements', name: 'admin-settlements', component: () => import('@/views/admin/SettlementsView.vue'), meta: { role: 'admin' } },
        { path: 'admin/audit', name: 'admin-audit', component: () => import('@/views/admin/AuditView.vue'), meta: { role: 'admin' } },
        { path: 'admin/settings', name: 'admin-settings', component: () => import('@/views/admin/SettingsView.vue'), meta: { role: 'admin' } },
        // Partner
        { path: 'partner/orders', name: 'partner-orders', component: () => import('@/views/partner/OrdersView.vue'), meta: { role: 'partner' } },
        { path: 'partner/settlements', name: 'partner-settlements', component: () => import('@/views/partner/SettlementsView.vue'), meta: { role: 'partner' } },
        // Dispatcher
        { path: 'dispatcher/orders', name: 'dispatcher-orders', component: () => import('@/views/dispatcher/OrdersView.vue'), meta: { role: 'dispatcher' } },
        { path: 'dispatcher/account', name: 'dispatcher-account', component: () => import('@/views/dispatcher/AccountView.vue'), meta: { role: 'dispatcher' } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const auth = authStore()
  const loggedIn = !!auth.token

  if (!to.meta.public && !loggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && loggedIn) {
    return landing(auth)
  }
  // Role gate
  const requiredRole = to.meta.role as string | undefined
  if (requiredRole && auth.user && auth.user.role !== requiredRole &&
      !(requiredRole === 'partner' && auth.user.role === 'worker')) {
    return landing(auth)
  }
  return true
})

export default router
