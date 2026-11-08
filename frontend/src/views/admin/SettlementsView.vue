<template>
  <div>
    <el-card class="filters">
      <template #header>{{ t('settlements.filter') }}</template>
      <el-form :inline="true" :model="filter">
        <el-form-item :label="t('settlements.ledger')">
          <el-radio-group v-model="ledger">
            <el-radio-button label="group">{{ t('settlements.ledgerGroup') }}</el-radio-button>
            <el-radio-button label="dispatcher">{{ t('settlements.ledgerDispatcher') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="ledger === 'dispatcher'" :label="t('settlements.dispatcher')">
          <el-select v-model="dispatcherId" style="width: 180px" :placeholder="t('settlements.selectDispatcher')">
            <el-option v-for="d in dispatchers" :key="d.id" :value="d.id"
              :label="d.display_name || d.username" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('settlements.currency')">
          <el-select v-model="filter.currency" clearable style="width: 120px">
            <el-option label="INR" value="INR" /><el-option label="USD" value="USD" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('settlements.amount')"><el-input v-model="filter.amount" placeholder="100.00" style="width: 130px" /></el-form-item>
        <el-form-item :label="t('settlements.filterProduct')"><el-input v-model="filter.product" style="width: 140px" /></el-form-item>
        <el-form-item :label="t('settlements.filterFrom')">
          <el-date-picker v-model="filter.start_date" type="date" value-format="YYYY-MM-DD" style="width: 150px" />
        </el-form-item>
        <el-form-item :label="t('settlements.filterTo')">
          <el-date-picker v-model="filter.end_date" type="date" value-format="YYYY-MM-DD" style="width: 150px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="onPreview" :loading="previewing">{{ t('settlements.preview') }}</el-button>
          <el-button type="success" @click="onCreate" :loading="creating">{{ t('settlements.create') }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="preview" class="preview">
      <template #header>{{ t('settlements.preview') }}</template>
      <el-row :gutter="12" class="counts">
        <el-col :span="4"><el-statistic :title="t('settlements.eligible')" :value="preview.eligible_order_count" /></el-col>
        <el-col :span="4"><el-statistic :title="t('settlements.reserved')" :value="preview.reserved_count" /></el-col>
        <el-col :span="4"><el-statistic :title="t('settlements.alreadySettled')" :value="preview.already_settled_count" /></el-col>
        <el-col :span="4"><el-statistic :title="t('settlements.excluded')" :value="preview.excluded_count" /></el-col>
        <el-col :span="4"><el-statistic :title="t('settlements.ineligible')" :value="preview.ineligible_orders.length" /></el-col>
      </el-row>
      <el-divider>{{ t('settlements.paymentCounts') }}</el-divider>
      <el-alert
        type="warning"
        :closable="false"
        :title="t('settlements.countsHint')"
        style="margin-bottom: 10px"
      />
      <el-table :data="preview.payment_counts" :empty-text="t('orders.noData')">
        <el-table-column :label="t('settlements.currency')" prop="currency" />
        <el-table-column :label="t('settlements.amount')" prop="amount" />
        <el-table-column :label="t('settlements.quantity')" prop="quantity" />
      </el-table>
    </el-card>

    <el-card class="list">
      <template #header>{{ t('menu.settlements') }}</template>
      <el-table :data="settlements" v-loading="loading">
        <el-table-column :label="t('settlements.batchId')" prop="settlement_id" width="160" />
        <el-table-column :label="t('settlements.ledger')" width="130">
          <template #default="{ row }">
            <el-tag :type="row.settlement_type === 'dispatcher' ? 'warning' : 'info'">
              {{ row.settlement_type === 'dispatcher' ? t('settlements.ledgerDispatcher') : t('settlements.ledgerGroup') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('settlements.dispatcher')" width="140">
          <template #default="{ row }">
            {{ row.dispatcher_user_id ? dispatcherName(row.dispatcher_user_id) : '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="t('settlements.statusDraft')">
          <template #default="{ row }"><el-tag :type="settlementStatusTag(row.status)">{{ t(settlementStatusKey(row.status)) }}</el-tag></template>
        </el-table-column>
        <el-table-column :label="t('settlements.orderCount')" prop="order_count" width="100" />
        <el-table-column :label="t('settlements.createdAt')" :formatter="(r:any)=>fmt(r.created_at)" />
        <el-table-column :label="t('settlements.confirmedAt')" :formatter="(r:any)=>fmt(r.confirmed_at)" />
        <el-table-column :label="t('common.actions')" width="260" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'draft'" text type="success" @click="onConfirm(row)">{{ t('settlements.confirm') }}</el-button>
            <el-button v-if="row.status === 'draft'" text type="danger" @click="onCancel(row)">{{ t('settlements.cancel') }}</el-button>
            <el-button text type="primary" @click="onExport(row)">{{ t('settlements.export') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  previewSettlement, listSettlements, createSettlement, confirmSettlement,
  cancelSettlement, exportSettlement,
} from '@/api/settlements'
import { listDispatchers } from '@/api/dispatchers'
import { settlementStatusTag, formatDateTime } from '@/utils/format'
import { settlementStatusKey } from '@/utils/labels'
import type { SettlementPreview, SettlementOut, SettlementFilter, User } from '@/types'

const { t } = useI18n()
const fmt = formatDateTime

const filter = ref<SettlementFilter>({ currency: null, amount: null, product: null, start_date: null, end_date: null })
const ledger = ref<'group' | 'dispatcher'>('group')
const dispatcherId = ref<number | null>(null)
const dispatchers = ref<User[]>([])
const previewing = ref(false)
const creating = ref(false)
const preview = ref<SettlementPreview | null>(null)
const settlements = ref<SettlementOut[]>([])
const loading = ref(false)

function dispatcherName(id: number): string {
  const d = dispatchers.value.find((x) => x.id === id)
  return d ? (d.display_name || d.username) : `#${id}`
}

function cleanFilter(): SettlementFilter {
  const f: SettlementFilter = {}
  if (ledger.value === 'dispatcher') {
    if (dispatcherId.value) f.dispatcher_user_id = dispatcherId.value
    f.settlement_type = 'dispatcher'
  } else {
    f.settlement_type = 'group'
  }
  if (filter.value.currency) f.currency = filter.value.currency
  if (filter.value.amount) f.amount = filter.value.amount
  if (filter.value.product) f.product = filter.value.product
  if (filter.value.start_date) f.start_date = filter.value.start_date
  if (filter.value.end_date) f.end_date = filter.value.end_date
  return f
}

async function onPreview() {
  if (ledger.value === 'dispatcher' && !dispatcherId.value) {
    ElMessage.warning(t('settlements.selectDispatcher'))
    return
  }
  previewing.value = true
  try {
    preview.value = await previewSettlement(cleanFilter())
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    previewing.value = false
  }
}

async function onCreate() {
  if (ledger.value === 'dispatcher' && !dispatcherId.value) {
    ElMessage.warning(t('settlements.selectDispatcher'))
    return
  }
  creating.value = true
  try {
    await createSettlement(cleanFilter())
    ElMessage.success(t('settlements.created'))
    preview.value = null
    load()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    creating.value = false
  }
}

async function onConfirm(row: SettlementOut) {
  await ElMessageBox.confirm(t('settlements.confirm') + '?', t('common.confirm'), { type: 'warning' })
  await confirmSettlement(row.settlement_id)
  ElMessage.success(t('settlements.confirmedMsg'))
  load()
}

async function onCancel(row: SettlementOut) {
  await ElMessageBox.confirm(t('settlements.cancel') + '?', t('common.confirm'), { type: 'warning' })
  await cancelSettlement(row.settlement_id)
  ElMessage.success(t('settlements.cancelledMsg'))
  load()
}

async function onExport(row: SettlementOut) {
  try {
    const blob = await exportSettlement(row.settlement_id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${row.settlement_id}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e?.message || 'export failed')
  }
}

async function load() {
  loading.value = true
  try {
    const [rows, ds] = await Promise.all([listSettlements(), listDispatchers()])
    settlements.value = rows
    dispatchers.value = ds
  } catch (e: any) {
    ElMessage.error(e?.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.filters, .preview, .list {
  margin-bottom: 14px;
}
.counts {
  margin-bottom: 4px;
}
</style>
