<template>
  <div class="account-page">
    <el-card v-loading="loading">
      <template #header>{{ t('account.title') }}</template>
      <el-descriptions v-if="profile" :column="1" border size="small">
        <el-descriptions-item :label="t('common.username')">{{ profile.username }}</el-descriptions-item>
        <el-descriptions-item :label="t('dispatchers.displayName')">{{ profile.display_name || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('dispatchers.products')">
          <el-tag v-for="p in profile.products" :key="p.id" class="tag">{{ p.name }}</el-tag>
          <span v-if="!profile.products.length" class="sub">{{ t('dispatcherPage.noProducts') }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card>
      <template #header>
        <div class="card-head">
          <span>{{ t('account.telegram') }}</span>
          <el-button size="small" @click="loadProfile">{{ t('common.refresh') }}</el-button>
        </div>
      </template>

      <div v-if="profile" class="tg-row">
        <div>
          <el-tag :type="profile.telegram_bound ? 'success' : 'info'" size="large">
            {{ profile.telegram_bound ? t('dispatchers.bound') : t('dispatchers.notBound') }}
          </el-tag>
          <span v-if="profile.telegram_bound" class="tg-name">
            {{ profile.telegram_username ? '@' + profile.telegram_username : profile.telegram_user_id }}
          </span>
        </div>
        <div class="tg-actions">
          <el-button v-if="!profile.telegram_bound" type="primary" @click="startBind">
            {{ t('account.bindTelegram') }}
          </el-button>
          <el-button v-else type="danger" plain @click="onUnbind">{{ t('account.unbind') }}</el-button>
        </div>
      </div>

      <el-alert
        type="info"
        :closable="false"
        :title="t('account.bindHint')"
        class="tg-hint"
      />
    </el-card>

    <el-card>
      <template #header>{{ t('account.mySettlements') }}</template>
      <el-table :data="settlements" :empty-text="t('orders.noData')">
        <el-table-column :label="t('settlements.batchId')" prop="settlement_id" width="170" />
        <el-table-column :label="t('settlements.statusDraft')" width="120">
          <template #default="{ row }">
            <el-tag :type="settlementStatusTag(row.status)">{{ t(settlementStatusKey(row.status)) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('settlements.orderCount')" prop="order_count" width="110" />
        <el-table-column :label="t('settlements.createdAt')" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('settlements.confirmedAt')" width="170">
          <template #default="{ row }">{{ formatDateTime(row.confirmed_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="bindVisible" :title="t('account.bindTelegram')" width="460px" @closed="stopPolling">
      <div v-if="bindToken">
        <el-alert
          v-if="bindToken.deep_link"
          type="success"
          :closable="false"
          :title="t('account.stepOpen')"
          class="bind-block"
        />
        <el-button
          v-if="bindToken.deep_link"
          type="primary"
          size="large"
          class="bind-open"
          @click="openTelegram"
        >
          {{ t('account.openTelegram') }}
        </el-button>

        <el-divider>{{ t('account.orCommand') }}</el-divider>
        <div class="bind-command">{{ bindToken.command }}</div>
        <el-button size="small" class="bind-copy" @click="copyCommand">{{ t('account.copy') }}</el-button>

        <el-divider />
        <div class="bind-expire">{{ t('account.expiresIn') }}: {{ countdown }}s</div>
        <el-button text type="primary" @click="startBind">{{ t('account.regenerate') }}</el-button>
      </div>
      <el-empty v-else :description="t('account.preparing')" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createBindToken, dispatcherProfile, dispatcherSettlements, unbindTelegram,
  type BindToken, type DispatcherProfile,
} from '@/api/dispatchers'
import { settlementStatusTag, formatDateTime } from '@/utils/format'
import { settlementStatusKey } from '@/utils/labels'
import type { SettlementOut } from '@/types'

const { t } = useI18n()
const loading = ref(false)
const profile = ref<DispatcherProfile | null>(null)
const settlements = ref<SettlementOut[]>([])
const bindVisible = ref(false)
const bindToken = ref<BindToken | null>(null)
const countdown = ref(0)
let timer: number | undefined
let pollTimer: number | undefined

async function loadProfile() {
  loading.value = true
  try {
    profile.value = await dispatcherProfile()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

async function loadSettlements() {
  try {
    settlements.value = await dispatcherSettlements()
  } catch {
    settlements.value = []
  }
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
}

// The bind happens in Telegram, outside this tab. Poll the profile so the
// dialog closes by itself once the bot confirms, instead of asking the user
// to guess whether it worked and refresh manually.
function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      const p = await dispatcherProfile()
      if (p.telegram_bound) {
        profile.value = p
        stopPolling()
        bindVisible.value = false
        ElMessage.success(t('account.boundSuccess'))
      }
    } catch {
      // Keep polling: a transient network error is not a bind failure.
    }
  }, 3000)
}

async function startBind() {
  bindVisible.value = true
  bindToken.value = null
  try {
    const token = await createBindToken()
    bindToken.value = token
    countdown.value = token.expires_in
    if (timer) window.clearInterval(timer)
    timer = window.setInterval(() => {
      countdown.value -= 1
      if (countdown.value <= 0) {
        window.clearInterval(timer)
        timer = undefined
        bindVisible.value = false
        ElMessage.warning(t('account.expired'))
      }
    }, 1000)
    startPolling()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
    bindVisible.value = false
  }
}

function openTelegram() {
  if (bindToken.value?.deep_link) window.open(bindToken.value.deep_link, '_blank')
}

async function copyCommand() {
  if (!bindToken.value) return
  try {
    await navigator.clipboard.writeText(bindToken.value.command)
    ElMessage.success(t('account.copied'))
  } catch {
    ElMessage.warning(bindToken.value.command)
  }
}

async function onUnbind() {
  await ElMessageBox.confirm(t('account.unbindConfirm'), t('common.confirm'), { type: 'warning' })
  try {
    await unbindTelegram()
    ElMessage.success(t('common.success'))
    await loadProfile()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  }
}

onMounted(async () => {
  await loadProfile()
  await loadSettlements()
})
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  stopPolling()
})
</script>

<style scoped>
.account-page { display: grid; gap: 14px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.tg-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.tg-name { margin-left: 10px; color: #606266; }
.tg-hint { margin-top: 14px; }
.tag { margin: 2px 6px 2px 0; }
.sub { color: #909399; font-size: 12px; }
.bind-block { margin-bottom: 12px; }
.bind-open { width: 100%; margin-bottom: 8px; }
.bind-command { font-family: ui-monospace, monospace; font-size: 16px; padding: 10px 12px; background: #f5f7fa; border-radius: 8px; word-break: break-all; }
.bind-copy { margin-top: 8px; }
.bind-expire { color: #909399; font-size: 13px; margin-bottom: 6px; }
</style>
