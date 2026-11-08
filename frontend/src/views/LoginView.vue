<template>
  <div ref="shellEl" class="login-shell" @pointermove.passive="onPointerMove" @pointerleave="onPointerLeave">
    <!-- Cinematic backdrop: dark base, a warm light beam, a faint tile grid. -->
    <div class="bg" aria-hidden="true">
      <div class="bg__orb bg__orb--amber"></div>
      <div class="bg__orb bg__orb--red"></div>
      <div class="bg__glow"></div>
      <div class="bg__beam"></div>
      <div class="bg__grid"></div>
      <div class="bg__dust">
        <i v-for="n in 12" :key="n"></i>
      </div>
      <div class="bg__spot"></div>
      <div class="bg__noise"></div>
      <div class="bg__vignette"></div>
    </div>

    <div class="lang" role="group" aria-label="Language">
      <button
        type="button"
        class="lang__btn"
        :class="{ 'lang__btn--on': locale === 'zh-CN' }"
        @click="switchLocale('zh-CN')"
      >中文</button>
      <button
        type="button"
        class="lang__btn"
        :class="{ 'lang__btn--on': locale === 'en' }"
        @click="switchLocale('en')"
      >EN</button>
    </div>

    <main class="login-page">
      <div class="brand">
        <span class="brand__mark" aria-hidden="true"></span>
        <span class="brand__name">OrderFlow</span>
      </div>

      <section class="card">
        <span class="card__sheen" aria-hidden="true"></span>
        <h1 class="card__title">{{ t('common.login') }}</h1>

        <form class="form" @submit.prevent="onSubmit">
          <label class="field">
            <span class="field__label">{{ t('common.username') }}</span>
            <el-input
              v-model="username"
              size="large"
              :placeholder="t('login.pleaseInputUser')"
              autofocus
            />
          </label>

          <label class="field">
            <span class="field__label">{{ t('common.password') }}</span>
            <el-input
              v-model="password"
              type="password"
              size="large"
              show-password
              :placeholder="t('login.pleaseInputPass')"
              @keyup.enter="onSubmit"
            />
          </label>

          <div v-if="error" class="notice notice--error">{{ error }}</div>

          <el-button
            class="submit"
            type="primary"
            native-type="submit"
            :loading="loading"
          >
            {{ t('common.login') }}
          </el-button>
        </form>

        <div class="divider"><span>{{ t('login.or') }}</span></div>

        <div class="telegram">
          <div ref="telegramMount" class="telegram__mount"></div>
          <div v-if="telegramError" class="notice notice--muted">{{ telegramError }}</div>
          <div v-if="pendingNotice" class="notice notice--warn">{{ pendingNotice }}</div>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authStore } from '@/store/auth'
import api from '@/api/client'
import { currentLocale, setLocale, type AppLocale } from '@/i18n'

function landing(): string {
  if (auth.user?.role === 'admin') return '/admin/orders'
  if (auth.user?.role === 'dispatcher') return '/dispatcher/orders'
  return '/partner/orders'
}

declare global {
  interface Window { onTelegramAuth?: (payload: Record<string, string | number>) => void }
}

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const auth = authStore()

const locale = ref<AppLocale>(currentLocale())

function switchLocale(next: AppLocale) {
  setLocale(next)
  locale.value = next
}

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const telegramError = ref('')
const pendingNotice = ref('')
const telegramMount = ref<HTMLDivElement | null>(null)
const shellEl = ref<HTMLDivElement | null>(null)
let telegramScript: HTMLScriptElement | null = null

// Pointer spotlight: rAF-throttled so moving the mouse stays at 60fps.
let spotRaf = 0
let spotX = 50
let spotY = 42

function onPointerMove(e: PointerEvent) {
  spotX = (e.clientX / Math.max(1, window.innerWidth)) * 100
  spotY = (e.clientY / Math.max(1, window.innerHeight)) * 100
  if (spotRaf) return
  spotRaf = requestAnimationFrame(() => {
    spotRaf = 0
    const el = shellEl.value
    if (!el) return
    el.style.setProperty('--spot-x', `${spotX}%`)
    el.style.setProperty('--spot-y', `${spotY}%`)
  })
}

