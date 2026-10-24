<script setup lang="ts">
// Оболочка компании. Дашборд грузится один раз и раздаётся вкладкам через provide/inject;
// после любого действия (событие, выписка, категория, вложение) вкладка вызывает reload().
import { ChevronLeft, LogOut, MessageCircle } from 'lucide-vue-next'
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, logout, type AccountBalance, type Company, type Dashboard } from '../api'
import AppLogo from '../components/AppLogo.vue'
import AssistantPanel from '../components/AssistantPanel.vue'

const route = useRoute()
const router = useRouter()
const dashboard = ref<Dashboard | null>(null)
const company = ref<Company | null>(null)
const balance = ref<AccountBalance | null>(null)
const emptyHistory = ref(false)
const error = ref('')
const assistantOpen = ref(false)
const toastText = ref('')
let toastTimer: number | undefined
let reloadSeq = 0
onBeforeUnmount(() => { ++reloadSeq; window.clearTimeout(toastTimer) })

async function reload() {
  const seq = ++reloadSeq
  const id = route.params.id as string
  error.value = ''
  emptyHistory.value = false
  try {
    const [currentCompany, currentBalance] = await Promise.all([api.company(id), api.balance(id)])
    if (seq !== reloadSeq) return
    company.value = currentCompany
    balance.value = currentBalance
    const currentDashboard = await api.dashboard(id)
    if (seq === reloadSeq) dashboard.value = currentDashboard
  } catch (e) {
    if (seq !== reloadSeq) return
    dashboard.value = null
    if (e instanceof ApiError && e.status === 409) emptyHistory.value = true
    else error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить прогноз'
  }
}

function toast(text: string) {
  toastText.value = text
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toastText.value = ''), 4000)
}

provide('dashboard', dashboard)
provide('company', company)
provide('balance', balance)
provide('emptyHistory', emptyHistory)
provide('reload', reload)
provide('toast', toast)
watch(() => route.params.id, () => { dashboard.value = null; company.value = null; balance.value = null; assistantOpen.value = false; reload() }, { immediate: true })

const base = computed(() => `/companies/${route.params.id}`)
const tabs = [
  { to: '', label: 'Главная' },
  { to: 'operations', label: 'Операции' },
  { to: 'scenarios', label: 'Сценарии' },
  { to: 'plan-fact', label: 'План-факт' },
  { to: 'sources', label: 'Источники' },
]
const isActive = (to: string) => route.path.replace(/\/$/, '') === (to ? `${base.value}/${to}` : base.value)

function signOut() {
  logout()
  router.push('/login')
}
</script>

<template>
  <div class="shell">
    <header class="top">
      <div class="bar">
        <RouterLink to="/companies" class="home" aria-label="Все компании"><AppLogo /></RouterLink>
        <nav class="tabs" aria-label="Разделы">
          <RouterLink v-for="t in tabs" :key="t.to" :to="t.to ? `${base}/${t.to}` : base"
                      :aria-current="isActive(t.to) ? 'page' : undefined">{{ t.label }}</RouterLink>
        </nav>
        <div class="right">
          <button class="btn btn-sm" @click="assistantOpen = true"><MessageCircle />Спросить</button>
          <button class="btn btn-ghost btn-icon" aria-label="Выйти" title="Выйти" @click="signOut"><LogOut /></button>
        </div>
      </div>
    </header>

    <div class="page">
      <div class="crumbs">
        <RouterLink to="/companies" class="back"><ChevronLeft />Все компании</RouterLink>
        <span v-if="company" class="company">{{ company.name }}</span>
      </div>
      <p v-if="error" class="error banner" role="alert">{{ error }}</p>
      <div v-if="emptyHistory && !isActive('operations') && !isActive('sources')" class="card empty">
        <h2>{{ balance?.source === 'unknown' && balance.first_operation_date ? 'Для прогноза нужен начальный остаток' : 'Для прогноза нужна история платежей' }}</h2>
        <p class="muted">Загрузите выписку или добавьте проведённые платежи и укажите начальный остаток в «Источниках».</p>
        <RouterLink class="btn btn-primary" :to="`${base}/operations`">Перейти к операциям</RouterLink>
        <RouterLink class="btn" :to="`${base}/sources`">Настроить остаток</RouterLink>
      </div>
      <RouterView v-else :key="route.params.id as string" />
    </div>

    <AssistantPanel v-if="assistantOpen" :company-id="route.params.id as string" @close="assistantOpen = false" />
    <p v-if="toastText" class="toast" role="status">{{ toastText }}</p>
  </div>
</template>

<style scoped>
.top { position: sticky; top: 0; z-index: 30; background: var(--surface); border-bottom: 1px solid var(--line); }
.bar { max-width: var(--page); margin: 0 auto; padding: 0 24px; height: 64px; display: flex; align-items: center; gap: 32px; }
.home { text-decoration: none; flex: none; }
.tabs { display: flex; gap: 4px; height: 100%; overflow-x: auto; scrollbar-width: none; }
.tabs a {
  display: flex; align-items: center; padding: 0 12px; height: 100%; text-decoration: none; color: var(--ink-2);
  font-weight: 550; font-size: 15px; border-bottom: 2px solid transparent; white-space: nowrap;
}
.tabs a:hover { color: var(--ink); }
.tabs a[aria-current='page'] { color: var(--ink); border-bottom-color: var(--brand); }
.right { margin-left: auto; display: flex; gap: 4px; align-items: center; flex: none; }
.page { max-width: var(--page); margin: 0 auto; padding: 20px 24px 64px; }
.crumbs { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; font-size: 14px; color: var(--ink-2); flex-wrap: wrap; }
.back { display: inline-flex; align-items: center; gap: 2px; color: var(--ink-2); text-decoration: none; }
.back svg { width: 16px; height: 16px; }
.back:hover { color: var(--ink); }
.company { font-weight: 600; color: var(--ink); padding-left: 12px; border-left: 1px solid var(--line); }
.banner { margin-bottom: 16px; }
.empty { display: grid; gap: 12px; justify-items: start; }
@media (max-width: 900px) {
  .bar { height: auto; flex-wrap: wrap; gap: 0 12px; padding: 0 16px; }
  .home { padding: 12px 0; }
  .tabs { order: 3; width: 100%; height: 44px; margin: 0 -12px; }
  .page { padding: 16px 16px 48px; }
}
@media (max-width: 480px) {
  .home :deep(.word) { display: none; }
}
</style>
