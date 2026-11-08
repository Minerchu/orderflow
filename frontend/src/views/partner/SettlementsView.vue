<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-head">
          <span>{{ t('menu.mySettlements') }}</span>
          <el-button size="small" @click="load">{{ t('common.refresh') }}</el-button>
        </div>
      </template>

      <el-alert
        type="info"
        :closable="false"
        :title="t('partners.onlyMyBatches')"
        style="margin-bottom: 10px"
      />

      <el-table :data="settlements" v-loading="loading" :empty-text="t('orders.noData')">
        <el-table-column :label="t('settlements.batchId')" prop="settlement_id" width="170" />
        <el-table-column :label="t('settlements.statusDraft')" width="130">
          <template #default="{ row }">
            <el-tag :type="settlementStatusTag(row.status)">
              {{ t(settlementStatusKey(row.status)) }}
            </el-tag>
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
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { partnerSettlements } from '@/api/partners'
import { settlementStatusTag, formatDateTime } from '@/utils/format'
import { settlementStatusKey } from '@/utils/labels'
import type { SettlementOut } from '@/types'

const { t } = useI18n()
const settlements = ref<SettlementOut[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    settlements.value = await partnerSettlements()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
