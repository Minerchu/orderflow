<template>
  <div>
    <div class="toolbar">
      <el-button type="primary" @click="onCreate">{{ t('partners.create') }}</el-button>
      <el-button @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-table :data="partners" v-loading="loading" :empty-text="t('orders.noData')">
      <el-table-column :label="t('common.username')" min-width="150">
        <template #default="{ row }">{{ row.display_name || row.username }}</template>
      </el-table-column>
      <el-table-column :label="t('partners.telegramId')" prop="telegram_user_id" min-width="120" />
      <el-table-column :label="t('partners.telegramHandle')" prop="telegram_username" min-width="130" />
      <el-table-column :label="t('partners.lastLogin')" min-width="160">
        <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('partners.groupAccess')" min-width="180">
        <template #default="{ row }">
          <el-tag v-for="id in row.assigned_chat_ids || []" :key="id" class="group-tag">{{ id }}</el-tag>
          <span v-if="!row.assigned_chat_ids?.length">—</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('partners.active')" width="150">
        <template #default="{ row }">
          <el-tag v-if="row.role === 'worker' && !row.is_active" type="warning">{{ t('partners.pendingApproval') }}</el-tag>
          <el-tag v-else :type="row.is_active ? 'success' : 'danger'">{{ row.is_active ? t('partners.active') : t('partners.inactive') }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="150" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="openAccess(row)">{{ t('partners.groupAccess') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="accessVisible" :title="t('partners.groupAccess')" width="520px">
      <p v-if="selectedPartner?.role === 'worker' && !selectedPartner.is_active" class="hint">
        {{ t('partners.pendingHint') }}
      </p>
      <div class="access-user">{{ selectedPartner?.display_name || (selectedPartner?.telegram_username ? `@${selectedPartner.telegram_username}` : selectedPartner?.username) }}</div>
      <el-form label-position="top">
        <el-form-item :label="t('partners.assignedGroups')">
          <el-select v-model="selectedChats" multiple filterable collapse-tags style="width: 100%">
            <el-option v-for="group in groups" :key="group.chat_id" :value="group.chat_id"
              :label="`${group.chat_id} · ${group.order_count} ${t('partners.orderCountUnit')}`" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="accessActive">{{ t('partners.allowLogin') }}</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accessVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="saveAccess">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createVisible" :title="t('partners.newPartner')" width="420px">
      <el-form :model="form" label-width="130px">
        <el-form-item :label="t('common.username')" required><el-input v-model="form.username" /></el-form-item>
        <el-form-item :label="t('common.password')" required><el-input v-model="form.password" show-password /></el-form-item>
        <el-form-item :label="t('partners.telegramId')"><el-input v-model="form.telegram_user_id" /></el-form-item>
        <el-form-item :label="t('partners.telegramHandle')"><el-input v-model="form.telegram_username" /></el-form-item>
        <el-form-item :label="t('partners.language')">
          <el-select v-model="form.preferred_language" style="width: 100%">
            <el-option :label="t('settings.languageEnglish')" value="en" /><el-option :label="t('settings.languageChinese')" value="zh-CN" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { createPartner, listPartners, partnerGroups, updatePartnerAccess, type PartnerPayload, type PartnerGroup } from '@/api/partners'
import { formatDateTime } from '@/utils/format'
import type { User } from '@/types'

const { t } = useI18n()
const partners = ref<User[]>([])
const groups = ref<PartnerGroup[]>([])
const loading = ref(false)
const saving = ref(false)
const createVisible = ref(false)
const accessVisible = ref(false)
const selectedPartner = ref<User | null>(null)
const selectedChats = ref<string[]>([])
const accessActive = ref(false)
const form = ref<PartnerPayload>({ username: '', password: '', telegram_user_id: null, telegram_username: null, preferred_language: 'en' })

async function load() {
  loading.value = true
  try {
    const [users, chats] = await Promise.all([listPartners(), partnerGroups()])
    partners.value = users
    groups.value = chats
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

function onCreate() {
  form.value = { username: '', password: '', telegram_user_id: null, telegram_username: null, preferred_language: 'en' }
  createVisible.value = true
}

async function submit() {
  saving.value = true
  try {
    await createPartner(form.value)
    ElMessage.success(t('partners.created'))
    createVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || 'create failed')
  } finally {
    saving.value = false
  }
}

function openAccess(user: User) {
  selectedPartner.value = user
  selectedChats.value = [...(user.assigned_chat_ids || [])]
  accessActive.value = user.is_active
  accessVisible.value = true
}

async function saveAccess() {
  if (!selectedPartner.value) return
  saving.value = true
  try {
    await updatePartnerAccess(selectedPartner.value.id, selectedChats.value, accessActive.value)
    ElMessage.success(t('common.success'))
    accessVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || 'save failed')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; gap: 10px; margin-bottom: 12px; }
.group-tag { margin: 2px 4px 2px 0; }
.access-user { margin-bottom: 14px; font-weight: 600; }
.hint { color: #9a6700; }
</style>
