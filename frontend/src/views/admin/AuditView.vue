<template>
  <div>
    <div class="toolbar">
      <el-button @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-table :data="logs" v-loading="loading" :empty-text="t('orders.noData')">
      <el-table-column :label="t('audit.time')" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('audit.actor')" width="140">
        <template #default="{ row }">
          <el-tag size="small" :type="row.actor_type === 'admin' ? 'primary' : 'info'">
            {{ t(actorTypeKey(row.actor_type)) }}
          </el-tag>
          <span v-if="row.actor_user_id"> #{{ row.actor_user_id }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.action')" width="180">
        <template #default="{ row }">{{ t(auditActionKey(row.action)) }}</template>
      </el-table-column>
      <el-table-column :label="t('audit.entity')" width="220">
        <template #default="{ row }">
          <span>{{ t(entityTypeKey(row.entity_type)) }}</span>
          <span v-if="row.entity_id" class="dim"> / {{ row.entity_id }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.detail')" prop="detail" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { listAuditLogs } from '@/api/admin'
import { formatDateTime } from '@/utils/format'
import { actorTypeKey, auditActionKey, entityTypeKey } from '@/utils/labels'
import type { AuditLog } from '@/types'

const { t } = useI18n()
const logs = ref<AuditLog[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    logs.value = await listAuditLogs(200)
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
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
.dim {
  color: #909399;
}
</style>
