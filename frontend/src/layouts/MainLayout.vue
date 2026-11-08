<template>
  <el-container class="layout">
    <!-- Sidebar: fixed on desktop, off-canvas drawer on phones -->
    <el-aside v-if="!isMobile" width="220px" class="aside">
      <div class="logo">{{ t('common.appName') }}</div>
      <el-menu :default-active="activePath" router class="menu">
        <template v-if="auth.isAdmin()">
          <el-menu-item index="/admin/orders">
            <el-icon><Tickets /></el-icon>
            <span>{{ t('menu.orders') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/products">
            <el-icon><Goods /></el-icon>
            <span>{{ t('menu.products') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/partners">
            <el-icon><User /></el-icon>
            <span>{{ t('menu.partners') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/dispatchers">
            <el-icon><Avatar /></el-icon>
            <span>{{ t('menu.dispatchers') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/settlements">
            <el-icon><Money /></el-icon>
            <span>{{ t('menu.settlements') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/audit">
            <el-icon><Document /></el-icon>
            <span>{{ t('menu.auditLogs') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/settings">
            <el-icon><Setting /></el-icon>
            <span>{{ t('menu.settings') }}</span>
          </el-menu-item>
        </template>

        <template v-else-if="auth.isDispatcher()">
          <el-menu-item index="/dispatcher/orders">
            <el-icon><Tickets /></el-icon>
            <span>{{ t('menu.myOrders') }}</span>
          </el-menu-item>
          <el-menu-item index="/dispatcher/account">
            <el-icon><Setting /></el-icon>
            <span>{{ t('menu.account') }}</span>
          </el-menu-item>
        </template>

        <template v-else>
          <el-menu-item index="/partner/orders">
            <el-icon><Tickets /></el-icon>
            <span>{{ t('menu.myOrders') }}</span>
          </el-menu-item>
          <el-menu-item v-if="auth.user?.role === 'partner'" index="/partner/settlements">
            <el-icon><Money /></el-icon>
            <span>{{ t('menu.mySettlements') }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <el-drawer
      v-model="drawerVisible"
      direction="ltr"
      size="78%"
      :with-header="false"
      class="nav-drawer"
    >
      <div class="logo logo--drawer">{{ t('common.appName') }}</div>
      <el-menu :default-active="activePath" router class="menu" @select="drawerVisible = false">
        <template v-if="auth.isAdmin()">
          <el-menu-item index="/admin/orders">
            <el-icon><Tickets /></el-icon><span>{{ t('menu.orders') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/products">
            <el-icon><Goods /></el-icon><span>{{ t('menu.products') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/partners">
            <el-icon><User /></el-icon><span>{{ t('menu.partners') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/dispatchers">
            <el-icon><Avatar /></el-icon><span>{{ t('menu.dispatchers') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/settlements">
            <el-icon><Money /></el-icon><span>{{ t('menu.settlements') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/audit">
            <el-icon><Document /></el-icon><span>{{ t('menu.auditLogs') }}</span>
          </el-menu-item>
          <el-menu-item index="/admin/settings">
            <el-icon><Setting /></el-icon><span>{{ t('menu.settings') }}</span>
          </el-menu-item>
        </template>
        <template v-else-if="auth.isDispatcher()">
          <el-menu-item index="/dispatcher/orders">
            <el-icon><Tickets /></el-icon><span>{{ t('menu.myOrders') }}</span>
          </el-menu-item>
          <el-menu-item index="/dispatcher/account">
            <el-icon><Setting /></el-icon><span>{{ t('menu.account') }}</span>
          </el-menu-item>
        </template>
        <template v-else>
          <el-menu-item index="/partner/orders">
            <el-icon><Tickets /></el-icon><span>{{ t('menu.myOrders') }}</span>
          </el-menu-item>
          <el-menu-item v-if="auth.user?.role === 'partner'" index="/partner/settlements">
            <el-icon><Money /></el-icon><span>{{ t('menu.mySettlements') }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-drawer>

    <el-container class="body">
      <el-header class="header">
        <el-button
          v-if="isMobile"
          class="menu-btn"
          text
          aria-label="menu"
          @click="drawerVisible = true"
        >
          <el-icon :size="22"><Fold /></el-icon>
        </el-button>
        <div class="header-title">{{ pageTitle }}</div>
        <div class="header-right">
          <el-select :model-value="displayTimezone" size="small" class="timezone-select" @change="onTimezone">
            <el-option :label="t('settings.timezoneIndia')" value="Asia/Kolkata" />
            <el-option :label="t('settings.timezoneBeijing')" value="Asia/Shanghai" />
          </el-select>
          <el-select :model-value="locale" size="small" style="width: 96px" @change="onLocale">
            <el-option :label="t('settings.languageEnglish')" value="en" />
            <el-option :label="t('settings.languageChinese')" value="zh-CN" />
          </el-select>
          <span class="user">{{ auth.user?.username }}</span>
          <el-button text type="primary" @click="onLogout">
            <el-icon><SwitchButton /></el-icon>
            <span class="logout-label">{{ t('common.logout') }}</span>
          </el-button>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { authStore } from '@/store/auth'
import { setLocale, currentLocale, type AppLocale } from '@/i18n'
import { displayTimezone, setDisplayTimezone, type DisplayTimezone } from '@/utils/format'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = authStore()

const locale = currentLocale()
const activePath = computed(() => '/' + (route.path.split('/').filter(Boolean)[0] || (auth.isAdmin() ? 'admin' : 'partner')))
const pageTitle = computed(() => (route.meta.title as string) || t('common.appName'))

// Phones get a drawer; anything wider keeps the sidebar.
const isMobile = ref(false)
const drawerVisible = ref(false)

function syncViewport() {
  isMobile.value = window.innerWidth < 768
}

onMounted(() => {
  syncViewport()
  window.addEventListener('resize', syncViewport)
})
onBeforeUnmount(() => window.removeEventListener('resize', syncViewport))

function onLocale(val: AppLocale) {
  setLocale(val)
}

function onTimezone(val: DisplayTimezone) {
  setDisplayTimezone(val)
}

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<style scoped>
.layout {
  /* dvh tracks the mobile URL bar; 100vh makes content jump on iOS. */
  height: 100vh;
  height: 100dvh;
}
.aside {
  background: #ffffff;
  color: #2c2c2a;
  border-right: 0.5px solid #e4e1d8;
}
.body {
  min-width: 0;
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  font-size: 17px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: #2c2c2a;
  border-bottom: 0.5px solid #edeae1;
}
.logo::after {
  content: "";
  width: 22px;
  height: 2px;
  margin-left: 10px;
  background-color: #a32d2d;
}
.logo--drawer {
  color: #2c2c2a;
  border-bottom: 0.5px solid #edeae1;
}
.menu {
  border-right: none;
  background: transparent;
  --el-menu-item-height: 48px;
  font-size: 14px;
  padding: 8px 10px;
}
.menu :deep(.el-menu-item) {
  color: #5f5e5a;
  border-radius: 9px;
  margin-bottom: 2px;
}
.menu :deep(.el-menu-item:hover) {
  background-color: #f1efe8;
  color: #2c2c2a;
}
.menu :deep(.el-menu-item.is-active) {
  color: #a32d2d;
  background: #f5e2e2;
  font-weight: 500;
}
.nav-drawer :deep(.el-drawer__body) {
  padding: 0;
  background: #ffffff;
}
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 0.5px solid #edeae1;
  background: #ffffff;
  /* Respect the notch / home indicator. */
  padding-top: env(safe-area-inset-top);
  padding-left: env(safe-area-inset-left);
  padding-right: env(safe-area-inset-right);
}
.menu-btn {
  padding: 8px;
  margin-left: -6px;
}
.header-title {
  font-size: 16px;
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.user {
  font-size: 13px;
  color: #5f5e5a;
  max-width: 92px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.main {
  background: #faf8f4;
  /* Room for content above the iOS home indicator. */
  padding-bottom: env(safe-area-inset-bottom);
}

@media (max-width: 767px) {
  .header {
    height: 54px;
  }
  .header-title {
    font-size: 16px;
  }
  /* iOS zooms any input whose font is under 16px on focus. */
  .main :deep(.el-input__inner),
  .main :deep(.el-textarea__inner),
  .main :deep(.el-select__placeholder) {
    font-size: 16px;
  }
  .logout-label {
    display: none;
  }
}
</style>
