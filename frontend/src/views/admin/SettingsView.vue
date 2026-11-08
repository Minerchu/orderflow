<template>
  <div v-loading="loading">
    <el-card class="block">
      <template #header>
        <div class="card-header">
          <span>{{ t('settings.telegramConfig') }}</span>
          <el-tag size="small" :type="s?.telegram_configured ? 'success' : 'danger'">
            {{ s?.telegram_configured ? t('settings.configured') : t('settings.notConfigured') }}
          </el-tag>
        </div>
      </template>

      <el-alert
        type="info"
        :closable="false"
        :title="t('settings.tokenHint')"
        class="notice"
      />

      <el-form ref="formRef" :model="form" :rules="rules" label-width="190px" label-position="left">
        <el-form-item :label="t('settings.botToken')" prop="bot_token">
          <el-input
            v-model.trim="form.bot_token"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="s?.telegram_configured ? t('settings.keepTokenPlaceholder') : t('settings.tokenPlaceholder')"
          />
        </el-form-item>
        <el-form-item :label="t('settings.defaultChatId')" prop="default_chat_id">
          <el-input v-model.trim="form.default_chat_id" placeholder="-1001234567890" />
        </el-form-item>
        <el-form-item :label="t('settings.allowedChatIds')" prop="allowed_chat_ids">
          <el-input v-model.trim="form.allowed_chat_ids" :placeholder="t('settings.idListPlaceholder')" />
          <div class="help">{{ t('settings.allowedChatHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('settings.adminTelegramIds')" prop="admin_telegram_user_ids">
          <el-input v-model.trim="form.admin_telegram_user_ids" :placeholder="t('settings.userIdListPlaceholder')" />
          <div class="help">{{ t('settings.adminTelegramHint') }}</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveTelegram">
            {{ t('settings.saveTelegram') }}
          </el-button>
          <el-button :loading="testing" @click="runTest(false)">
            {{ t('settings.testConnection') }}
          </el-button>
          <el-button :loading="testing" @click="runTest(true)">
            {{ t('settings.sendTestMessage') }}
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="testResult"
        :type="testResult.ok ? 'success' : 'error'"
        :closable="true"
        class="test-result"
      >
        <template #title>{{ testResult.ok ? t('settings.testPassed') : t('settings.testFailed') }}</template>
        <div class="test-lines">
          <div v-if="testResult.bot_username">{{ t('settings.botLabel') }}: @{{ testResult.bot_username }}</div>
          <div v-if="testResult.chat_title">{{ t('settings.group') }}: {{ testResult.chat_title }} ({{ t(chatTypeKey(testResult.chat_type)) }})</div>
          <div v-if="testResult.message_id">{{ t('settings.testMessageSent') }}</div>
          <div v-if="!testResult.proxy_configured" class="test-warn">{{ t('settings.proxyHint') }}</div>
          <div v-if="!testResult.ok" class="test-fix">{{ describeDiagCode(testResult.code) }}</div>
        </div>
      </el-alert>
    </el-card>

    <el-card class="block">
      <template #header>{{ t('settings.title') }}</template>
      <el-descriptions :column="2" border size="small" v-if="s">
        <el-descriptions-item :label="t('settings.defaultCurrency')">{{ s.default_currency }}</el-descriptions-item>
        <el-descriptions-item :label="t('settings.supportedCurrencies')">
          <el-tag v-for="c in s.supported_currencies" :key="c" size="small" class="tag">{{ c }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="t('settings.defaultLanguage')">{{ t(languageLabel(s.default_language)) }}</el-descriptions-item>
        <el-descriptions-item :label="t('settings.telegramLanguage')">{{ t(languageLabel(s.telegram_message_language)) }}</el-descriptions-item>
        <el-descriptions-item :label="t('settings.allowedChats')">{{ s.allowed_chat_count }}</el-descriptions-item>
        <el-descriptions-item :label="t('settings.backend')">{{ s.storage_backend }}</el-descriptions-item>
        <el-descriptions-item :label="t('settings.maxUpload')">{{ s.max_upload_size_mb }} MB</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- Webhook status: the #1 reason group buttons do nothing -->
    <el-card class="block">
      <template #header>
        <div class="card-header">
          <span>{{ t('settings.webhookTitle') }}</span>
          <el-tag size="small" :type="webhookOk ? 'success' : 'danger'">
            {{ webhookOk ? t('settings.webhookOk') : t('settings.webhookMissing') }}
          </el-tag>
        </div>
      </template>

      <el-alert type="info" :closable="false" :title="t('settings.webhookHint')" class="notice" />

      <el-alert
        v-if="webhook && webhook.config_ok === false"
        type="error"
        :closable="false"
        class="config-alert"
      >
        <template #title>{{ t('settings.baseUrlWrongTitle') }}</template>
        <div class="test-lines">
          <div>{{ t('settings.currentBaseUrl') }}: <code>{{ webhook.app_base_url || '(未设置)' }}</code></div>
          <div class="test-fix">{{ describeDiagCode(webhook.config_reason || '') }}</div>
        </div>
      </el-alert>

      <el-descriptions :column="1" border size="small" v-if="webhook && webhook.config_ok !== false">
        <el-descriptions-item :label="t('settings.expectedUrl')">{{ webhook.expected_url || '—' }}</el-descriptions-item>
        <el-descriptions-item :label="t('settings.currentUrl')">{{ webhook.current_url || t('settings.webhookMissing') }}</el-descriptions-item>
        <el-descriptions-item :label="t('settings.pendingUpdates')">{{ webhook.pending_update_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item v-if="webhook.last_error_message" :label="t('settings.telegramError')">
          {{ webhook.last_error_message }}
        </el-descriptions-item>
      </el-descriptions>

      <div class="webhook-actions">
        <el-button :loading="checkingWebhook" @click="loadWebhook">{{ t('settings.refreshStatus') }}</el-button>
        <el-button
          type="primary"
          :loading="registeringWebhook"
          :disabled="webhook?.config_ok === false"
          @click="registerWebhook"
        >
          {{ t('settings.registerWebhook') }}
        </el-button>
      </div>
      <div v-if="webhook && !webhook.ok && webhook.config_ok !== false" class="webhook-fix">
        {{ describeDiagCode(webhook.code) }}
      </div>

      <div v-if="webhook && webhook.config_ok === false" class="baseurl-form">
        <div class="upload-help">{{ t('settings.baseUrlHelp') }}</div>
        <div class="baseurl-row">
          <el-input
            v-model.trim="baseUrlInput"
            placeholder="https://order.example.com"
            :disabled="savingBaseUrl"
          />
          <el-button type="primary" :loading="savingBaseUrl" @click="saveBaseUrlAndRegister">
            {{ t('settings.saveAndRegister') }}
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card class="block">
      <template #header>{{ t('settings.groupTipsTitle') }}</template>
      <ul class="tips">
        <li>{{ t('settings.groupTips') }}</li>
        <li>{{ t('settings.groupTipsSelf') }}</li>
        <li>{{ t('settings.groupTipsAdmin') }}</li>
      </ul>
    </el-card>

    <el-card class="block" v-if="s">
      <template #header>{{ t('settings.displayFlags') }}</template>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item :label="t('settings.showOrderId')"><el-tag size="small" :type="s.show_order_id_in_group ? 'success' : 'info'">{{ s.show_order_id_in_group }}</el-tag></el-descriptions-item>
        <el-descriptions-item :label="t('settings.showCredentials')"><el-tag size="small" :type="s.show_credentials_in_group ? 'success' : 'info'">{{ s.show_credentials_in_group }}</el-tag></el-descriptions-item>
        <el-descriptions-item :label="t('settings.showPassword')"><el-tag size="small" :type="s.show_password_in_group ? 'success' : 'info'">{{ s.show_password_in_group }}</el-tag></el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card class="block" v-if="s">
      <template #header>{{ t('settings.groupPermissions') }}</template>
      <el-alert type="info" :closable="false" :title="t('settings.permissionHint')" class="notice" />
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item :label="t('settings.allowComplete')"><el-tag size="small" :type="s.allow_any_group_member_to_complete ? 'success' : 'info'">{{ s.allow_any_group_member_to_complete }}</el-tag></el-descriptions-item>
        <el-descriptions-item :label="t('settings.allowFail')"><el-tag size="small" :type="s.allow_any_group_member_to_fail ? 'success' : 'info'">{{ s.allow_any_group_member_to_fail }}</el-tag></el-descriptions-item>
        <el-descriptions-item :label="t('settings.allowReopen')"><el-tag size="small" :type="s.allow_any_group_member_to_reopen ? 'success' : 'info'">{{ s.allow_any_group_member_to_reopen }}</el-tag></el-descriptions-item>
        <el-descriptions-item :label="t('settings.allowClose')"><el-tag size="small" :type="s.allow_any_group_member_to_close ? 'success' : 'info'">{{ s.allow_any_group_member_to_close }}</el-tag></el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { getSettings, updateTelegramSettings, testTelegramConnection, getWebhookStatus, registerWebhook as registerWebhookApi, updatePublicBaseUrl } from '@/api/admin'
import { describeDiagCode, describeSendError } from '@/utils/errors'
import type { SystemSettings, TelegramSettingsPayload, TelegramTestResult, WebhookStatus } from '@/types'
import { chatTypeKey, languageLabel } from '@/utils/labels'

const { t } = useI18n()
const s = ref<SystemSettings | null>(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref<TelegramTestResult | null>(null)
const webhook = ref<(WebhookStatus & { ok: boolean }) | null>(null)
const checkingWebhook = ref(false)
const registeringWebhook = ref(false)
const baseUrlInput = ref('')
const savingBaseUrl = ref(false)

/** A webhook that is registered AND points at this deployment. */
const webhookOk = computed(
  () => !!(webhook.value?.ok && webhook.value.registered && webhook.value.matches_expected),
)
const formRef = ref<FormInstance>()
const form = reactive<TelegramSettingsPayload>({
  bot_token: '',
  default_chat_id: '',
  allowed_chat_ids: '',
  admin_telegram_user_ids: '',
})

const numericId = /^-?\d+$/
function validateIdList(_rule: unknown, value: string, callback: (error?: Error) => void) {
  const invalid = (value || '').split(',').map((item) => item.trim()).filter(Boolean).some((item) => !numericId.test(item))
  callback(invalid ? new Error(t('settings.invalidIdList')) : undefined)
}

const rules: FormRules<TelegramSettingsPayload> = {
  default_chat_id: [
    { required: true, message: () => t('settings.defaultChatRequired'), trigger: 'blur' },
    { pattern: numericId, message: () => t('settings.invalidChatId'), trigger: 'blur' },
  ],
  allowed_chat_ids: [{ validator: validateIdList, trigger: 'blur' }],
  admin_telegram_user_ids: [{ validator: validateIdList, trigger: 'blur' }],
}

function fillForm(settings: SystemSettings) {
  form.bot_token = ''
  form.default_chat_id = settings.default_chat_id || ''
  form.allowed_chat_ids = settings.allowed_chat_ids || ''
  form.admin_telegram_user_ids = settings.admin_telegram_user_ids || ''
}

async function load() {
  loading.value = true
  try {
    s.value = await getSettings()
    fillForm(s.value)
  } catch (e: any) {
    ElMessage.error(e?.message || t('common.failed'))
  } finally {
    loading.value = false
  }
  await loadWebhook()
}

/** Read-only webhook check; never throws so the page still renders. */
async function loadWebhook() {
  checkingWebhook.value = true
  try {
    const data = await getWebhookStatus()
    // `ok` is our own "diagnostic ran cleanly" flag, not part of the payload.
    webhook.value = { ...data, ok: !!data.registered && data.code === '' }
    if (!baseUrlInput.value) baseUrlInput.value = data.app_base_url || ''
  } catch {
    webhook.value = null
  } finally {
    checkingWebhook.value = false
  }
}

/** Save the public URL, then immediately try to register the webhook. */
async function saveBaseUrlAndRegister() {
  const value = baseUrlInput.value.trim()
  if (!value) {
    ElMessage.warning(t('settings.baseUrlRequired'))
    return
  }
  savingBaseUrl.value = true
  try {
    await updatePublicBaseUrl(value)
    ElMessage.success(t('settings.baseUrlSaved'))
    await loadWebhook()
    await registerWebhook()
  } catch (e: any) {
    ElMessage.error(describeSendError(e))
    await loadWebhook()
  } finally {
    savingBaseUrl.value = false
  }
}

/** Register the callback URL so group buttons start working. */
async function registerWebhook() {
  registeringWebhook.value = true
  try {
    const res = await registerWebhookApi()
    ElMessage.success(t('settings.webhookRegistered', { url: res.url }))
    await loadWebhook()
  } catch (e: any) {
    ElMessage.error(describeSendError(e))
    await loadWebhook()
  } finally {
    registeringWebhook.value = false
  }
}

async function saveTelegram() {
  if (!formRef.value || !(await formRef.value.validate().catch(() => false))) return
  saving.value = true
  try {
    s.value = await updateTelegramSettings({
      bot_token: form.bot_token || undefined,
      default_chat_id: form.default_chat_id,
      allowed_chat_ids: form.allowed_chat_ids,
      admin_telegram_user_ids: form.admin_telegram_user_ids,
    })
    fillForm(s.value)
    testResult.value = null
    ElMessage.success(t('settings.saved'))
  } catch (e: any) {
    ElMessage.error(e?.message || t('settings.saveFailed'))
  } finally {
    saving.value = false
  }
}

/** Run the end-to-end health check against the configured bot + group. */
async function runTest(sendMessage: boolean) {
  testing.value = true
  testResult.value = null
  try {
    const chatId = (form.default_chat_id || '').trim()
    testResult.value = await testTelegramConnection({
      chat_id: chatId || undefined,
      send_test_message: sendMessage,
    })
    if (testResult.value.ok) {
      ElMessage.success(t('settings.testPassed'))
    }
  } catch (e: any) {
    ElMessage.error(e?.message || t('settings.testFailed'))
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.block { margin-bottom: 14px; }
.tag { margin-right: 4px; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.notice { margin-bottom: 16px; }
.help { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.4; }
.test-result { margin-top: 14px; }
.test-lines { font-size: 13px; line-height: 1.8; }
.test-warn { color: #e6a23c; margin-top: 4px; }
.test-fix { color: #f56c6c; margin-top: 6px; font-weight: 600; }
.webhook-actions { margin-top: 14px; display: flex; gap: 10px; flex-wrap: wrap; }
.webhook-fix { margin-top: 10px; color: #f56c6c; font-weight: 600; font-size: 13px; }
.tips {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.config-alert { margin-bottom: 14px; }
.baseurl-form { margin-top: 14px; }
.baseurl-row { display: flex; gap: 8px; margin: 8px 0; }
.baseurl-row :deep(.el-input) { flex: 1; }
code {
  padding: 1px 5px; border-radius: 4px;
  background: var(--el-fill-color-light); font-family: monospace; font-size: 12px;
}
</style>