function onPointerLeave() {
  const el = shellEl.value
  if (!el) return
  el.style.setProperty('--spot-x', '50%')
  el.style.setProperty('--spot-y', '42%')
}

onMounted(async () => {
  try {
    const { data } = await api.get<{ bot_username: string }>('/api/auth/telegram/config')
    if (!telegramMount.value) return
    window.onTelegramAuth = async (payload) => {
      error.value = ''
      pendingNotice.value = ''
      try {
        const { data: result } = await api.post('/api/auth/telegram', payload)
        if (result.status === 'pending_approval') {
          pendingNotice.value = t('login.pendingApproval')
          return
        }
        auth.setSession(result.access_token, result.user)
        router.push((route.query.redirect as string) || landing())
      } catch (e: any) {
        error.value = e?.message || t('login.telegramLoginFailed')
      }
    }
    telegramScript = document.createElement('script')
    telegramScript.async = true
    telegramScript.src = 'https://telegram.org/js/telegram-widget.js?22'
    telegramScript.setAttribute('data-telegram-login', data.bot_username)
    telegramScript.setAttribute('data-size', 'large')
    telegramScript.setAttribute('data-userpic', 'false')
    telegramScript.setAttribute('data-onauth', 'onTelegramAuth(user)')
    telegramMount.value.appendChild(telegramScript)
  } catch {
    telegramError.value = t('login.telegramUnavailable')
  }
})

onBeforeUnmount(() => {
  if (spotRaf) cancelAnimationFrame(spotRaf)
  telegramScript?.remove()
  delete window.onTelegramAuth
})

async function onSubmit() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = t('login.pleaseInputUser')
    return
  }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    ElMessage.success(t('common.success'))
    const redirect = (route.query.redirect as string) || landing()
    router.push(redirect)
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || ''
    error.value = msg === 'Invalid username or password' ? t('login.invalid') : (msg || t('login.invalid'))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-shell {
  position: relative;
  box-sizing: border-box;
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 40px 20px 56px;
  background: #08080a;
  color: #f2f2f4;
  overflow: hidden;
  color-scheme: dark;
}

/* ---------- backdrop ---------- */
.bg { position: absolute; inset: 0; pointer-events: none; }

.lang {
  position: absolute;
  top: 20px;
  right: 22px;
  z-index: 2;
  display: flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.03);
  backdrop-filter: blur(10px);
}

