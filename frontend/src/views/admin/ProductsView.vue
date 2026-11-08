<template>
  <div>
    <div class="toolbar">
      <el-button type="primary" @click="onCreate">{{ t('products.create') }}</el-button>
      <el-button @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-alert type="info" :closable="false" :title="t('products.hint')" class="hint" />

    <el-table :data="products" v-loading="loading" :empty-text="t('products.empty')">
      <el-table-column :label="t('products.name')" prop="name" />
      <el-table-column :label="t('products.active')" width="110">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? t('common.yes') : t('common.no') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="170" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="onEdit(row)">{{ t('common.edit') }}</el-button>
          <el-button text type="danger" @click="onDelete(row)">{{ t('common.delete') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="visible"
      :title="editing ? t('products.edit') : t('products.create')"
      width="min(420px, calc(100vw - 24px))"
    >
      <el-form :model="form" label-position="top">
        <el-form-item :label="t('products.name')" required>
          <el-input
            v-model.trim="form.name"
            :placeholder="t('products.namePlaceholder')"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-form-item :label="t('products.active')">
          <el-switch v-model="form.is_active" />
          <div class="help">{{ t('products.activeHint') }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listProducts, createProduct, updateProduct, deleteProduct } from '@/api/products'
import { describeSendError } from '@/utils/errors'
import type { Product } from '@/types'

const { t } = useI18n()
const products = ref<Product[]>([])
const loading = ref(false)
const visible = ref(false)
const saving = ref(false)
const editing = ref<Product | null>(null)

const form = ref({ name: '', is_active: true })

async function load() {
  loading.value = true
  try {
    products.value = await listProducts()
  } catch (e: any) {
    ElMessage.error(describeSendError(e))
  } finally {
    loading.value = false
  }
}

function onCreate() {
  editing.value = null
  form.value = { name: '', is_active: true }
  visible.value = true
}

function onEdit(row: Product) {
  editing.value = row
  form.value = { name: row.name, is_active: row.is_active }
  visible.value = true
}

async function submit() {
  if (!form.value.name) {
    ElMessage.warning(t('products.nameRequired'))
    return
  }
  saving.value = true
  try {
    if (editing.value) await updateProduct(editing.value.id, { ...form.value })
    else await createProduct({ ...form.value })
    ElMessage.success(t('common.success'))
    visible.value = false
    load()
  } catch (e: any) {
    // Turns a bare 500 / error code into a readable cause + fix.
    ElMessage.error(describeSendError(e))
  } finally {
    saving.value = false
  }
}

async function onDelete(row: Product) {
  try {
    await ElMessageBox.confirm(
      t('products.deleteConfirm', { name: row.name }),
      t('common.confirm'),
      { type: 'warning' },
    )
  } catch {
    return // user cancelled
  }
  try {
    await deleteProduct(row.id)
    ElMessage.success(t('common.success'))
    load()
  } catch (e: any) {
    ElMessage.error(describeSendError(e))
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.hint {
  margin-bottom: 12px;
}
.help {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}
</style>