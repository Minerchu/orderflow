<template>
  <div>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate">{{ t('dispatchers.create') }}</el-button>
      <el-button @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-alert
      type="info"
      :closable="false"
      :title="t('dispatchers.hint')"
      class="hint-block"
    />

    <el-table :data="rows" v-loading="loading" :empty-text="t('orders.noData')">
      <el-table-column :label="t('common.username')" min-width="150">
        <template #default="{ row }">
          <div>{{ row.display_name || row.username }}</div>
          <div class="sub">{{ row.username }}</div>
        </template>
      </el-table-column>
      <el-table-column :label="t('dispatchers.telegram')" min-width="150">
        <template #default="{ row }">
          <el-tag v-if="row.telegram_bound" type="success">
            {{ row.telegram_username ? '@' + row.telegram_username : row.telegram_user_id }}
          </el-tag>
          <el-tag v-else type="info">{{ t('dispatchers.notBound') }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('dispatchers.sendGroups')" min-width="150">
        <template #default="{ row }">
          <el-tag v-for="id in row.assigned_chat_ids" :key="id" class="tag">{{ id }}</el-tag>
          <div v-if="row.default_chat_id" class="sub">
            {{ t('dispatchers.defaultGroup') }}: {{ row.default_chat_id }}
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('dispatchers.products')" min-width="180">
        <template #default="{ row }">
          <el-tag v-for="name in productNames(row.allowed_product_ids)" :key="name" class="tag">
            {{ name }}
          </el-tag>
          <span v-if="!row.allowed_product_ids?.length" class="sub">{{ t('dispatchers.noProducts') }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('partners.active')" width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'">
            {{ row.is_active ? t('partners.active') : t('partners.inactive') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="250" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
          <el-button text type="warning" @click="onToggle(row)">
            {{ row.is_active ? t('partners.inactive') : t('partners.active') }}
          </el-button>
          <el-button v-if="row.telegram_bound" text type="danger" @click="onUnbind(row)">
            {{ t('dispatchers.unbind') }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? t('dispatchers.edit') : t('dispatchers.create')" width="560px">
      <el-form :model="form" label-position="top">
        <el-form-item :label="t('common.username')" required>
          <el-input v-model="form.username" :disabled="editing" />
        </el-form-item>
        <el-form-item :label="t('common.password')" :required="!editing">
          <el-input v-model="form.password" show-password :placeholder="editing ? t('dispatchers.passwordKeep') : ''" />
        </el-form-item>
        <el-form-item :label="t('dispatchers.displayName')">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item :label="t('dispatchers.sendGroups')" required>
          <el-select v-model="form.chat_ids" multiple filterable style="width: 100%">
            <el-option v-for="g in groups" :key="g.chat_id" :value="g.chat_id"
              :label="`${g.chat_id} (${g.order_count})`" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('dispatchers.defaultGroup')" required>
          <el-select v-model="form.default_chat_id" style="width: 100%" clearable>
            <el-option v-for="id in form.chat_ids" :key="id" :value="id" :label="id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('dispatchers.products')">
          <el-select v-model="form.product_ids" multiple filterable style="width: 100%">
            <el-option v-for="p in products" :key="p.id" :value="p.id" :label="p.name" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('partners.language')">
          <el-select v-model="form.preferred_language" style="width: 100%">
            <el-option :label="t('settings.languageEnglish')" value="en" />
            <el-option :label="t('settings.languageChinese')" value="zh-CN" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createDispatcher, listDispatchers, updateDispatcher, unbindDispatcherTelegram,
  type DispatcherPayload,
} from '@/api/dispatchers'
import { partnerGroups, type PartnerGroup } from '@/api/partners'
import { listProducts } from '@/api/products'
import type { Product, User } from '@/types'

const { t } = useI18n()

interface Row extends User {
  allowed_product_ids: number[]
  telegram_bound: boolean
}

const rows = ref<Row[]>([])
const groups = ref<PartnerGroup[]>([])
const products = ref<Product[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref<Row | null>(null)
const form = ref<DispatcherPayload>(emptyForm())

function emptyForm(): DispatcherPayload {
  return {
    username: '', password: '', display_name: '', preferred_language: 'en',
    chat_ids: [], default_chat_id: null, product_ids: [], is_active: true,
  }
}

function productNames(ids?: number[]): string[] {
  return (ids || []).map((id) => products.value.find((p) => p.id === id)?.name || `#${id}`)
}

async function load() {
  loading.value = true
  try {
    const [d, g, p] = await Promise.all([listDispatchers(), partnerGroups(), listProducts()])
    rows.value = d as Row[]
    groups.value = g
    products.value = p
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: Row) {
  editing.value = row
  form.value = {
    username: row.username,
    password: '',
    display_name: row.display_name || '',
    preferred_language: row.preferred_language || 'en',
    chat_ids: [...(row.assigned_chat_ids || [])],
    default_chat_id: row.default_chat_id || null,
    product_ids: [...(row.allowed_product_ids || [])],
    is_active: row.is_active,
  }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.chat_ids?.length) {
    ElMessage.warning(t('dispatchers.groupRequired'))
    return
  }
  if (!form.value.default_chat_id) {
    ElMessage.warning(t('dispatchers.defaultRequired'))
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const payload = { ...form.value }
      if (!payload.password) delete payload.password
      await updateDispatcher(editing.value.id, payload)
    } else {
      await createDispatcher(form.value)
    }
    ElMessage.success(t('common.success'))
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    saving.value = false
  }
}

async function onToggle(row: Row) {
  try {
    await updateDispatcher(row.id, { is_active: !row.is_active })
    ElMessage.success(t('common.success'))
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  }
}

async function onUnbind(row: Row) {
  await ElMessageBox.confirm(t('dispatchers.unbindConfirm'), t('common.confirm'), { type: 'warning' })
  try {
    await unbindDispatcherTelegram(row.id)
    ElMessage.success(t('common.success'))
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; gap: 10px; margin-bottom: 12px; }
.hint-block { margin-bottom: 12px; }
.tag { margin: 2px 6px 2px 0; }
.sub { color: #909399; font-size: 12px; }
</style>