.lang__btn {
  border: 0;
  background: transparent;
  color: #8a8a90;
  font-size: 12px;
  line-height: 1;
  padding: 6px 11px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.lang__btn:hover { color: #f2f2f4; }

.lang__btn--on {
  background: rgba(255, 255, 255, 0.10);
  color: #f2f2f4;
}

.bg__glow {
  position: absolute;
  top: -42vh;
  right: -22vw;
  width: 92vw;
  height: 130vh;
  background: radial-gradient(
    closest-side,
    rgba(224, 86, 74, 0.30),
    rgba(224, 86, 74, 0.08) 55%,
    transparent 76%
  );
  filter: blur(24px);
}

/* A soft diagonal shaft, echoing a projector beam. */
.bg__beam {
  position: absolute;
  top: -30%;
  right: -14%;
  width: 76%;
  height: 160%;
  background: linear-gradient(
    114deg,
    transparent 42%,
    rgba(255, 170, 120, 0.10) 48.5%,
    rgba(255, 228, 195, 0.06) 51%,
    transparent 58%
  );
  transform: rotate(-6deg);
  filter: blur(22px);
}

.bg__grid {
  position: absolute;
  inset: -12%;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='168' height='168'%3E%3Crect x='8' y='8' width='152' height='152' rx='30' fill='none' stroke='%23ffffff' stroke-opacity='0.055' stroke-width='2'/%3E%3C/svg%3E");
  background-size: 168px 168px;
  -webkit-mask-image: radial-gradient(ellipse at 50% 44%, #000 8%, transparent 68%);
  mask-image: radial-gradient(ellipse at 50% 44%, #000 8%, transparent 68%);
  opacity: 0.8;
}

.bg__vignette {
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 38%, transparent 26%, rgba(0, 0, 0, 0.62) 100%);
}

/* ---------- layout ---------- */
.login-page {
  position: relative;
  width: min(400px, 100%);
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 26px;
}

.brand__mark {
  position: relative;
  width: 22px;
  height: 22px;
  border: 2px solid rgba(255, 255, 255, 0.92);
  border-radius: 50%;
}

.brand__mark::after {
  content: "";
  position: absolute;
  top: -1px;
  right: -4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #e0564a;
  box-shadow: 0 0 14px rgba(224, 86, 74, 0.95);
}

.brand__name {
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: #f2f2f4;
}

/* ---------- card ---------- */
.card {
  padding: 30px 28px 26px;
  background: rgba(18, 18, 21, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 18px;
  box-shadow:
    0 40px 120px rgba(0, 0, 0, 0.62),
    inset 0 1px 0 rgba(255, 255, 255, 0.045);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}

.card__title {
  margin: 0 0 22px;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #f5f5f7;
}

.form { display: grid; gap: 15px; }
.field { display: grid; gap: 8px; }

.field__label {
  font-size: 12.5px;
  font-weight: 400;
  color: #9a9aa1;
  letter-spacing: 0.02em;
}

/* ---------- Element Plus inputs, dark ---------- */
:deep(.el-input__wrapper) {
  height: 46px;
  padding: 2px 14px;
  background: #212125;
  border: 1px solid transparent;
  border-radius: 10px;
  box-shadow: none;
  transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

:deep(.el-input__wrapper:hover) {
  background: #26262b;
}

:deep(.el-input__wrapper.is-focus) {
  background: #242428;
  border-color: rgba(224, 86, 74, 0.65);
  box-shadow: 0 0 0 3px rgba(224, 86, 74, 0.13);
}

:deep(.el-input__inner) {
  color: #f2f2f4;
  font-size: 14.5px;
}

:deep(.el-input__inner::placeholder) {
  color: #6e6e76;
}

:deep(.el-input__suffix .el-input__icon) {
  color: #8a8a92;
}

/* Chrome paints autofilled fields white; keep them dark. */
:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus) {
  -webkit-text-fill-color: #f2f2f4;
  -webkit-box-shadow: 0 0 0 1000px #212125 inset;
  caret-color: #f2f2f4;
  transition: background-color 9999s ease-out 0s;
}

/* ---------- primary action ---------- */
.submit.el-button--primary {
  width: 100%;
  height: 46px;
  margin-top: 3px;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: #ffffff;
  background: linear-gradient(180deg, #dd5147 0%, #a32d2d 100%);
  box-shadow: 0 10px 28px rgba(163, 45, 45, 0.34);
}

.submit.el-button--primary:hover,
.submit.el-button--primary:focus {
  color: #ffffff;
  background: linear-gradient(180deg, #e45f55 0%, #b13333 100%);
  box-shadow: 0 12px 32px rgba(163, 45, 45, 0.42);
}

.submit.el-button--primary:active {
  transform: translateY(1px);
}

.submit.el-button--primary.is-loading {
  opacity: 0.85;
}

/* ---------- notices ---------- */
.notice {
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
}

.notice--error {
  color: #ffb4ae;
  background: rgba(224, 86, 74, 0.12);
  border: 1px solid rgba(224, 86, 74, 0.30);
}

.notice--warn {
  color: #f0c46a;
  background: rgba(240, 180, 60, 0.10);
  border: 1px solid rgba(240, 180, 60, 0.26);
}

.notice--muted {
  color: #9a9aa1;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.07);
}

/* ---------- telegram ---------- */
.divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 22px 0 18px;
  color: #6e6e76;
  font-size: 12.5px;
}

.divider::before,
.divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
}

.telegram {
  display: grid;
  justify-items: center;
  gap: 10px;
}

.telegram__mount {
  display: flex;
  justify-content: center;
  min-height: 40px;
  border-radius: 20px;
  overflow: hidden;
}

/* Telegram's iframe is rectangular; clip it to the button's pill shape so
   the white corners of the cross-origin document do not show on the card. */
.telegram__mount :deep(iframe) {
  border-radius: 20px !important;
  overflow: hidden !important;
  background: transparent !important;
}

/* ---------- small screens ---------- */
@media (max-width: 480px) {
  .login-shell { padding: 28px 14px 40px; }
  .card { padding: 24px 18px 22px; border-radius: 16px; }
  .brand { margin-bottom: 20px; }
}

/* ---------- cinematic motion ---------- */

.bg__dust {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.bg__dust i {
  position: absolute;
  bottom: -6vh;
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: rgba(255, 214, 188, 0.9);
  box-shadow: 0 0 10px 2px rgba(255, 120, 90, 0.5);
  opacity: 0;
  animation-name: dustRise;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
  will-change: transform, opacity;
}

.bg__dust i:nth-child(1)  { left: 5%;  animation-duration: 19s; animation-delay: -1s; }
.bg__dust i:nth-child(2)  { left: 13%; animation-duration: 23s; animation-delay: -9s; width: 3px; height: 3px; }
.bg__dust i:nth-child(3)  { left: 21%; animation-duration: 17s; animation-delay: -13s; }
.bg__dust i:nth-child(4)  { left: 29%; animation-duration: 21s; animation-delay: -5s; width: 1px; height: 1px; }
.bg__dust i:nth-child(5)  { left: 37%; animation-duration: 25s; animation-delay: -17s; }
.bg__dust i:nth-child(6)  { left: 45%; animation-duration: 18s; animation-delay: -7s; width: 3px; height: 3px; }
.bg__dust i:nth-child(7)  { left: 53%; animation-duration: 22s; animation-delay: -15s; }
.bg__dust i:nth-child(8)  { left: 61%; animation-duration: 19s; animation-delay: -3s; width: 1px; height: 1px; }
.bg__dust i:nth-child(9)  { left: 69%; animation-duration: 24s; animation-delay: -11s; }
.bg__dust i:nth-child(10) { left: 77%; animation-duration: 16s; animation-delay: -6s; width: 3px; height: 3px; }
.bg__dust i:nth-child(11) { left: 85%; animation-duration: 20s; animation-delay: -14s; }
.bg__dust i:nth-child(12) { left: 93%; animation-duration: 26s; animation-delay: -19s; width: 1px; height: 1px; }

@keyframes dustRise {
  0%   { transform: translate3d(0, 0, 0) scale(0.6); opacity: 0; }
  12%  { opacity: 0.8; }
  70%  { opacity: 0.4; }
  100% { transform: translate3d(28px, -108vh, 0) scale(1.15); opacity: 0; }
}

.login-shell {
  --spot-x: 50%;
  --spot-y: 42%;
}

.bg__orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(72px);
  pointer-events: none;
  will-change: transform, opacity;
}

.bg__orb--amber {
  left: -10vw;
  bottom: -18vh;
  width: 46vw;
  height: 46vw;
  background: radial-gradient(
    circle,
    rgba(255, 164, 92, 0.30),
    rgba(255, 120, 60, 0.08) 52%,
    transparent 72%
  );
  animation: orbDriftA 17s ease-in-out infinite alternate;
}

.bg__orb--red {
  right: 2vw;
  top: -6vh;
  width: 38vw;
  height: 38vw;
  background: radial-gradient(
    circle,
    rgba(224, 86, 74, 0.26),
    rgba(224, 86, 74, 0.06) 55%,
    transparent 74%
  );
  animation: orbDriftB 21s ease-in-out infinite alternate;
}

.bg__glow {
  animation: glowBreathe 13s ease-in-out infinite alternate;
}

.bg__beam {
  animation: beamSweep 9s ease-in-out infinite alternate;
}

.bg__grid {
  animation: gridDrift 26s linear infinite;
}

.bg__spot {
  position: absolute;
  inset: -25%;
  background: radial-gradient(
    circle 520px at var(--spot-x) var(--spot-y),
    rgba(255, 146, 110, 0.13),
    rgba(255, 146, 110, 0.03) 45%,
    transparent 70%
  );
  pointer-events: none;
}

.bg__noise {
  position: absolute;
  inset: -40%;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E");
  background-size: 180px 180px;
  opacity: 0.05;
  mix-blend-mode: overlay;
  animation: grainShift 1.4s steps(5) infinite;
  pointer-events: none;
}

.brand {
  animation: riseIn 0.8s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.brand__mark {
  border-color: rgba(255, 255, 255, 0.2);
}

.brand__mark::before {
  content: "";
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    transparent 0deg 208deg,
    rgba(255, 255, 255, 0.92) 264deg,
    rgba(224, 86, 74, 0.9) 300deg,
    transparent 332deg 360deg
  );
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));
  mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));
  animation: ringSpin 5s linear infinite;
}

