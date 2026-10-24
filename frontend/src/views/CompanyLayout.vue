<script setup lang="ts">
// Оболочка вкладок компании. Дашборд грузится один раз и раздаётся вкладкам через provide/inject;
// после любого действия (событие, выписка, категория) вкладка вызывает reload().
import { provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type Dashboard } from '../api'
import AssistantPanel from '../components/AssistantPanel.vue'

const route = useRoute()
const dashboard = ref<Dashboard | null>(null)
const error = ref('')
const assistantOpen = ref(false)

async function reload() {
  error.value = ''
  try {
    dashboard.value = await api.dashboard(route.params.id as string)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить прогноз'
  }
}

provide('dashboard', dashboard)
provide('reload', reload)
watch(() => route.params.id, reload, { immediate: true })

const tabs = [
  { to: '', label: 'Прогноз' },
  { to: 'scenarios', label: 'Что если' },
  { to: 'operations', label: 'Операции' },
  { to: 'plan-fact', label: 'План-факт' },
  { to: 'sources', label: 'Источники' },
]
</script>

<template>
  <div class="shell">
    <header class="top">
      <RouterLink to="/companies" class="back">← Компании</RouterLink>
      <h1 v-if="dashboard">{{ dashboard.company.name }}</h1>
      <nav class="tabs" aria-label="Разделы компании">
        <RouterLink v-for="t in tabs" :key="t.to" :to="`/companies/${route.params.id}/${t.to}`"
                    :class="{ active: route.path.replace(/\/$/, '') === `/companies/${route.params.id}${t.to ? '/' + t.to : ''}` }">
          {{ t.label }}
        </RouterLink>
      </nav>
    </header>
    <p v-if="error" class="error page" role="alert">{{ error }}</p>
    <main class="page"><RouterView /></main>
    <button class="ask btn btn-primary" @click="assistantOpen = true">Спросить</button>
    <AssistantPanel v-if="assistantOpen" :company-id="route.params.id as string" @close="assistantOpen = false" />
  </div>
</template>

<style scoped>
.top { background: var(--surface); border-bottom: 1px solid var(--line); padding: 12px 16px 0; }
.back { color: var(--ink-2); text-decoration: none; font-size: 14px; }
h1 { font-size: 20px; margin: 4px 0 8px; }
.tabs { display: flex; gap: 4px; overflow-x: auto; }
.tabs a { padding: 8px 12px; text-decoration: none; color: var(--ink-2); border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs a.active { color: var(--ink); border-color: var(--green); font-weight: 500; }
.page { max-width: 1180px; margin: 0 auto; padding: 24px 16px 96px; }
.ask { position: fixed; right: 20px; bottom: 20px; border-radius: 999px; padding: 12px 20px; box-shadow: 0 4px 16px rgb(15 123 87 / 0.25); }
</style>
