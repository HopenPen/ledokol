<script setup lang="ts">
// Главная: ответ одной фразой → три цифры → график → разрывы с причинами и действиями → ближайшие платежи.
import { CalendarPlus } from 'lucide-vue-next'
import { computed, inject, ref, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type AccountBalance, type Dashboard, type Forecast } from '../api'
import AddEventModal from '../components/AddEventModal.vue'
import AlertCard from '../components/AlertCard.vue'
import BalanceChart from '../components/BalanceChart.vue'
import MissedPayments from '../components/MissedPayments.vue'
import { BALANCE_SOURCE, chanceWords, daysBetween, humanDate, money, percent, plural, rub, signed, SOURCE_LABEL } from '../format'

const dashboard = inject<Ref<Dashboard | null>>('dashboard')!
const balance = inject<Ref<AccountBalance | null>>('balance')!
const emptyHistory = inject<Ref<boolean>>('emptyHistory')!
const reload = inject<() => Promise<void>>('reload')!
const toast = inject<(t: string) => void>('toast')!
const route = useRoute()
const adding = ref(false)
const showAll = ref(false)

// 30 дней приходят с дашбордом (этот прогноз сохраняется для план-факта); 60 и 90 догружаем только для показа.
const horizon = ref(30)
const longer = ref<Forecast | null>(null)
const loadingLonger = ref(false)
const forecastError = ref('')
watch([horizon, dashboard], async (_, __, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  longer.value = null
  forecastError.value = ''
  loadingLonger.value = false
  if (horizon.value === 30 || !dashboard.value) return
  loadingLonger.value = true
  try {
    const result = await api.forecast(route.params.id as string, horizon.value)
    if (active) longer.value = result
  } catch (e) {
    if (active) forecastError.value = e instanceof ApiError ? e.message : 'Не удалось загрузить прогноз'
  } finally { if (active) loadingLonger.value = false }
})
const f = computed(() => longer.value ?? dashboard.value?.forecast ?? null)

const tone = computed(() => {
  const a = f.value?.alerts.find((x) => !x.worst_case)
  if (!f.value?.alerts.length) return 'ok'
  return a && a.probability >= 0.5 ? 'risk' : 'warn'
})

/** Запас хода: сколько календарных дней до первой вероятной нехватки. */
const runway = computed(() => {
  if (!f.value) return null
  const gap = f.value.alerts.find((a) => !a.worst_case)
  if (!gap) return null
  return { days: daysBetween(f.value.as_of, gap.start), date: gap.start }
})
const minPoint = computed(() => f.value?.points.reduce((m, p) => (p.p50 < m.p50 ? p : m), f.value.points[0]) ?? null)
const upcoming = computed(() => (f.value?.events ?? []).slice(0, showAll.value ? 60 : 8))

async function onSaved() {
  adding.value = false
  await reload()
  toast('Платёж добавлен, прогноз пересчитан')
}
</script>

