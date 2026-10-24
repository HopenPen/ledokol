<script setup lang="ts">
// План-факт: сверху график «ожидали vs было» по дням, ниже — какие ожидаемые платежи пришли, а какие нет.
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type DailyPlanFact, type PlanFactRow } from '../api'
import PlanFactChart from '../components/PlanFactChart.vue'
import { humanDate, rub } from '../format'

const route = useRoute()
const id = route.params.id as string
const reload = inject<() => Promise<void>>('reload')!
const rows = ref<PlanFactRow[]>([])
const daily = ref<DailyPlanFact | null>(null)
const error = ref('')
const STATUS = { received: 'Пришло', partial: 'Частично', missed: 'Не пришло', pending: 'Ждём' } as Record<string, string>

const summary = computed(() => {
  const d = daily.value
  if (!d?.run || !d.rows.length) return ''
  const last = d.rows[d.rows.length - 1]
  const sign = last.deviation >= 0 ? 'больше' : 'меньше'
  return `Прогноз от ${humanDate(d.run.as_of)}: сейчас на счёте на ${rub(Math.abs(last.deviation))} ${sign}, чем ожидали. `
    + (d.flagged_days ? `Необычных дней: ${d.flagged_days}.` : 'Всё в пределах обычного разброса.')
})

async function load() {
  try {
    [rows.value, daily.value] = await Promise.all([api.planFact(id), api.planFactDaily(id)])
  } catch (e) { error.value = (e as Error).message }
}
onMounted(load)

async function onFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    await api.uploadStatement(id, file)
    await reload()
    await load()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить выписку'
  }
}
</script>

<template>
  <div class="stack">
    <section class="card">
      <header class="head">
        <div>
          <h2>Ожидали и было</h2>
          <p class="muted">Прошлый прогноз против фактического остатка. Красные точки — дни, когда остаток вышел за обычный разброс.</p>
        </div>
        <label class="btn btn-primary">Загрузить новую выписку<input type="file" accept=".csv" hidden @change="onFile" /></label>
      </header>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="!daily?.run" class="muted">Сравнивать пока не с чем: загрузите выписку за следующие дни — увидите, насколько сбылся сегодняшний прогноз.</p>
      <template v-else>
        <p class="summary">{{ summary }}</p>
        <PlanFactChart :rows="daily.rows" />
      </template>
    </section>

    <section class="card">
      <h2>Ожидаемые платежи</h2>
      <p v-if="!rows.length" class="muted">Добавьте ожидаемые платежи на вкладке «Прогноз» — здесь будет видно, пришли ли они.</p>
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
  </div>
</template>

<style scoped>
.stack { display: grid; gap: 20px; }
.head { display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 12px; }
h2 { font-size: 18px; }
.muted { color: var(--muted); margin: 4px 0 0; }
.summary { font-weight: 500; }
table { width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 8px; }
th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--line); }
td { padding: 8px; border-bottom: 1px solid var(--line); }
.r { text-align: right; }
.status { padding: 2px 8px; border-radius: 999px; font-size: 13px; background: var(--paper); }
.status.received { background: var(--green-wash); color: var(--green); }
.status.partial { background: var(--warn-wash); color: var(--warn); }
.status.missed { background: var(--risk-wash); color: var(--risk); }
</style>