.brand__mark::after {
  animation: dotPulse 3.2s ease-in-out infinite;
}

.card {
  position: relative;
  overflow: hidden;
  animation: cardIn 0.9s cubic-bezier(0.16, 1, 0.3, 1) 0.05s both;
}

.card__sheen {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(
    108deg,
    transparent 34%,
    rgba(255, 255, 255, 0.055) 47%,
    transparent 60%
  );
  transform: translateX(-130%);
  animation: cardSheen 5.5s cubic-bezier(0.4, 0, 0.2, 1) infinite;
  pointer-events: none;
}

@keyframes orbDriftA {
  0%   { transform: translate3d(0, 0, 0) scale(1); opacity: 0.45; }
  50%  { transform: translate3d(9%, -6%, 0) scale(1.18); opacity: 1; }
  100% { transform: translate3d(-5%, 4%, 0) scale(1.02); opacity: 0.55; }
}

@keyframes orbDriftB {
  0%   { transform: translate3d(0, 0, 0) scale(1.08); opacity: 0.4; }
  50%  { transform: translate3d(-7%, 7%, 0) scale(0.9); opacity: 0.95; }
  100% { transform: translate3d(6%, -5%, 0) scale(1.16); opacity: 0.5; }
}

@keyframes glowBreathe {
  0%   { transform: translate3d(0, 0, 0) scale(1); opacity: 0.66; }
  50%  { transform: translate3d(-4%, 3%, 0) scale(1.12); opacity: 1; }
  100% { transform: translate3d(3%, -3%, 0) scale(1.2); opacity: 0.78; }
}