<template>
  <div v-if="!dashboard && !emptyHistory" class="loading" aria-busy="true">
    <div class="skeleton" style="height: 44px; width: 60%" />
    <div class="skeleton" style="height: 96px" />
    <div class="skeleton" style="height: 360px" />
  </div>

  <div v-else-if="f && dashboard" class="home">
    <section class="answer" :class="tone">
      <h1>{{ f.headline }}</h1>
      <p v-if="f.low_history" class="note">Истории пока мало, поэтому прогноз приблизительный.</p>
      <p v-for="w in f.warnings" :key="w" class="note">{{ w }}</p>
    </section>

    <section class="kpis" aria-label="Главные цифры">
      <div class="kpi">
        <p class="k-label">На счёте сейчас</p>
        <p class="k-value num">{{ money(f.last_balance) }}</p>
        <p class="tiny">{{ balance ? BALANCE_SOURCE[balance.source] : 'Остаток' }} · {{ humanDate(f.as_of, true) }}</p>
      </div>
      <div class="kpi" :class="{ 'kpi-risk': runway && runway.days <= 14 }">
        <p class="k-label">Запас хода</p>
        <p v-if="runway" class="k-value num">{{ runway.days }} {{ plural(runway.days, 'день', 'дня', 'дней') }}</p>
        <p v-else class="k-value">весь прогноз</p>
        <p class="tiny">{{ runway ? `до ${humanDate(runway.date)}` : `нехватки не видно на ${f.points.length} рабочих дней` }}</p>
      </div>
      <div v-if="minPoint" class="kpi">
        <p class="k-label">Минимум в прогнозе</p>
        <p class="k-value num" :class="{ 'v-risk': minPoint.p50 < f.threshold }">{{ rub(minPoint.p50) }}</p>
        <p class="tiny">{{ humanDate(minPoint.date) }}</p>
      </div>
    </section>

    <MissedPayments :company-id="route.params.id as string" :events="dashboard.missed_payments" :min-date="f.as_of" @changed="reload" />

    <div class="grid">
      <section class="card chart-card">
        <div class="card-head">
          <h2>Остаток на счёте</h2>
          <div class="seg" role="group" aria-label="Горизонт прогноза">
            <button v-for="h in [30, 60, 90]" :key="h" :aria-pressed="horizon === h" @click="horizon = h">{{ h }} дней</button>
          </div>
        </div>
        <p v-if="loadingLonger" class="small muted" role="status">Загружаем прогноз. Пока показаны 30 рабочих дней.</p>
        <p v-if="forecastError" class="error" role="alert">{{ forecastError }} Показан прогноз на 30 рабочих дней.</p>
        <div :class="{ dim: loadingLonger }">
          <BalanceChart :history="dashboard.history" :points="f.points" :threshold="f.threshold" :events="f.events" :alerts="f.alerts" />
        </div>
      </section>

      <section class="side" aria-labelledby="alerts-title">
        <h2 id="alerts-title" class="side-title">Предупреждения</h2>
        <div v-if="!f.alerts.length" class="ok-plate">
          <p><b>Нехватки денег не видно</b></p>
          <p class="small">на ближайшие {{ f.points.length }} рабочих дней с учётом регулярных платежей и налогов.</p>
        </div>
        <AlertCard v-for="(a, i) in f.alerts" :key="a.start" :alert="a" :start-open="i === 0" />
      </section>
    </div>

    <section class="card">
      <div class="card-head">
        <div>
          <h2>Ближайшие платежи</h2>
          <p class="small muted">Всё, что сервис уже знает о будущих деньгах. У каждого платежа указан источник.</p>
        </div>
        <button class="btn" @click="adding = true"><CalendarPlus />Добавить ожидаемый платёж</button>
      </div>
      <p v-if="!upcoming.length" class="muted">Будущих платежей пока нет.</p>
      <ul class="events">
        <li v-for="e in upcoming" :key="e.date + e.title + e.amount">
          <span class="e-date num">{{ humanDate(e.date) }}</span>
          <span class="e-title">{{ e.title }}</span>
          <span class="e-meta">
            <span class="src" :class="`src-${e.source}`">{{ SOURCE_LABEL[e.source] ?? e.source }}</span>
            <span v-if="e.probability < 0.995" class="tiny">{{ chanceWords(e.probability) }}, {{ percent(e.probability) }}</span>
          </span>
          <span class="amount e-amt" :class="e.direction">{{ signed(e.amount, e.direction) }}</span>
        </li>
      </ul>
      <button v-if="f.events.length > 8" class="btn btn-ghost more" @click="showAll = !showAll">
        {{ showAll ? 'Свернуть' : `Показать все (${f.events.length})` }}
      </button>
    </section>

    <AddEventModal v-if="adding" :company-id="route.params.id as string" :min-date="f.as_of" @close="adding = false" @saved="onSaved" />
  </div>
</template>

<style scoped>
.loading { display: grid; gap: 16px; }
.home { display: grid; gap: 20px; }
.answer { padding-left: 20px; border-left: 4px solid var(--brand); }
.answer.warn { border-left-color: var(--warn); }
.answer.risk { border-left-color: var(--risk); }
.answer h1 { font-size: clamp(26px, 3.4vw, 38px); line-height: 1.15; max-width: 28ch; font-weight: 700; letter-spacing: -0.025em; }
.note { color: var(--warn); margin-top: 8px; font-size: 14px; }

.kpis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
.kpi { padding: 16px 20px; display: grid; gap: 2px; }
.kpi + .kpi { border-left: 1px solid var(--line); }
.k-label { font-size: 14px; color: var(--ink-2); font-weight: 550; }
.k-value { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2; }
.kpi-risk .k-value, .v-risk { color: var(--risk); }

.grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 20px; align-items: start; }
.chart-card { min-width: 0; }
.dim { opacity: 0.5; transition: opacity 150ms; }
.side { display: grid; gap: 12px; }
.side-title { font-size: 16px; color: var(--ink-2); }
.ok-plate { background: var(--brand-soft); color: var(--brand); padding: 16px 20px; border-radius: var(--radius); display: grid; gap: 4px; }

.events { list-style: none; padding: 0; margin: 0; }
.events li {
  display: grid; grid-template-columns: 96px minmax(0, 1fr) auto; grid-template-areas: 'd t a' 'd m a';
  gap: 2px 16px; padding: 12px 0; border-top: 1px solid var(--line); align-items: center;
}
.e-date { grid-area: d; color: var(--ink-2); font-size: 14px; align-self: start; padding-top: 2px; }
.e-title { grid-area: t; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e-meta { grid-area: m; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.e-amt { grid-area: a; text-align: right; font-weight: 600; white-space: nowrap; }
.more { margin-top: 8px; }

@media (max-width: 1080px) { .grid { grid-template-columns: 1fr; } }
@media (max-width: 640px) {
  .kpis { grid-template-columns: 1fr; }
  .kpi + .kpi { border-left: 0; border-top: 1px solid var(--line); }
  .events li { grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: 'd a' 't a' 'm m'; }
}
</style>
