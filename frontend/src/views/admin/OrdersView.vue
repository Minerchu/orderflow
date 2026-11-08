<template>
  <div class="orders-page">
    <div class="of-page-head">
      <div class="of-page-head__title">{{ t('orders.title') }}</div>
      <div class="of-page-head__desc">{{ t('orders.quickSendHint') }}</div>
    </div>

    <section class="of-send-hero">
      <div>
        <div class="of-send-hero__title">{{ t('orders.quickSendTitle') }}</div>
        <div class="of-send-hero__desc">{{ t('orders.quickSendHint') }}</div>
      </div>
      <el-button class="of-send-hero__button" type="primary" size="large" @click="onCreate">
        {{ t('orders.createAndSend') }}
      </el-button>
    </section>

    <div class="toolbar">
      <el-select v-model="filterStatus" clearable :placeholder="t('orders.filterStatus')" class="filter-control">
        <el-option v-for="s in orderStatuses" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="filterCurrency" clearable :placeholder="t('orders.filterCurrency')" class="filter-control filter-control--currency">
        <el-option v-for="c in currencies" :key="c" :label="c" :value="c" />
      </el-select>
      <el-select v-model="filterOwner" clearable :placeholder="t('orders.filterDispatcher')" class="filter-control">
        <el-option v-for="d in dispatchers" :key="d.id" :value="d.id" :label="d.display_name || d.username" />
      </el-select>
      <el-button @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-table :data="orders" v-loading="loading" :empty-text="t('orders.noData')">
      <el-table-column :label="t('orders.orderNumber')" prop="order_number" width="140" />
      <el-table-column :label="t('orders.createdAt')" min-width="150">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('orders.product')" prop="product_name_snapshot" />
      <el-table-column :label="t('orders.amount')" width="140">
        <template #default="{ row }">{{ formatAmount(row.amount, row.currency) }}</template>
      </el-table-column>
      <el-table-column :label="t('orders.status')" width="130">
        <template #default="{ row }"><el-tag :type="orderStatusTag(row.order_status)">{{ t(orderStatusKey(row.order_status)) }}</el-tag></template>
      </el-table-column>
      <el-table-column :label="t('orders.financialStatus')" width="130">
        <template #default="{ row }"><el-tag :type="financialStatusTag(row.financial_status)">{{ t(financialStatusKey(row.financial_status)) }}</el-tag></template>
      </el-table-column>
      <el-table-column :label="t('orders.owner')" prop="order_owner_id" width="90" />
      <el-table-column :label="t('orders.dispatcher')" width="140">
        <template #default="{ row }">{{ dispatcherName(row.order_owner_id) }}</template>
      </el-table-column>
      <el-table-column :label="t('orders.tgStatus')" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.telegram_send_status === 'sent'" type="success">{{ t('orders.tgSent') }}</el-tag>
          <el-tag v-else-if="row.telegram_send_status === 'failed'" type="danger">{{ t('orders.tgFailed') }}</el-tag>
          <el-tag v-else type="info">{{ t('orders.tgPending') }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="120" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="openDetail(row)">{{ t('orders.detail') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create and send: one screen, ordered by how often each field is used.
         A stepper was tried first and white-screened on phones, so the flow is
         back to a single scroll with the footer pinned. -->
    <el-dialog
      v-model="createVisible"
      :title="t('orders.createAndSend')"
      width="min(600px, calc(100vw - 32px))"
      class="of-create-dialog"
      :show-close="!saving"
      :close-on-press-escape="!saving"
      :close-on-click-modal="false"
    >
      <el-alert type="info" :closable="false" :title="t('orders.onlyFilledHint')" class="of-create-hint" />

      <!-- 商品：常用置顶的 chip 网格，比下拉少两次点击 -->
      <div class="of-field">
        <span class="of-field__label">{{ t('orders.product') }}</span>
        <div class="of-chips">
          <span
            v-for="p in visibleProducts"
            :key="p.id"
            class="of-chip"
            :class="{ 'of-chip--on': form.product_id === p.id }"
            @click="form.product_id = form.product_id === p.id ? null : p.id"
          >{{ p.name }}</span>
          <span class="of-chip of-chip--more" @click="showAllProducts = !showAllProducts">
            {{ showAllProducts ? '\u2191' : t('orders.moreProducts') }}
          </span>
        </div>
        <div class="of-field__hint">
          {{ showAllProducts ? t('orders.allProducts') : t('orders.recentProducts') }}
        </div>
      </div>

      <!-- 金额 + 币种：一眼确认数字，币种一键切 -->
      <div class="of-field">
        <span class="of-field__label">{{ t('orders.amount') }}<span class="of-required">*</span></span>
        <div class="of-amount">
          <span class="of-amount__sign">{{ form.currency === 'USD' ? '$' : '\u20b9' }}</span>
          <div class="of-amount__input">
            <el-input v-model.trim="form.amount" inputmode="decimal" placeholder="0" />
          </div>
        </div>
        <div class="of-seg">
          <span
            v-for="c in currencies"
            :key="c"
            class="of-seg__item"
            :class="{ 'of-seg__item--on': form.currency === c }"
            @click="form.currency = c"
          >{{ c }}</span>
        </div>
      </div>

      <!-- 账号信息：粘贴按钮免去长按选择 -->
      <div class="of-field">
        <span class="of-field__label">{{ t('orders.accountInfo') }}</span>
        <el-input
          v-model="form.account_info"
          type="textarea"
          :rows="4"
          :placeholder="t('orders.accountInfoPlaceholder')"
        />
        <div class="of-pastebar">
          <el-button :disabled="saving" @click="pasteAccount">{{ t('orders.paste') }}</el-button>
          <el-button :disabled="saving" @click="form.account_info = ''">{{ t('orders.clear') }}</el-button>
        </div>
        <div class="of-field__hint">{{ t('orders.accountInfoHint') }}</div>
      </div>

      <!-- 登录方式：三个大档位，记住上次选择 -->
      <div class="of-field">
        <span class="of-field__label">{{ t('orders.loginMethod') }}</span>
        <div class="of-seg">
          <span
            class="of-seg__item"
            :class="{ 'of-seg__item--on': form.login_method === 'password' }"
            @click="form.login_method = 'password'"
          >{{ t('orders.passwordLogin') }}</span>
          <span
            class="of-seg__item"
            :class="{ 'of-seg__item--on': form.login_method === 'code_send' }"
            @click="form.login_method = 'code_send'"
          >{{ t('orders.codeSend') }}</span>
          <span
            class="of-seg__item"
            :class="{ 'of-seg__item--on': form.login_method === 'account_only' }"
            @click="form.login_method = 'account_only'"
          >{{ t('orders.accountOnly') }}</span>
          <span
            class="of-seg__item"
            :class="{ 'of-seg__item--on': form.login_method === 'qr_scan' }"
            @click="form.login_method = 'qr_scan'"
          >{{ t('orders.qrScan') }}</span>
        </div>
      </div>

      <!-- 图片：自绘网格，比 picture-card 少一次点击 -->
      <div class="of-field">
        <span class="of-field__label">{{ t('orders.imagesOptional') }}</span>
        <div class="of-img-grid">
          <div v-for="(f, i) in pendingFiles" :key="i" class="of-img-cell">
            <img :src="f.url" alt="" />
            <span class="of-img-cell__del" @click="removePendingFile(i)">×</span>
          </div>
          <div
            v-if="pendingFiles.length < 6"
            class="of-img-cell of-img-cell--add"
            @click="pickFiles"
          >+</div>
        </div>
        <div class="of-img-paste">
          <el-button size="small" :disabled="saving || pendingFiles.length >= 6" @click="pasteImages">
            {{ t('orders.pasteImages') }}
          </el-button>
          <span class="of-field__hint">{{ t('orders.pasteImagesHint') }}</span>
        </div>
        <div class="of-field__hint">{{ t('orders.imageNameHint') }}</div>
      </div>

      <div class="of-field">
        <span class="of-field__label">{{ t('orders.noteOptional') }}</span>
        <el-input v-model.trim="form.note" type="textarea" :rows="2" />
      </div>

      <!-- 目标群：默认走设置里的群，不用每次填 chat_id -->
      <div class="of-field">
        <span class="of-field__label">{{ t('orders.targetChat') }}</span>
        <div class="of-seg">
          <span
            class="of-seg__item"
            :class="{ 'of-seg__item--on': !form.chat_id }"
            @click="form.chat_id = ''"
          >{{ t('orders.chatDefault') }}</span>
          <span
            class="of-seg__item"
            :class="{ 'of-seg__item--on': !!form.chat_id }"
            @click="form.chat_id = form.chat_id || defaultChatId || ''"
          >{{ t('orders.changeChat') }}</span>
        </div>
        <el-input
          v-if="form.chat_id"
          v-model.trim="form.chat_id"
          inputmode="numeric"
          :placeholder="t('orders.defaultChatPlaceholder')"
          style="margin-top: 10px"
        />
        <div class="of-field__hint">{{ t('orders.chatDefaultHint') }}</div>
      </div>

      <template #footer>
        <div class="of-create-footer">
          <el-button :disabled="saving" @click="createVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button :disabled="saving" @click="submitCreate(false)">{{ t('orders.saveDraft') }}</el-button>
          <el-button type="primary" :loading="saving" @click="submitCreate(true)">
            {{ t('orders.createAndSend') }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <button class="of-fab" type="button" @click="onCreate">
      <span>+</span>
      <span>{{ t('orders.createAndSend') }}</span>
    </button>

    <!-- Native picker behind the custom image grid: one tap on phones, where
         Element Plus' picture-card list needs two and scrolls. -->
    <input
      ref="fileInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      multiple
      hidden
      @change="onFilesPicked"
    />

    <!-- Detail drawer -->
    <el-drawer v-model="detailVisible" :title="detail?.order_number" size="min(560px, 100vw)">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item :label="t('orders.createdAt')">{{ formatDateTime(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.completed_at" :label="t('orders.completedAt')">{{ formatDateTime(detail.completed_at) }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.status')">
            <el-tag :type="orderStatusTag(detail.order_status)">{{ t(orderStatusKey(detail.order_status)) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('orders.financialStatus')">
            <el-tag :type="financialStatusTag(detail.financial_status)">{{ t(financialStatusKey(detail.financial_status)) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('orders.amount')">{{ formatAmount(detail.amount, detail.currency) }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.owner')">{{ detail.order_owner_id ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.acceptedBy')">{{ detail.accepted_by_username ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.completedBy')">{{ detail.completed_by_username ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.createdBy')">{{ detail.created_by_username ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('orders.amountConfirmed')">
            <el-tag :type="detail.amount_confirmed ? 'success' : 'info'">
              {{ detail.amount_confirmed ? t('orders.amountConfirmedYes') : t('orders.amountConfirmedAuto') }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('orders.tgStatus')">{{ t(telegramStatusKey(detail.telegram_send_status)) }}</el-descriptions-item>
        </el-descriptions>

        <div class="detail-actions">
          <el-input v-model="chatId" :placeholder="'chat_id (' + t('common.all') + ')'" style="width: 200px" />
          <el-tooltip :content="t('orders.syncHint')" placement="top">
            <el-button @click="onSend(false)" :loading="acting">{{ t('orders.send') }}</el-button>
          </el-tooltip>
          <el-tooltip :content="t('orders.retryHint')" placement="top">
            <el-button @click="onSend(true)" :loading="acting">{{ t('orders.retry') }}</el-button>
          </el-tooltip>
          <el-button @click="onToggleExclude" :loading="acting">
            {{ detail.financial_status === 'excluded' ? t('orders.include') : t('orders.exclude') }}
          </el-button>
        </div>
        <div class="action-help">{{ t('orders.actionHelp') }}</div>

        <!-- Edit an order that is already out in the group. -->
        <div class="edit-block">
          <div class="edit-block__head">
            <span class="edit-block__label">{{ t('orders.editOrder') }}</span>
            <el-button
              text
              type="primary"
              size="small"
              @click="toggleEdit"
            >
              {{ editOpen ? t('common.cancel') : t('common.edit') }}
            </el-button>
          </div>
          <template v-if="editOpen">
            <el-form :model="editForm" label-position="top" class="edit-form">
              <el-form-item :label="t('orders.product')">
                <el-select v-model="editForm.product_id" filterable clearable style="width: 100%">
                  <el-option v-for="p in activeProducts" :key="p.id" :label="p.name" :value="p.id" />
                </el-select>
              </el-form-item>
              <el-form-item :label="t('orders.productNameManual')">
                <el-input v-model.trim="editForm.product_name_snapshot" />
              </el-form-item>
              <el-form-item :label="t('orders.amount')">
                <el-input v-model.trim="editForm.amount" inputmode="decimal" />
              </el-form-item>
              <el-form-item :label="t('orders.currency')">
                <el-select v-model="editForm.currency" style="width: 100%">
                  <el-option v-for="c in currencies" :key="c" :label="c" :value="c" />
                </el-select>
              </el-form-item>
              <el-form-item :label="t('orders.accountInfo')">
                <el-input v-model="editForm.account_info" type="textarea" :rows="3" />
              </el-form-item>
              <el-form-item :label="t('orders.loginMethod')">
                <el-select v-model="editForm.login_method" clearable style="width: 100%">
                  <el-option :label="t('orders.emailPassword')" value="password" />
                  <el-option :label="t('orders.codeSend')" value="code_send" />
                  <el-option :label="t('orders.accountOnly')" value="account_only" />
                  <el-option :label="t('orders.qrScan')" value="qr_scan" />
                </el-select>
              </el-form-item>
              <el-form-item :label="t('orders.password')">
                <el-input v-model="editForm.password" type="password" show-password
                          :placeholder="t('orders.passwordKeepHint')" />
              </el-form-item>
              <el-form-item :label="t('orders.note')">
                <el-input v-model="editForm.note" type="textarea" :rows="2" />
              </el-form-item>
            </el-form>
            <div class="edit-form__actions">
              <el-button @click="toggleEdit">{{ t('common.cancel') }}</el-button>
              <el-button type="primary" :loading="acting" @click="onSaveEdit(false)">
                {{ t('orders.saveOnly') }}
              </el-button>
              <el-button type="success" :loading="acting" @click="onSaveEdit(true)">
                {{ t('orders.saveAndSync') }}
              </el-button>
            </div>
            <div class="action-help">{{ t('orders.editSyncHint') }}</div>
          </template>
        </div>

        <!-- Admin status override: a failed order must not be a dead end. -->
        <div class="status-override">
          <div class="status-override__label">{{ t('orders.adminChangeStatus') }}</div>
          <div class="status-override__row">
            <el-select v-model="statusTarget" style="flex: 1">
              <el-option
                v-for="s in ADMIN_STATUS_OPTIONS"
                :key="s.value"
                :label="t(s.label)"
                :value="s.value"
              />
            </el-select>
            <el-select
              v-if="statusTarget === 'failed'"
              v-model="failureReason"
              style="flex: 1"
              :placeholder="t('orders.failureReason')"
            >
              <el-option
                v-for="r in FAILURE_REASON_OPTIONS"
                :key="r.value"
                :label="t(r.label)"
                :value="r.value"
              />
            </el-select>
            <el-button type="warning" :loading="acting" @click="onChangeStatus">
              {{ t('orders.applyStatus') }}
            </el-button>
          </div>
        </div>

        <el-tabs v-model="tab">
          <el-tab-pane :label="t('orders.events')" name="events">
            <el-timeline>
              <el-timeline-item
                v-for="e in events"
                :key="e.id"
                :timestamp="formatDateTime(e.created_at)"
                placement="top"
              >
                <strong>{{ t(eventTypeKey(e.event_type)) }}</strong>
                <span v-if="e.from_status || e.to_status"> ({{ e.from_status ? t(orderStatusKey(e.from_status)) : '-' }} → {{ e.to_status ? t(orderStatusKey(e.to_status)) : '-' }})</span>
                <div v-if="e.note" class="ev-note">{{ e.note }}</div>
                <div v-if="e.telegram_username" class="ev-note">@{{ e.telegram_username }}</div>
              </el-timeline-item>
              <el-timeline-item v-if="!events.length" :timestamp="t('orders.noData')" />
            </el-timeline>
          </el-tab-pane>

          <el-tab-pane :label="t('orders.attachments')" name="attachments">
            <el-upload
              :auto-upload="false"
              :show-file-list="false"
              accept="image/*"
              :on-change="onUpload"
            >
              <el-button type="primary">{{ t('orders.upload') }}</el-button>
            </el-upload>
            <el-table :data="attachments" style="margin-top: 12px">
              <el-table-column :label="t('orders.file')" prop="original_filename" />
              <el-table-column :label="t('orders.size')" width="100">
                <template #default="{ row }">{{ (row.file_size / 1024).toFixed(1) }} KB</template>
              </el-table-column>
              <el-table-column :label="t('common.actions')" width="160">
                <template #default="{ row }">
                  <el-button text type="primary" @click="onDownload(row)">{{ t('orders.download') }}</el-button>
                  <el-button text type="danger" @click="onDeleteAtt(row)">{{ t('orders.deleteAtt') }}</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>

        <!-- One-tap repeat: pre-fill the create flow from this order. -->
        <div class="of-reuse">
          <div class="of-reuse__label">{{ t('orders.reuseOrder') }}</div>
          <div class="of-reuse__desc">{{ t('orders.reuseOrderDesc') }}</div>
          <el-button type="primary" @click="onReuseOrder">{{ t('orders.reuseOrder') }}</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type UploadUserFile } from 'element-plus'
import {
  listOrders, createOrder, sendOrder, retrySend, updateOrder, orderEvents,
  listAttachments, uploadAttachment, deleteAttachment, attachmentSignedUrl,
} from '@/api/orders'
import { getSettings } from '@/api/admin'
import { listProducts } from '@/api/products'
import { listDispatchers } from '@/api/dispatchers'
import {
  orderStatusTag, financialStatusTag, formatAmount, formatDateTime,
  ORDER_STATUSES, FINANCIAL_STATUSES,
} from '@/utils/format'
import { describeSendError } from '@/utils/errors'
import {
  orderStatusKey, financialStatusKey, telegramStatusKey, eventTypeKey,
} from '@/utils/labels'
import type { Order, AttachmentOut, OrderEventOut, Product, User } from '@/types'

const { t } = useI18n()

const orders = ref<Order[]>([])
const dispatchers = ref<User[]>([])

function dispatcherName(id?: number | null): string {
  if (!id) return '-'
  const d = dispatchers.value.find((x) => x.id === id)
  return d ? (d.display_name || d.username) : `#${id}`
}
const loading = ref(false)
const filterStatus = ref<string>('')
const filterCurrency = ref<string>('')
const filterOwner = ref<number | null>(null)
const currencies = ['INR', 'USD']
const orderStatuses = ORDER_STATUSES
const defaultChatId = ref('')
const products = ref<Product[]>([])

/** Only active types are offered when creating an order. */
const activeProducts = computed(() => products.value.filter((p) => p.is_active))

const createVisible = ref(false)
const saving = ref(false)
const pendingFiles = ref<{ raw: File; url: string }[]>([])

/** Expand the product chip list beyond the frequently-used ones. */
const showAllProducts = ref(false)

// ---------------------------------------------------------------------------
// 表单记忆：币种 / 登录方式 / 常用商品记在 localStorage。
// 发第二单时这三样已经填好，基本只剩金额和账号要输入。
// ---------------------------------------------------------------------------
const PREF_KEY = 'orderflow.create.prefs.v1'
interface CreatePrefs {
  currency: string
  login_method: string
  chat_id: string
  recent: number[]
}

const DEFAULT_PREFS: CreatePrefs = {
  currency: 'INR',
  login_method: 'password',
  chat_id: '',
  recent: [],
}

function loadPrefs(): CreatePrefs {
  try {
    const raw = localStorage.getItem(PREF_KEY)
    if (!raw) return { ...DEFAULT_PREFS }
    return { ...DEFAULT_PREFS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

const prefs = ref<CreatePrefs>(loadPrefs())

function savePrefs() {
  try {
    localStorage.setItem(
      PREF_KEY,
      JSON.stringify({
        currency: form.value.currency,
        login_method: form.value.login_method,
        chat_id: form.value.chat_id,
        recent: recentIds.value,
      }),
    )
  } catch {
    /* private mode / quota — remembering is a convenience, never a requirement */
  }
}

/** Product ids, most recently used first. */
const recentIds = ref<number[]>(prefs.value.recent)

// ---------------------------------------------------------------------------
// 草稿自动保存：手机切到别的 app 再回来，页面常被浏览器回收重载，
// 不落盘的话填了一半的账号信息就全丢了。这里每次改动都写 localStorage，
// 重新打开发单弹窗时自动恢复；超过 24 小时的旧草稿直接丢弃。
// ---------------------------------------------------------------------------
const DRAFT_KEY = 'orderflow.create.draft.v1'
const DRAFT_TTL_MS = 24 * 60 * 60 * 1000

function saveDraft() {
  try {
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ saved_at: Date.now(), form: form.value }),
    )
  } catch {
    /* private mode / quota — the form still works, it just is not recoverable */
  }
}

function clearDraft() {
  try {
    localStorage.removeItem(DRAFT_KEY)
  } catch {
    /* ignore */
  }
}

function loadDraft(): { form: Partial<ReturnType<typeof emptyForm>> } | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.saved_at || Date.now() - parsed.saved_at > DRAFT_TTL_MS) {
      localStorage.removeItem(DRAFT_KEY)
      return null
    }
    return parsed.form ? { form: parsed.form } : null
  } catch {
    return null
  }
}

/** Frequently-used products float to the top of the chip grid. */
const sortedProducts = computed(() => {
  const active = activeProducts.value
  const head = recentIds.value
    .map((id) => active.find((p) => p.id === id))
    .filter((p): p is Product => Boolean(p))
  const seen = new Set(head.map((p) => p.id))
  return [...head, ...active.filter((p) => !seen.has(p.id))]
})

const visibleProducts = computed(() =>
  showAllProducts.value ? sortedProducts.value : sortedProducts.value.slice(0, 8),
)

function emptyForm() {
  return {
    product_id: null as number | null,
    amount: '',
    currency: prefs.value.currency || 'INR',
    account_info: '',
    login_method: prefs.value.login_method || 'password',
    note: '',
    chat_id: prefs.value.chat_id || '',
  }
}

const form = ref(emptyForm())

// Deep watch: every keystroke and chip tap refreshes the saved draft, so a
// page reload (mobile browsers evict backgrounded tabs) loses nothing.
watch(form, saveDraft, { deep: true })

const detailVisible = ref(false)
const detail = ref<Order | null>(null)
const events = ref<OrderEventOut[]>([])
const attachments = ref<AttachmentOut[]>([])
const chatId = ref('')
const acting = ref(false)
const tab = ref('events')
const statusTarget = ref('')
const failureReason = ref('')

/** Inline edit form for an order that has already been sent to the group. */
const editOpen = ref(false)
function emptyEditForm() {
  return {
    product_id: null as number | null,
    product_name_snapshot: '',
    amount: '',
    currency: 'INR',
    account_info: '',
    login_method: '' as string | null,
    password: '',
    note: '',
  }
}
const editForm = ref(emptyEditForm())

function toggleEdit() {
  if (!detail.value) return
  if (editOpen.value) {
    editOpen.value = false
    return
  }
  // Seed from the current order so the admin edits rather than re-types.
  editForm.value = {
    product_id: detail.value.product_id ?? null,
    product_name_snapshot: detail.value.product_name_snapshot ?? '',
    amount: detail.value.amount != null ? String(detail.value.amount) : '',
    currency: detail.value.currency || 'INR',
    account_info: detail.value.account_info ?? '',
    login_method: detail.value.login_method ?? '',
    password: '',
    note: detail.value.note ?? '',
  }
  editOpen.value = true
}

/** Save the inline edit. ``sync`` controls whether the group message is
 *  rewritten right away; the backend also auto-syncs, but this lets the admin
 *  explicitly force it and see the result. */
async function onSaveEdit(sync: boolean) {
  if (!detail.value) return
  const amountText = String(editForm.value.amount ?? '').trim()
  if (!amountText) {
    ElMessage.warning(t('orders.amountRequired'))
    return
  }
  if (!(Number(amountText) > 0)) {
    ElMessage.warning(t('orders.amountInvalid'))
    return
  }
  acting.value = true
  try {
    const f = editForm.value
    const payload: any = {
      product_id: f.product_id,
      product_name_snapshot: f.product_name_snapshot || null,
      amount: f.amount === '' ? null : String(f.amount),
      currency: f.currency,
      account_info: f.account_info,
      login_method: f.login_method || null,
      note: f.note,
    }
    // Only send the password when the admin typed a new one, so an empty box
    // never wipes the stored credential.
    if (f.password) payload.password = f.password

    detail.value = await updateOrder(detail.value.id, payload)
    if (sync) {
      await sendOrder(detail.value.id, chatId.value || undefined)
    }
    ElMessage.success(t('orders.editSaved'))
    editOpen.value = false
    await loadEvents(detail.value.id)
    await loadAttachments(detail.value.id)
    await load()
  } catch (e: any) {
    ElMessage.error(describeSendError(e))
  } finally {
    acting.value = false
  }
}

/** Statuses an admin may force from the detail drawer. `draft` is excluded:
 *  a draft has never been delivered, so "revert" to it is meaningless. */
const ADMIN_STATUS_OPTIONS = [
  { value: 'pending', label: 'statusPending' },
  { value: 'processing', label: 'statusProcessing' },
  { value: 'completed', label: 'statusCompleted' },
  { value: 'failed', label: 'statusFailed' },
  { value: 'closed', label: 'statusClosed' },
]

const FAILURE_REASON_OPTIONS = [
  { value: 'account_not_eligible', label: 'reasonAccount' },
  { value: 'invalid_account', label: 'reasonInvalid' },
  { value: 'recharge_failed', label: 'reasonRecharge' },
  { value: 'other', label: 'reasonOther' },
]

async function load() {
  loading.value = true
  try {
    if (!dispatchers.value.length) dispatchers.value = await listDispatchers()
    orders.value = await listOrders({
      order_status: filterStatus.value || undefined,
      currency: filterCurrency.value || undefined,
      owner_id: filterOwner.value || undefined,
      page: 1,
      page_size: 100,
    })
  } catch (e: any) {
    ElMessage.error(e?.message || 'load failed')
  } finally {
    loading.value = false
  }
}

function onCreate() {
  if (saving.value || createVisible.value) return
  // Pick up whatever was half-typed last time: mobile browsers evict the page
  // when the user switches apps, so an unsaved form would otherwise vanish.
  const draft = loadDraft()
  form.value = draft ? { ...emptyForm(), ...draft.form } : emptyForm()
  pendingFiles.value = []
  showAllProducts.value = false
  createVisible.value = true
}

/** One-tap repeat from the detail drawer: same product/amount/credentials. */
function onReuseOrder() {
  if (!detail.value) return
  form.value = {
    product_id: detail.value.product_id ?? null,
    amount: detail.value.amount != null ? String(detail.value.amount) : '',
    currency: detail.value.currency || prefs.value.currency || 'INR',
    account_info: detail.value.account_info ?? '',
    login_method: detail.value.login_method || prefs.value.login_method || 'password',
    note: detail.value.note ?? '',
    chat_id: detail.value.telegram_chat_id ?? prefs.value.chat_id ?? '',
  }
  pendingFiles.value = []
  showAllProducts.value = false
  detailVisible.value = false
  createVisible.value = true
}

function onCreateFileExceed(_files: File[], _uploadFiles: UploadUserFile[]) {
  ElMessage.warning(t('orders.imageLimitHint'))
}

/** Read the clipboard into the account box — no long-press gymnastics. */
async function pasteAccount() {
  try {
    const text = await navigator.clipboard.readText()
    if (!text || !text.trim()) {
      ElMessage.warning(t('orders.pasteEmpty'))
      return
    }
    form.value.account_info = text.trim()
    ElMessage.success(t('orders.pasteOk'))
  } catch {
    // Denied permission or insecure context: the textarea still works.
    ElMessage.warning(t('orders.pasteEmpty'))
  }
}

// Keep the clipboard path aligned with the backend allow-list; otherwise a
// GIF copied from a chat would look fine in the preview and fail on upload.
const PASTABLE_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

const fileInput = ref<HTMLInputElement | null>(null)

function pickFiles() {
  fileInput.value?.click()
}

function addPendingImages(files: File[]) {
  const room = 6 - pendingFiles.value.length
  if (files.length > room) ElMessage.warning(t('orders.imageLimitHint'))
  for (const file of files.slice(0, Math.max(room, 0))) {
    pendingFiles.value.push({ raw: file, url: URL.createObjectURL(file) })
  }
}

function onFilesPicked(event: Event) {
  const input = event.target as HTMLInputElement
  addPendingImages(Array.from(input.files || []))
  input.value = '' // allow picking the same file again
}

function imageFilesFromClipboard(data: DataTransfer | null): File[] {
  const out: File[] = []
  for (const item of Array.from(data?.items || [])) {
    if (item.kind !== 'file' || !PASTABLE_IMAGE_TYPES.has(item.type)) continue
    const file = item.getAsFile()
    if (file) out.push(file)
  }
  return out
}

/** Ctrl+V anywhere in the create form: a screenshot becomes a pending upload. */
function onPaste(event: ClipboardEvent) {
  if (!createVisible.value || saving.value) return
  const files = imageFilesFromClipboard(event.clipboardData)
  if (!files.length) return
  event.preventDefault()
  addPendingImages(files)
}

/** Button fallback for browsers that only expose the async Clipboard API. */
async function pasteImages() {
  if (saving.value) return
  if (pendingFiles.value.length >= 6) {
    ElMessage.warning(t('orders.imageLimitHint'))
    return
  }
  try {
    if (!navigator.clipboard?.read) {
      ElMessage.warning(t('orders.pasteImageDenied'))
      return
    }
    const items = await navigator.clipboard.read()
    const files: File[] = []
    for (const item of items) {
      const type = item.types.find((t) => PASTABLE_IMAGE_TYPES.has(t))
      if (!type) continue
      const blob = await item.getType(type)
      const ext = type.split('/')[1] || 'png'
      files.push(new File([blob], `pasted-${Date.now()}-${files.length}.${ext}`, { type }))
    }
    if (!files.length) {
      ElMessage.warning(t('orders.pasteImageEmpty'))
      return
    }
    addPendingImages(files)
  } catch {
    ElMessage.warning(t('orders.pasteImageDenied'))
  }
}

function removePendingFile(index: number) {
  const [removed] = pendingFiles.value.splice(index, 1)
  if (removed) URL.revokeObjectURL(removed.url)
}

async function submitCreate(shouldSend: boolean) {
  if (saving.value) return
  const amountText = String(form.value.amount ?? '').trim()
  if (!amountText) {
    ElMessage.warning(t('orders.amountRequired'))
    return
  }
  if (!(Number(amountText) > 0)) {
    ElMessage.warning(t('orders.amountInvalid'))
    return
  }
  let createdOrder: Order | null = null
  saving.value = true
  try {
    const { chat_id, ...rawPayload } = form.value
    const payload: any = Object.fromEntries(
      Object.entries(rawPayload).filter(([, value]) => value !== '' && value !== null && value !== undefined),
    )
    if (payload.amount) payload.amount = String(payload.amount)

    const order = await createOrder(payload)
    createdOrder = order
    for (const item of pendingFiles.value) {
      if (item.raw) await uploadAttachment(order.id, item.raw)
    }

    if (shouldSend) {
      await sendOrder(order.id, chat_id || undefined)
      ElMessage.success(t('orders.createdAndSent'))
    } else {
      ElMessage.success(t('orders.created'))
    }

    // Remember what was just used so the next order starts pre-filled.
    if (form.value.product_id != null) {
      recentIds.value = [
        form.value.product_id,
        ...recentIds.value.filter((id) => id !== form.value.product_id),
      ].slice(0, 12)
    }
    savePrefs()
    clearDraft()   // submitted — do not resurrect it next time
    for (const f of pendingFiles.value) URL.revokeObjectURL(f.url)

    createVisible.value = false
    pendingFiles.value = []
    await load()
  } catch (e: any) {
    // Surface the real cause (wrong chat id / not admin / network...) rather
    // than a generic failure code.
    ElMessage.error(describeSendError(e))
    if (createdOrder) {
      createVisible.value = false
      chatId.value = form.value.chat_id
      form.value = emptyForm()
      pendingFiles.value = []
      ElMessage.warning(t('orders.createdRecoveryHint'))
      await load()
      try {
        await openDetail(orders.value.find(row => row.id === createdOrder!.id) || createdOrder)
        tab.value = 'attachments'
      } catch {
        ElMessage.warning(t('orders.detailReloadHint'))
      }
    }
  } finally {
    saving.value = false
  }
}

async function openDetail(row: Order) {
  detail.value = row
  detailVisible.value = true
  tab.value = 'events'
  await Promise.all([loadEvents(row.id), loadAttachments(row.id)])
}

async function loadEvents(id: number) {
  events.value = await orderEvents(id)
}
async function loadAttachments(id: number) {
  attachments.value = await listAttachments(id)
}

async function onSend(retry: boolean) {
  if (!detail.value) return
  acting.value = true
  try {
    if (retry) detail.value = await retrySend(detail.value.id, chatId.value || undefined)
    else detail.value = await sendOrder(detail.value.id, chatId.value || undefined)
    ElMessage.success(t('common.success'))
    await loadEvents(detail.value.id)
    load()
  } catch (e: any) {
    ElMessage.error(describeSendError(e))
  } finally {
    acting.value = false
  }
}

/** Admin override: force an order into another state (e.g. un-stick a
 *  failed order that was marked by mistake). */
async function onChangeStatus() {
  if (!detail.value || !statusTarget.value) return
  const target = statusTarget.value
  const label = t(ADMIN_STATUS_OPTIONS.find((o) => o.value === target)?.label || '')
  try {
    await ElMessageBox.confirm(
      t('orders.confirmChangeStatus', { from: detail.value.order_status, to: label }),
      t('common.confirm'),
      { type: 'warning' },
    )
  } catch {
    return // cancelled
  }

  acting.value = true
  try {
    detail.value = await updateOrder(detail.value.id, {
      order_status: target,
      failure_reason: target === 'failed' ? (failureReason.value || 'other') : undefined,
    })
    ElMessage.success(t('orders.statusChanged'))
    statusTarget.value = ''
    failureReason.value = ''
    await loadEvents(detail.value.id)
    await loadAttachments(detail.value.id)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.error'))
  } finally {
    acting.value = false
  }
}

async function onToggleExclude() {
  if (!detail.value) return
  const next = detail.value.financial_status === 'excluded' ? 'unsettled' : 'excluded'
  acting.value = true
  try {
    detail.value = await updateOrder(detail.value.id, { financial_status: next })
    await loadEvents(detail.value.id)
    load()
  } catch (e: any) {
    ElMessage.error(e?.message)
  } finally {
    acting.value = false
  }
}

async function onUpload(file: any) {
  if (!detail.value) return
  try {
    await uploadAttachment(detail.value.id, file.raw)
    ElMessage.success(t('common.success'))
    await loadAttachments(detail.value.id)
  } catch (e: any) {
    ElMessage.error(e?.message || 'upload failed')
  }
}

async function onDownload(row: AttachmentOut) {
  try {
    const url = await attachmentSignedUrl(row.id)
    window.open(url, '_blank')
  } catch (e: any) {
    ElMessage.error(e?.message || 'download failed')
  }
}

async function onDeleteAtt(row: AttachmentOut) {
  await ElMessageBox.confirm(t('common.delete') + '?', t('common.confirm'), { type: 'warning' })
  await deleteAttachment(row.id)
  ElMessage.success(t('common.success'))
  await loadAttachments(detail.value!.id)
}

onMounted(async () => {
  document.addEventListener('paste', onPaste)
  await load()
  // Product types power the 商品 chip grid; the form still works without them.
  try {
    products.value = await listProducts()
  } catch {
    products.value = []
  }
  try {
    const settings = await getSettings()
    defaultChatId.value = settings.default_chat_id || ''
  } catch {
    defaultChatId.value = ''
  }
})

onUnmounted(() => {
  document.removeEventListener('paste', onPaste)
  for (const f of pendingFiles.value) URL.revokeObjectURL(f.url)
})
</script>

<style scoped>
.orders-page { min-width: 0; }
.of-required { color: #a32d2d; margin-left: 2px; }

.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.filter-control { width: 180px; }
.filter-control--currency { width: 140px; }
@media (max-width: 640px) {
  .toolbar { gap: 8px; }
  .filter-control, .filter-control--currency { flex: 1; min-width: 120px; }
}

/* 详情抽屉操作区 */
.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 14px 0;
}
.detail-actions .el-button { min-height: 40px; }
.action-help {
  margin: 6px 0 2px;
  color: #888780;
  font-size: 12px;
  line-height: 1.5;
}

/* 已发到群的订单可就地编辑 */
.edit-block {
  margin-top: 14px;
  padding: 12px;
  border: 0.5px solid #e4e1d8;
  border-radius: 12px;
  background-color: #faf8f4;
}
.edit-block__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.edit-block__label {
  font-size: 13px;
  font-weight: 500;
  color: #2c2c2a;
}
.edit-form { margin-top: 10px; }
.edit-form :deep(.el-form-item) { margin-bottom: 12px; }
.edit-form__actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

/* 管理员强制改状态 */
.status-override {
  margin-top: 14px;
  padding: 12px;
  border: 0.5px dashed #d3d1c7;
  border-radius: 12px;
  background-color: #faf8f4;
}
.status-override__label {
  font-size: 13px;
  font-weight: 500;
  color: #2c2c2a;
  margin-bottom: 8px;
}
.status-override__row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.ev-note {
  color: #888780;
  font-size: 12px;
}
</style>