@keyframes beamSweep {
  0%   { transform: translate3d(-9%, 0, 0) rotate(-8deg); opacity: 0.35; }
  50%  { transform: translate3d(0, 0, 0) rotate(-5.5deg); opacity: 1; }
  100% { transform: translate3d(9%, 0, 0) rotate(-3deg); opacity: 0.45; }
}

@keyframes gridDrift {
  from { background-position: 0 0; }
  to   { background-position: 168px 168px; }
}

@keyframes grainShift {
  0%, 100% { transform: translate3d(0, 0, 0); }
  20%      { transform: translate3d(-2%, 1%, 0); }
  40%      { transform: translate3d(1%, -2%, 0); }
  60%      { transform: translate3d(-1%, -1%, 0); }
  80%      { transform: translate3d(2%, 1%, 0); }
}

@keyframes ringSpin {
  to { transform: rotate(360deg); }
}

@keyframes dotPulse {
  0%, 100% {
    transform: scale(1);
    opacity: 0.88;
    box-shadow: 0 0 12px rgba(224, 86, 74, 0.85);
  }
  50% {
    transform: scale(1.45);
    opacity: 1;
    box-shadow: 0 0 24px rgba(255, 120, 100, 1);
  }
}

@keyframes riseIn {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes cardIn {
  from { opacity: 0; transform: translateY(22px) scale(0.985); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes cardSheen {
  0%, 52%  { transform: translateX(-130%); }
  88%, 100% { transform: translateX(130%); }
}

@media (prefers-reduced-motion: reduce) {
  .bg__orb,
  .bg__glow,
  .bg__beam,
  .bg__grid,
  .bg__noise,
  .bg__spot,
  .brand,
  .brand__mark::before,
  .brand__mark::after,
  .card,
  .card__sheen {
    animation: none !important;
  }
  .bg__spot { display: none; }
  .bg__dust { display: none; }
  .card__sheen { display: none; }
}

</style>
