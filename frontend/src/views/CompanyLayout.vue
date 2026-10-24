<script setup lang="ts">
// Оболочка вкладок компании. Дашборд грузится один раз и раздаётся вкладкам через provide/inject;
// после любого действия (событие, выписка, категория) вкладка вызывает reload().
import { provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, logout, type Company, type Dashboard } from '../api'
import AssistantPanel from '../components/AssistantPanel.vue'
import BrandLogo from '../components/BrandLogo.vue'
import AppIcon from '../components/AppIcon.vue'

const route = useRoute()
const router = useRouter()
const dashboard = ref<Dashboard | null>(null)
const company = ref<Company | null>(null)
const emptyHistory = ref(false)
const error = ref('')
const assistantOpen = ref(false)

async function reload() {
  error.value = ''
  dashboard.value = null
  emptyHistory.value = false
  try {
    company.value = await api.company(route.params.id as string)
    dashboard.value = await api.dashboard(route.params.id as string)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) emptyHistory.value = true
    else error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить прогноз'
  }
}

provide('dashboard', dashboard)
provide('company', company)
provide('emptyHistory', emptyHistory)
provide('reload', reload)
watch(() => route.params.id, reload, { immediate: true })

const tabs = [
  { to: '', label: 'Прогноз', icon: 'forecast' },
  { to: 'operations', label: 'Операции', icon: 'operations' },
  { to: 'scenarios', label: 'Сценарии', icon: 'scenarios' },
  { to: 'plan-fact', label: 'План-факт', icon: 'chart' },
  { to: 'sources', label: 'Источники', icon: 'sources' },
]
function signOut() { logout(); router.push('/login') }
</script>

<template>
  <div class="shell">
    <header class="top">
      <RouterLink to="/companies" class="brand-link" aria-label="Деньги, вперёд! — мои компании"><BrandLogo /></RouterLink>
      <nav class="tabs" aria-label="Разделы компании">
        <RouterLink v-for="t in tabs" :key="t.to" :to="`/companies/${route.params.id}/${t.to}`"
                    :class="{ active: route.path.replace(/\/$/, '') === `/companies/${route.params.id}${t.to ? '/' + t.to : ''}` }">
          <AppIcon :name="t.icon" :size="20" /> {{ t.label }}
        </RouterLink>
      </nav>
      <button class="btn sign-out" aria-label="Выйти из аккаунта" @click="signOut"><AppIcon name="logout" :size="19" /><span>Выйти</span></button>
    </header>
    <div class="company-context"><RouterLink to="/companies">Мои компании</RouterLink><span aria-hidden="true">/</span><span>{{ company?.name ?? 'Загружаем компанию…' }}</span></div>
    <p v-if="error" class="error page" role="alert">{{ error }}</p>
    <p v-if="emptyHistory" class="empty">Для прогноза нужна история платежей.
      <RouterLink :to="`/companies/${route.params.id}/operations`">Добавьте платёж или загрузите выписку</RouterLink>.
    </p>
    <main class="page"><RouterView /></main>
    <button class="ask btn btn-primary" @click="assistantOpen = true">Спросить</button>
    <AssistantPanel v-if="assistantOpen" :company-id="route.params.id as string" @close="assistantOpen = false" />
  </div>
</template>

<style scoped>
.top { background: var(--surface); border-bottom: 1px solid var(--line); padding: 0 28px; display: flex; align-items: center; gap: 28px; min-height: 80px; }
.empty { max-width: 1376px; margin: 20px auto 0; padding: 0 28px; color: var(--ink-2); }
.brand-link { text-decoration: none; display: inline-flex; }
.tabs { display: flex; gap: 4px; overflow-x: auto; flex: 1; min-width: 0; }
.tabs a { display: inline-flex; align-items: center; gap: 8px; padding: 27px 12px 23px; text-decoration: none; color: var(--ink-2); border-bottom: 3px solid transparent; white-space: nowrap; }
.tabs a.active { color: var(--ink); border-color: var(--green); font-weight: 500; }
.tabs a.active { color: var(--green); }
.sign-out { display: inline-flex; align-items: center; gap: 7px; border-color: transparent; font-size: 14px; }
.company-context { max-width: 1376px; margin: 0 auto; display: flex; gap: 10px; padding: 20px 28px 0; color: var(--ink-2); font-size: 13px; }
.company-context a { color: var(--ink-2); text-underline-offset: 3px; }
.page { max-width: 1376px; margin: 0 auto; padding: 24px 28px 96px; }
.ask { position: fixed; right: 20px; bottom: 20px; border-radius: 999px; padding: 12px 20px; box-shadow: 0 4px 16px rgb(15 123 87 / 0.25); }
@media (max-width: 1100px) {
  .top { flex-wrap: wrap; gap: 0 20px; padding: 16px 20px 0; }
  .tabs { order: 3; flex-basis: 100%; }
  .tabs a { padding-block: 16px 12px; }
  .sign-out { margin-left: auto; }
}
@media (max-width: 600px) {
  .top { padding-inline: 16px; }
  .tabs { gap: 0; }
  .tabs a { padding-inline: 10px; font-size: 14px; }
  .tabs svg { display: none; }
  .sign-out span { display: none; }
  .company-context { padding: 16px 16px 0; flex-wrap: wrap; }
  .page { padding: 20px 16px 90px; }
}
</style>
