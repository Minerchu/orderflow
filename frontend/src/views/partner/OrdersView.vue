<template>
  <div class="worker-page">
    <div class="page-head">
      <div>
        <h2>{{ t('partners.workerPanel') }}</h2>
        <div class="page-note">{{ t('partners.groupScopeHint') }}</div>
      </div>
      <div class="page-actions">
        <el-select v-model="chatId" clearable :placeholder="t('partners.chooseGroup')" @change="onGroupChange">
          <el-option v-for="group in groups" :key="group.chat_id" :value="group.chat_id"
            :label="`${group.chat_id} · ${group.order_count} ${t('partners.orderCountUnit')}`" />
        </el-select>
        <el-button @click="load">{{ t('common.refresh') }}</el-button>
      </div>
    </div>

    <el-card class="section-card">
      <template #header>
        <div class="section-head">
          <div class="section-title">
            <span>{{ t('partners.unsettledOrders') }}</span>
            <el-tag type="warning">{{ t('orders.financialStatus') }}: {{ t('orders.financialUnsettled') }}</el-tag>
          </div>
          <div class="section-actions">
            <el-button type="primary" @click="calculateUnsettled" :loading="calculating">
              {{ t('partners.calculateUnsettled') }}
            </el-button>
            <el-button @click="countDialogVisible = true; loadPaymentCounts()">
              {{ t('partners.completedAmountCheck') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="unsettledCount !== null" type="info" :closable="false" class="count-result">
        <template #title>
          <strong>{{ t('partners.unsettledTotal', { count: unsettledCount }) }}</strong>
        </template>
        <div v-if="unsettledBreakdown.length" class="breakdown">
          <span v-for="row in unsettledBreakdown" :key="`${row.currency}:${row.amount}`">
            {{ formatAmount(row.amount, row.currency) }} × {{ row.quantity }}
          </span>
        </div>
      </el-alert>

      <el-table :data="unsettledOrders" v-loading="loading" :empty-text="t('orders.noData')" class="orders-table">
        <el-table-column :label="t('orders.orderNumber')" prop="order_number" min-width="150" />
        <el-table-column :label="t('orders.createdAt')" min-width="155">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('partners.group')" prop="telegram_chat_id" min-width="130" />
        <el-table-column :label="t('orders.product')" prop="product_name_snapshot" min-width="130" />
        <el-table-column :label="t('orders.amount')" min-width="130">
          <template #default="{ row }">{{ formatAmount(row.amount, row.currency) }}</template>
        </el-table-column>
        <el-table-column :label="t('orders.status')" width="125">
          <template #default="{ row }"><el-tag :type="orderStatusTag(row.order_status)">{{ t(orderStatusKey(row.order_status)) }}</el-tag></template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="100" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openOrderDetail(row)">{{ t('orders.detail') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="section-card">
      <template #header>
        <div class="section-head">
          <div class="section-title">
            <span>{{ t('partners.settledBatches') }}</span>
            <el-tag type="success">{{ t('orders.financialStatus') }}: {{ t('orders.financialSettled') }}</el-tag>
          </div>
          <span class="section-subtitle">{{ t('partners.settledBatchHint') }}</span>
        </div>
      </template>
      <el-table :data="settlements" v-loading="loading" :empty-text="t('orders.noData')">
        <el-table-column :label="t('settlements.batchId')" prop="settlement_id" min-width="175" />
        <el-table-column :label="t('partners.settlementTime')" min-width="175">
          <template #default="{ row }">{{ formatDateTime(row.settled_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('partners.ordersInBatch')" prop="order_count" width="130" />
        <el-table-column :label="t('common.actions')" width="120" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openSettlement(row)">{{ t('partners.viewDetails') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="countDialogVisible" :title="t('partners.completedAmountCheck')" width="min(720px, calc(100vw - 28px))">
      <el-alert type="info" :closable="false" :title="t('partners.countCheckHint')" class="count-hint" />
      <el-alert v-if="!chatId" type="warning" :closable="false" :title="t('partners.countCheckChooseGroup')" class="count-hint" />
      <el-table :data="payCounts" v-loading="countsLoading" :empty-text="t('orders.noData')" size="small">
        <el-table-column :label="t('settlements.currency')" prop="currency" width="105" />
        <el-table-column :label="t('settlements.amount')" min-width="135">
          <template #default="{ row }">{{ formatAmount(row.amount, row.currency) }}</template>
        </el-table-column>
        <el-table-column :label="t('settlements.quantity')" prop="quantity" width="95" />
        <el-table-column :label="t('partners.countCheck')" min-width="170">
          <template #default="{ row }">
            <el-button size="small" :type="row.checked ? 'success' : 'primary'"
              :disabled="!chatId || row.checked || row.amount == null"
              :loading="checkingKey === `${row.currency}:${row.amount}`" @click="verifyCount(row)">
              {{ row.checked ? t('partners.countChecked') : t('partners.checkNow') }}
            </el-button>
            <span v-if="row.checked_at" class="checked-time">{{ formatDateTime(row.checked_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="countDialogVisible = false">{{ t('common.back') }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="settlementDrawerVisible" :title="settlementDetail?.settlement_id" size="min(760px, 94vw)">
      <template v-if="settlementDetail">
        <el-descriptions :column="1" border size="small" class="batch-description">
          <el-descriptions-item :label="t('partners.settlementTime')">{{ formatDateTime(settlementDetail.settled_at) }}</el-descriptions-item>
          <el-descriptions-item :label="t('partners.ordersInBatch')">{{ settlementDetail.order_count }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="settlementDetail.orders" v-loading="batchLoading" :empty-text="t('orders.noData')">
          <el-table-column :label="t('orders.orderNumber')" prop="order_number" min-width="140" />
          <el-table-column :label="t('orders.product')" prop="product_name_snapshot" min-width="130" />
          <el-table-column :label="t('orders.amount')" min-width="125">
            <template #default="{ row }">{{ formatAmount(row.amount, row.currency) }}</template>
          </el-table-column>
          <el-table-column :label="t('orders.createdAt')" min-width="155">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column :label="t('orders.completedAt')" min-width="155">
            <template #default="{ row }">{{ formatDateTime(row.completed_at) }}</template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>

    <el-drawer v-model="detailVisible" :title="detail?.order_number" size="min(560px, 94vw)">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item :label="t('orders.createdAt')">{{ formatDateTime(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.completed_at" :label="t('orders.completedAt')">{{ formatDateTime(detail.completed_at) }}</el-descriptions-item>
          <el-descriptions-item :label="t('partners.group')">{{ detail.telegram_chat_id || '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.status')"><el-tag :type="orderStatusTag(detail.order_status)">{{ t(orderStatusKey(detail.order_status)) }}</el-tag></el-descriptions-item>
          <el-descriptions-item :label="t('orders.financialStatus')"><el-tag :type="financialStatusTag(detail.financial_status)">{{ t(financialStatusKey(detail.financial_status)) }}</el-tag></el-descriptions-item>
          <el-descriptions-item :label="t('orders.product')">{{ detail.product_name_snapshot || '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.amount')">{{ formatAmount(detail.amount, detail.currency) }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.completedBy')">{{ detail.completed_by_username || '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-timeline class="events-timeline">
          <el-timeline-item v-for="event in events" :key="event.id" :timestamp="formatDateTime(event.created_at)" placement="top">
            <strong>{{ t(eventTypeKey(event.event_type)) }}</strong>
            <span v-if="event.from_status || event.to_status"> ({{ event.from_status ? t(orderStatusKey(event.from_status)) : '-' }} → {{ event.to_status ? t(orderStatusKey(event.to_status)) : '-' }})</span>
            <div v-if="event.note" class="event-note">{{ event.note }}</div>
          </el-timeline-item>
        </el-timeline>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  checkPartnerPaymentCount, workerGroups, partnerOrders, partnerPaymentCounts,
  partnerSettledDetails, partnerSettledHistory,
  type PartnerCountRow, type PartnerGroup, type PartnerSettlementDetails, type PartnerSettlementRow,
} from '@/api/partners'
import { orderEvents } from '@/api/orders'
import { financialStatusTag, formatAmount, formatDateTime, orderStatusTag } from '@/utils/format'
import { orderStatusKey, financialStatusKey, eventTypeKey } from '@/utils/labels'
import type { Order, OrderEventOut } from '@/types'

const { t } = useI18n()
const groups = ref<PartnerGroup[]>([])
const chatId = ref('')
const unsettledOrders = ref<Order[]>([])
const settlements = ref<PartnerSettlementRow[]>([])
const payCounts = ref<PartnerCountRow[]>([])
const unsettledCount = ref<number | null>(null)
const unsettledBreakdown = ref<{ currency: string; amount: string | null; quantity: number }[]>([])
const loading = ref(false)
const calculating = ref(false)
const countsLoading = ref(false)
const checkingKey = ref('')
const countDialogVisible = ref(false)
const settlementDrawerVisible = ref(false)
const batchLoading = ref(false)
const settlementDetail = ref<PartnerSettlementDetails | null>(null)
const detailVisible = ref(false)
const detail = ref<Order | null>(null)
const events = ref<OrderEventOut[]>([])

async function load() {
  loading.value = true
  try {
    if (!groups.value.length) groups.value = await workerGroups()
    const selectedGroup = chatId.value || undefined
    const [orderRows, batchRows] = await Promise.all([
      partnerOrders({ chat_id: selectedGroup, financial_status: 'unsettled' }),
      partnerSettledHistory(selectedGroup),
    ])
    unsettledOrders.value = orderRows
    settlements.value = batchRows
  } catch (e: any) {
    ElMessage.error(e?.message || 'load failed')
  } finally {
    loading.value = false
  }
}

async function onGroupChange() {
  unsettledCount.value = null
  unsettledBreakdown.value = []
  await load()
}

async function calculateUnsettled() {
  calculating.value = true
  try {
    unsettledOrders.value = await partnerOrders({ chat_id: chatId.value || undefined, financial_status: 'unsettled' })
    unsettledCount.value = unsettledOrders.value.length
    const counts = new Map<string, { currency: string; amount: string | null; quantity: number }>()
    for (const order of unsettledOrders.value) {
      const amount = order.amount ?? null
      const key = `${order.currency}:${amount ?? 'unknown'}`
      const row = counts.get(key) || { currency: order.currency, amount, quantity: 0 }
      row.quantity += 1
      counts.set(key, row)
    }
    unsettledBreakdown.value = [...counts.values()].sort((a, b) => a.currency.localeCompare(b.currency) || String(a.amount).localeCompare(String(b.amount)))
  } catch (e: any) {
    ElMessage.error(e?.message || 'calculation failed')
  } finally {
    calculating.value = false
  }
}

async function loadPaymentCounts() {
  countsLoading.value = true
  try {
    payCounts.value = await partnerPaymentCounts(chatId.value || undefined)
  } catch (e: any) {
    ElMessage.error(e?.message || 'load failed')
  } finally {
    countsLoading.value = false
  }
}

async function verifyCount(row: PartnerCountRow) {
  if (!chatId.value || row.amount == null) return
  const key = `${row.currency}:${row.amount}`
  checkingKey.value = key
  try {
    await checkPartnerPaymentCount(chatId.value, row.currency, String(row.amount))
    ElMessage.success(t('partners.countChecked'))
    await loadPaymentCounts()
  } catch (e: any) {
    ElMessage.error(e?.message || 'check failed')
  } finally {
    checkingKey.value = ''
  }
}

async function openSettlement(row: PartnerSettlementRow) {
  settlementDrawerVisible.value = true
  batchLoading.value = true
  settlementDetail.value = null
  try {
    settlementDetail.value = await partnerSettledDetails(row.id, chatId.value || undefined)
  } catch (e: any) {
    ElMessage.error(e?.message || 'load settlement details failed')
    settlementDrawerVisible.value = false
  } finally {
    batchLoading.value = false
  }
}

async function openOrderDetail(row: Order) {
  detail.value = row
  detailVisible.value = true
  try {
    events.value = await orderEvents(row.id)
  } catch (e: any) {
    ElMessage.error(e?.message || 'load detail failed')
  }
}

onMounted(load)
</script>

<style scoped>
.worker-page { display: grid; gap: 16px; }
.page-head, .page-actions, .section-head, .section-title, .section-actions { display: flex; align-items: center; gap: 12px; }
.page-head, .section-head { justify-content: space-between; }
.page-head h2 { margin: 0; font-size: 22px; }
.page-note, .section-subtitle { color: #909399; font-size: 13px; margin-top: 5px; }
.page-actions { min-width: 300px; }
.page-actions .el-select { width: 260px; }
.section-title { font-weight: 600; }
.section-title > span { font-size: 17px; }
.count-result { margin-bottom: 12px; }
.breakdown { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 4px; }
.count-hint { margin-bottom: 10px; }
.checked-time { display: block; color: #909399; font-size: 12px; margin-top: 4px; }
.batch-description { margin-bottom: 14px; }
.events-timeline { margin-top: 18px; }
.event-note { color: #909399; font-size: 12px; }
@media (max-width: 760px) {
  .page-head, .section-head { align-items: stretch; flex-direction: column; }
  .page-actions, .section-actions { align-items: stretch; flex-direction: column; min-width: 0; }
  .page-actions .el-select { width: 100%; }
}
</style>
