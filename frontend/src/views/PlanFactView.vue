<script setup lang="ts">
// План-факт: «ожидали и было» по дням и список ожидаемых платежей со статусами.
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type DailyPlanFact, type ImportResult, type PlanFactRow } from '../api'
import PlanFactChart from '../components/PlanFactChart.vue'
import StatementUpload from '../components/StatementUpload.vue'
import { humanDate, importSummary, money, rub } from '../format'

const route = useRoute()
const id = route.params.id as string
const reload = inject<() => Promise<void>>('reload')!
const toast = inject<(t: string) => void>('toast')!
const rows = ref<PlanFactRow[]>([])
const daily = ref<DailyPlanFact | null>(null)
const error = ref('')
const loading = ref(true)
const STATUS: Record<string, { label: string; cls: string }> = {
  received: { label: 'Пришло', cls: 'chip-brand' }, partial: { label: 'Частично', cls: 'chip-warn' },
  missed: { label: 'Не пришло', cls: 'chip-risk' }, pending: { label: 'Ждём', cls: '' }, expected: { label: 'Ждём', cls: '' },
}

const summary = computed(() => {
  const d = daily.value
  if (!d?.run || !d.rows.length) return ''
  const last = d.rows[d.rows.length - 1]
  const sign = last.deviation >= 0 ? 'больше' : 'меньше'
  return `Сейчас на счёте на ${rub(Math.abs(last.deviation))} ${sign}, чем ожидали в прогнозе от ${humanDate(d.run.as_of)}.`
})

async function load() {
  loading.value = true
  error.value = ''
  try { [rows.value, daily.value] = await Promise.all([api.planFact(id), api.planFactDaily(id)]) }
  catch (e) { error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить план-факт' }
  finally { loading.value = false }
}
onMounted(load)

async function afterImport(results: ImportResult[]) {
  toast(importSummary(results))
  await reload()
  await load()
}
</script>

<template>
  <div class="pf">
    <div class="head">
      <div>
        <h1>План-факт</h1>
        <p class="muted small">Насколько сбылся прошлый прогноз и пришли ли ожидаемые деньги.</p>
      </div>
      <StatementUpload :company-id="id" label="Загрузить новую выписку" @imported="afterImport" @error="toast" />
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <section class="card">
      <div class="card-head"><h2>Ожидали и было</h2>
        <span v-if="daily?.run" class="chip" :class="daily.flagged_days ? 'chip-risk' : 'chip-brand'">
          {{ daily.flagged_days ? `необычных дней: ${daily.flagged_days}` : 'всё в пределах разброса' }}
        </span>
      </div>
      <div v-if="loading" class="skeleton" style="height: 300px" />
      <p v-else-if="!daily?.run" class="muted">Сравнивать пока не с чем. Загрузите выписку за следующие дни, и здесь будет видно, насколько сбылся сегодняшний прогноз.</p>
      <template v-else>
        <p class="summary">{{ summary }}</p>
        <PlanFactChart :rows="daily.rows" />
      </template>
    </section>

    <section class="card">
      <div class="card-head"><h2>Ожидаемые платежи</h2></div>
      <p v-if="!loading && !rows.length" class="muted">Платежей для сверки пока нет. Здесь появятся платежи, срок которых наступил по данным выписки. Будущие платежи видны на главной.</p>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>Что ждали</th><th>Когда</th><th class="r">Сколько</th><th>Статус</th><th class="r">Пришло</th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="(r.event_id ?? '') + r.planned_date + r.title">
              <td class="t-title">{{ r.title }}</td>
              <td class="num">{{ humanDate(r.planned_date) }}</td>
              <td class="r num">{{ money(r.planned_amount) }}</td>
              <td><span class="chip" :class="STATUS[r.status]?.cls">{{ STATUS[r.status]?.label ?? r.status }}</span></td>
              <td class="r num">{{ r.actual_amount ? money(r.actual_amount) : '—' }}<span v-if="r.actual_date" class="tiny"> · {{ humanDate(r.actual_date) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pf { display: grid; gap: 16px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
.head h1 { margin-bottom: 4px; }
.summary { font-weight: 600; margin-bottom: 8px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 15px; min-width: 560px; }
th { text-align: left; color: var(--ink-3); font-weight: 550; font-size: 13px; padding: 8px 12px; border-bottom: 1px solid var(--line); }
td { padding: 12px; border-bottom: 1px solid var(--line); }
tr:last-child td { border-bottom: 0; }
.r { text-align: right; }
.t-title { font-weight: 550; }
</style>
