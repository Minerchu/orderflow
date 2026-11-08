<template>
  <div>
    <!-- Partner dashboard -->
    <template v-if="auth.isPartner()">
      <el-row :gutter="16">
        <el-col :span="4" v-for="c in partnerCards" :key="c.label">
          <el-card shadow="hover" class="stat">{{ c.value }}<div class="stat-label">{{ c.label }}</div></el-card>
        </el-col>
      </el-row>
      <el-card class="block">
        <template #header>{{ t('dashboard.paymentCounts') }}</template>
        <el-table :data="payCounts" :empty-text="t('orders.noData')">
          <el-table-column :label="t('settlements.currency')" prop="currency" />
          <el-table-column :label="t('settlements.amount')" prop="amount" />
          <el-table-column :label="t('settlements.quantity')" prop="quantity" />
        </el-table>
      </el-card>
    </template>

    <!-- Admin dashboard -->
    <template v-else>
      <el-row :gutter="16">
        <el-col :span="6" v-for="c in adminCards" :key="c.label">
          <el-card shadow="hover" class="stat pointer" @click="go(c.to)">
            {{ c.value }}<div class="stat-label">{{ c.label }}</div>
          </el-card>
        </el-col>
      </el-row>
      <el-card class="block">
        <template #header>{{ t('menu.settlements') }}</template>
        <el-table :data="recentSettlements" :empty-text="t('orders.noData')">
          <el-table-column :label="t('settlements.batchId')" prop="settlement_id" />
          <el-table-column :label="t('settlements.statusDraft')">
          <template #default="{ row }">{{ t(settlementStatusKey(row.status)) }}</template>
        </el-table-column>
          <el-table-column :label="t('settlements.orderCount')" prop="order_count" />
          <el-table-column :label="t('settlements.createdAt')" :formatter="(r:any)=>fmt(r.created_at)" />
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { authStore } from '@/store/auth'
import { listProducts } from '@/api/products'
import { listPartners } from '@/api/partners'
import { listSettlements } from '@/api/settlements'
import { partnerDashboard, partnerPaymentCounts } from '@/api/partners'
import { formatDateTime } from '@/utils/format'
import { settlementStatusKey } from '@/utils/labels'
import type { SettlementOut } from '@/types'

const { t } = useI18n()
const router = useRouter()
const auth = authStore()
const fmt = formatDateTime

const productCount = ref(0)
const partnerCount = ref(0)
const recentSettlements = ref<SettlementOut[]>([])

const dash = ref<any>(null)
const payCounts = ref<any[]>([])

const partnerCards = computed(() => [
  { label: t('dashboard.completed'), value: dash.value?.completed_orders ?? 0 },
  { label: t('dashboard.unsettled'), value: dash.value?.unsettled ?? 0 },
  { label: t('dashboard.settled'), value: dash.value?.settled ?? 0 },
  { label: t('dashboard.failed'), value: dash.value?.failed ?? 0 },
  { label: t('dashboard.processing'), value: dash.value?.processing ?? 0 },
])

const adminCards = computed(() => [
  { label: t('menu.products'), value: productCount.value, to: '/admin/products' },
  { label: t('menu.partners'), value: partnerCount.value, to: '/admin/partners' },
  { label: t('menu.settlements'), value: recentSettlements.value.length, to: '/admin/settlements' },
  { label: t('menu.orders'), value: '—', to: '/admin/orders' },
])

function go(to: string) {
  router.push(to)
}

onMounted(async () => {
  try {
    if (auth.isPartner()) {
      dash.value = await partnerDashboard()
      payCounts.value = await partnerPaymentCounts()
    } else {
      productCount.value = (await listProducts()).length
      partnerCount.value = (await listPartners()).length
      recentSettlements.value = (await listSettlements()).slice(0, 8)
    }
  } catch (e) {
    // surfaced via global error handling
  }
})
</script>

<style scoped>
.stat {
  font-size: 30px;
  font-weight: 700;
  text-align: center;
  color: #2563eb;
}
.stat-label {
  font-size: 13px;
  color: #606266;
  margin-top: 6px;
  font-weight: 400;
}
.block {
  margin-top: 16px;
}
.pointer {
  cursor: pointer;
}
</style>
