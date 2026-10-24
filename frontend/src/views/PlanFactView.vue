<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type PlanFactRow } from '../api'
import { humanDate, rub } from '../format'

const route = useRoute()
const reload = inject<() => Promise<void>>('reload')!
const rows = ref<PlanFactRow[]>([])
const error = ref('')
const STATUS = { received: 'Пришло', partial: 'Частично', missed: 'Не пришло', pending: 'Ждём' } as Record<string, string>

async function load() {
  try { rows.value = await api.planFact(route.params.id as string) } catch (e) { error.value = (e as Error).message }
}
onMounted(load)

async function onFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    await api.uploadStatement(route.params.id as string, file)
    await Promise.all([load(), reload()])
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить выписку'
  }
}
</script>

<template>
  <section class="card">
    <header class="head">
      <div>
        <h2>План-факт</h2>
        <p class="muted">Что ожидали и что пришло на самом деле. Не пришедший платёж сразу учитывается в прогнозе.</p>
      </div>
      <label class="btn btn-primary">Загрузить новую выписку<input type="file" accept=".csv" hidden @change="onFile" /></label>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="!rows.length" class="muted">Пока сравнивать нечего: добавьте ожидаемые платежи на вкладке «Прогноз» и загрузите следующую выписку.</p>
    <table v-else>
      <thead><tr><th>Что ждали</th><th>Когда</th><th class="r">Сколько</th><th>Статус</th><th class="r">Пришло</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="(r.event_id ?? '') + r.planned_date">
          <td>{{ r.title }}</td>
          <td>{{ humanDate(r.planned_date) }}</td>
          <td class="r num">{{ rub(r.planned_amount) }}</td>
          <td><span class="status" :class="r.status">{{ STATUS[r.status] }}</span></td>
          <td class="r num">{{ r.actual_amount ? rub(r.actual_amount) : '—' }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 12px; }
.muted { color: var(--muted); margin: 4px 0 0; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--line); }
td { padding: 8px; border-bottom: 1px solid var(--line); }
.r { text-align: right; }
.status { padding: 2px 8px; border-radius: 999px; font-size: 13px; background: var(--paper); }
.status.received { background: var(--green-wash); color: var(--green); }
.status.partial { background: var(--warn-wash); color: var(--warn); }
.status.missed { background: var(--risk-wash); color: var(--risk); }
</style>
