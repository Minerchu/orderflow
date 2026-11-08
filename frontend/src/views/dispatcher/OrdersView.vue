<template>
  <div class="orders-page">
    <div class="of-page-head">
      <div class="of-page-head__title">{{ t('dispatcherPage.title') }}</div>
      <div class="of-page-head__desc">{{ t('dispatcherPage.subtitle') }}</div>
    </div>

    <section class="of-send-hero">
      <div>
        <div class="of-send-hero__title">{{ t('dispatcherPage.sendTitle') }}</div>
        <div class="of-send-hero__desc">{{ t('dispatcherPage.sendHint') }}</div>
      </div>
      <el-button class="of-send-hero__button" type="primary" size="large" @click="openCreate">
        {{ t('dispatcherPage.create') }}
      </el-button>
    </section>

    <div class="toolbar">
      <el-select v-model="filterStatus" clearable :placeholder="t('orders.filterStatus')" class="filter">
        <el-option v-for="s in ORDER_STATUSES" :key="s" :value="s" :label="t(orderStatusKey(s))" />
      </el-select>
      <el-button @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-table :data="orders" v-loading="loading" :empty-text="t('orders.noData')">
      <el-table-column :label="t('orders.orderNumber')" prop="order_number" width="140" />
      <el-table-column :label="t('orders.createdAt')" min-width="150">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('orders.product')" prop="product_name_snapshot" min-width="130" />
      <el-table-column :label="t('orders.amount')" width="130">
        <template #default="{ row }">{{ formatAmount(row.amount, row.currency) }}</template>
      </el-table-column>
      <el-table-column :label="t('orders.status')" width="120">
        <template #default="{ row }">
          <el-tag :type="orderStatusTag(row.order_status)">{{ t(orderStatusKey(row.order_status)) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('dispatcherPage.mySettlement')" width="130">
        <template #default="{ row }">
          <el-tag :type="financialStatusTag(row.dispatcher_settlement_status)">
            {{ t(financialStatusKey(row.dispatcher_settlement_status)) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('orders.tgStatus')" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.telegram_send_status === 'sent'" type="success">{{ t('orders.tgSent') }}</el-tag>
          <el-tag v-else-if="row.telegram_send_status === 'failed'" type="danger">{{ t('orders.tgFailed') }}</el-tag>
          <el-tag v-else type="info">{{ t('orders.tgPending') }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="100" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="openDetail(row)">{{ t('orders.detail') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="createVisible"
      :title="t('dispatcherPage.create')"
      width="min(600px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      :show-close="!saving"
    >
      <el-alert type="info" :closable="false" :title="t('orders.onlyFilledHint')" class="of-create-hint" />

      <div class="of-field">
        <span class="of-field__label">{{ t('orders.product') }}</span>
        <div class="of-chips">
          <span
            v-for="p in products"
            :key="p.id"
            class="of-chip"
            :class="{ 'of-chip--on': form.product_id === p.id }"
            @click="form.product_id = form.product_id === p.id ? null : p.id"
          >{{ p.name }}</span>
          <span v-if="!products.length" class="of-field__hint">{{ t('dispatcherPage.noProducts') }}</span>
        </div>
      </div>

      <div class="of-field">
        <span class="of-field__label">{{ t('orders.amount') }}<span class="of-required">*</span></span>
        <div class="of-amount">
          <span class="of-amount__sign">{{ form.currency === 'USD' ? '$' : '\u20b9' }}</span>
          <div class="of-amount__input">
            <el-input v-model.trim="form.amount" inputmode="decimal" placeholder="0" />
          </div>
        </div>
        <div class="of-seg">
          <span v-for="c in currencies" :key="c" class="of-seg__item"
            :class="{ 'of-seg__item--on': form.currency === c }" @click="form.currency = c">{{ c }}</span>
        </div>
      </div>

      <div class="of-field">
        <span class="of-field__label">{{ t('orders.accountInfo') }}</span>
        <el-input v-model="form.account_info" type="textarea" :rows="4"
          :placeholder="t('orders.accountInfoPlaceholder')" />
        <div class="of-pastebar">
          <el-button :disabled="saving" @click="pasteAccount">{{ t('orders.paste') }}</el-button>
          <el-button :disabled="saving" @click="form.account_info = ''">{{ t('orders.clear') }}</el-button>
        </div>
        <div class="of-field__hint">{{ t('orders.accountInfoHint') }}</div>
      </div>

      <div class="of-field">
        <span class="of-field__label">{{ t('orders.loginMethod') }}</span>
        <div class="of-seg">
          <span v-for="m in loginMethods" :key="m.value" class="of-seg__item"
            :class="{ 'of-seg__item--on': form.login_method === m.value }"
            @click="form.login_method = m.value">{{ t(m.label) }}</span>
        </div>
      </div>

      <div class="of-field">
        <span class="of-field__label">{{ t('orders.imagesOptional') }}</span>
        <div class="of-img-grid">
          <div v-for="(f, i) in pendingFiles" :key="i" class="of-img-cell">
            <img :src="f.url" alt="" />
            <span class="of-img-cell__del" @click="removePendingFile(i)">&times;</span>
          </div>
          <div v-if="pendingFiles.length < 6" class="of-img-cell of-img-cell--add" @click="pickFiles">+</div>
        </div>
        <div class="of-img-paste">
          <el-button size="small" :disabled="saving || pendingFiles.length >= 6" @click="pasteImages">
            {{ t('orders.pasteImages') }}
          </el-button>
          <span class="of-field__hint">{{ t('orders.pasteImagesHint') }}</span>
        </div>
      </div>

      <div class="of-field">
        <span class="of-field__label">{{ t('orders.noteOptional') }}</span>
        <el-input v-model="form.note" type="textarea" :rows="2" :placeholder="t('orders.notePlaceholder')" />
      </div>

      <template #footer>
        <div class="of-create-footer">
          <el-button :disabled="saving" @click="createVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button :disabled="saving" @click="submit(false)">{{ t('orders.saveDraft') }}</el-button>
          <el-button type="primary" :loading="saving" @click="submit(true)">
            {{ t('dispatcherPage.createAndSend') }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp" multiple hidden @change="onFilesPicked" />

    <el-drawer v-model="detailVisible" :title="detail?.order_number" size="min(520px, 100vw)">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item :label="t('orders.createdAt')">{{ formatDateTime(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.product')">{{ detail.product_name_snapshot || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.amount')">{{ formatAmount(detail.amount, detail.currency) }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.status')">
            <el-tag :type="orderStatusTag(detail.order_status)">{{ t(orderStatusKey(detail.order_status)) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('dispatcherPage.mySettlement')">
            <el-tag :type="financialStatusTag(detail.dispatcher_settlement_status)">
              {{ t(financialStatusKey(detail.dispatcher_settlement_status)) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.failure_reason" :label="t('orders.failureReason')">
            {{ t(failureReasonKey(detail.failure_reason)) }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.account_info" :label="t('orders.accountInfo')">
            <pre class="pre">{{ detail.account_info }}</pre>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.note" :label="t('orders.note')">{{ detail.note }}</el-descriptions-item>
        </el-descriptions>

        <el-divider>{{ t('orders.events') }}</el-divider>
        <el-timeline>
          <el-timeline-item v-for="e in events" :key="e.id" :timestamp="formatDateTime(e.created_at)" placement="top">
            <strong>{{ t(eventTypeKey(e.event_type)) }}</strong>
            <span v-if="e.from_status || e.to_status">
              ({{ e.from_status ? t(orderStatusKey(e.from_status)) : '-' }} &rarr; {{ e.to_status ? t(orderStatusKey(e.to_status)) : '-' }})
            </span>
          </el-timeline-item>
        </el-timeline>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { createOrder, uploadAttachment, sendOrder, orderEvents } from '@/api/orders'
import { dispatcherOrders, dispatcherProducts } from '@/api/dispatchers'
import { describeSendError } from '@/utils/errors'
import {
  formatAmount, formatDateTime, orderStatusTag, financialStatusTag, ORDER_STATUSES,
} from '@/utils/format'
import { orderStatusKey, financialStatusKey, eventTypeKey, failureReasonKey } from '@/utils/labels'
import type { Order, OrderEventOut, Product } from '@/types'

const { t } = useI18n()
const currencies = ['INR', 'USD']
const loginMethods = [
  { value: 'password', label: 'orders.passwordLogin' },
  { value: 'code_send', label: 'orders.codeSend' },
  { value: 'account_only', label: 'orders.accountOnly' },
  { value: 'qr_scan', label: 'orders.qrScan' },
]

const orders = ref<Order[]>([])
const products = ref<Product[]>([])
const loading = ref(false)
const filterStatus = ref('')
const createVisible = ref(false)
const saving = ref(false)
const pendingFiles = ref<{ raw: File; url: string }[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const detailVisible = ref(false)
const detail = ref<Order | null>(null)
const events = ref<OrderEventOut[]>([])

function emptyForm() {
  return {
    product_id: null as number | null,
    amount: '',
    currency: 'INR',
    account_info: '',
    login_method: 'password',
    note: '',
  }
}
const form = ref(emptyForm())

async function load() {
  loading.value = true
  try {
    const [rows, allowed] = await Promise.all([
      dispatcherOrders({ order_status: filterStatus.value || undefined }),
      dispatcherProducts(),
    ])
    orders.value = rows
    products.value = allowed.filter((p) => p.is_active)
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

watch(filterStatus, load)

function openCreate() {
  form.value = emptyForm()
  pendingFiles.value = []
  createVisible.value = true
}

async function submit(andSend: boolean) {
  const amountText = String(form.value.amount ?? '').trim()
  if (!amountText) {
    ElMessage.warning(t('orders.amountRequired'))
    return
  }
  if (!(Number(amountText) > 0)) {
    ElMessage.warning(t('orders.amountInvalid'))
    return
  }
  if (!form.value.product_id) {
    ElMessage.warning(t('dispatcherPage.productRequired'))
    return
  }
  saving.value = true
  let created: Order | null = null
  try {
    created = await createOrder({
      product_id: form.value.product_id,
      amount: form.value.amount || null,
      currency: form.value.currency,
      account_info: form.value.account_info || null,
      login_method: form.value.login_method || null,
      note: form.value.note || null,
    })

    const failedUploads: string[] = []
    for (const f of pendingFiles.value) {
      try {
        await uploadAttachment(created.id, f.raw)
      } catch {
        failedUploads.push(f.raw.name)
      }
    }

    if (andSend) {
      await sendOrder(created.id)
      ElMessage.success(t('dispatcherPage.sent'))
    } else {
      ElMessage.success(t('orders.created'))
    }
    if (failedUploads.length) {
      ElMessage.warning(t('dispatcherPage.uploadFailed', { names: failedUploads.join(', ') }))
    }
    createVisible.value = false
    await load()
  } catch (e: any) {
    if (created) {
      // The order exists even if sending failed: say so instead of implying
      // nothing happened, and refresh the list so it is visible as a draft.
      ElMessage.error(describeSendError(e))
      createVisible.value = false
      await load()
    } else {
      ElMessage.error(e?.message || t('common.error'))
    }
  } finally {
    saving.value = false
  }
}

async function openDetail(row: Order) {
  detail.value = row
  detailVisible.value = true
  try {
    events.value = await orderEvents(row.id)
  } catch {
    events.value = []
  }
}

// ---- account info clipboard ----
async function pasteAccount() {
  try {
    const text = await navigator.clipboard.readText()
    if (!text.trim()) {
      ElMessage.warning(t('orders.pasteEmpty'))
      return
    }
    form.value.account_info = text.trim()
  } catch {
    ElMessage.warning(t('orders.pasteEmpty'))
  }
}

// ---- images: picker + paste, same allow-list as the backend ----
const PASTABLE = new Set(['image/jpeg', 'image/png', 'image/webp'])

function pickFiles() {
  fileInput.value?.click()
}

function addFiles(files: File[]) {
  const room = 6 - pendingFiles.value.length
  if (files.length > room) ElMessage.warning(t('orders.imageLimitHint'))
  for (const f of files.slice(0, Math.max(room, 0))) {
    pendingFiles.value.push({ raw: f, url: URL.createObjectURL(f) })
  }
}

function onFilesPicked(ev: Event) {
  const input = ev.target as HTMLInputElement
  addFiles(Array.from(input.files || []))
  input.value = ''
}

function removePendingFile(i: number) {
  const f = pendingFiles.value[i]
  if (f) URL.revokeObjectURL(f.url)
  pendingFiles.value.splice(i, 1)
}

async function pasteImages() {
  try {
    const items = await navigator.clipboard.read()
    const files: File[] = []
    for (const item of items) {
      for (const type of item.types) {
        if (!PASTABLE.has(type)) continue
        const blob = await item.getType(type)
        files.push(new File([blob], `pasted-${Date.now()}.${type.split('/')[1]}`, { type }))
      }
    }
    if (!files.length) {
      ElMessage.warning(t('orders.pasteImageEmpty'))
      return
    }
    addFiles(files)
  } catch {
    ElMessage.warning(t('orders.pasteImageEmpty'))
  }
}

function onPaste(ev: ClipboardEvent) {
  if (!createVisible.value) return
  const files: File[] = []
  for (const item of Array.from(ev.clipboardData?.items || [])) {
    if (item.kind !== 'file' || !PASTABLE.has(item.type)) continue
    const f = item.getAsFile()
    if (f) files.push(f)
  }
  if (files.length) {
    ev.preventDefault()
    addFiles(files)
  }
}

onMounted(() => {
  load()
  window.addEventListener('paste', onPaste)
})
onBeforeUnmount(() => window.removeEventListener('paste', onPaste))
</script>

<style scoped>
.of-required { color: #a32d2d; margin-left: 2px; }
.toolbar { display: flex; gap: 10px; margin-bottom: 12px; }
.filter { width: 200px; }
.of-create-footer { display: flex; gap: 10px; justify-content: flex-end; }
.pre { white-space: pre-wrap; margin: 0; font-family: inherit; }
</style>
