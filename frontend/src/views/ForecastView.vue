<script setup lang="ts">
// Главная: заголовок → три цифры → график и вывод → разрывы с причинами и действиями → ближайшие платежи.
import { CalendarPlus } from 'lucide-vue-next'
import { computed, inject, ref, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, type AccountBalance, type Dashboard, type ModelsCompare, type Point } from '../api'
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

// Основной прогноз на 30 рабочих дней приходит с дашбордом и сохраняется для план-факта.
const f = computed(() => dashboard.value?.forecast ?? null)
const firstGap = computed(() => f.value?.alerts[0] ?? null)

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

// Выбор модели для графика: гибрид (основной, из него заголовок и предупреждения), CatBoost и ансамбль.
const compareData = ref<ModelsCompare | null>(null)
const compareError = ref('')
const picked = ref('hybrid')
const userPicked = ref(false)
const overlay = ref('')
const OPTIONS = [{ key: 'hybrid', label: 'Гибрид' }, { key: 'catboost', label: 'CatBoost' },
                 { key: 'ensemble', label: 'Ансамбль' }]
async function loadCompare() {
  compareError.value = ''
  try {
    compareData.value = await api.models(route.params.id as string)
    if (!userPicked.value && compareData.value.models.find((m) => m.key === 'ensemble')?.available) picked.value = 'ensemble'
  } catch { compareError.value = 'Не удалось получить прогнозы моделей' }
}
watch(dashboard, () => { compareData.value = null; if (dashboard.value) loadCompare() }, { immediate: true })
function pick(key: string) { userPicked.value = true; picked.value = key; if (overlay.value === key) overlay.value = '' }
function pointsOf(key: string): Point[] | null {
  if (key === 'hybrid') return null
  return compareData.value?.models.find((m) => m.key === key && m.available)?.points ?? null
}
const shownPoints = computed(() => pointsOf(picked.value) ?? f.value?.points ?? [])
const overlayPoints = computed(() => (overlay.value ? (overlay.value === 'hybrid' ? f.value?.points : pointsOf(overlay.value)) : undefined) ?? undefined)
const labelOf = (key: string) => OPTIONS.find((o) => o.key === key)?.label ?? key

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
    <h1 class="page-title">Планирование движения денежных средств</h1>
    <section class="kpis" aria-label="Главные цифры">
      <div class="kpi">
        <p class="k-label">На счёте сейчас</p>
        <p class="k-value num">{{ money(f.last_balance) }}</p>
        <p class="tiny">{{ balance ? BALANCE_SOURCE[balance.source] : 'Остаток' }} · {{ humanDate(f.as_of, true) }}</p>
      </div>
      <div class="kpi" :class="{ 'kpi-risk': runway && runway.days <= 14 }">
        <p class="k-label">Запас</p>
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
          <span class="small muted">Прогноз на {{ f.points.length }} рабочих дней</span>
        </div>
        <div class="models" role="group" aria-label="Какой моделью строить прогноз">
          <span class="small muted">Прогноз:</span>
          <button v-for="o in OPTIONS" :key="o.key" class="mbtn" :class="{ on: picked === o.key }" :aria-pressed="picked === o.key" @click="pick(o.key)">{{ o.label }}</button>
          <span class="small muted">Сравнить с:</span>
          <select v-model="overlay" aria-label="Сравнить с моделью">
            <option value="">ничем</option>
            <option v-for="o in OPTIONS.filter((x) => x.key !== picked)" :key="o.key" :value="o.key">{{ o.label }}</option>
          </select>
        </div>
        <BalanceChart :history="dashboard.history" :points="shownPoints" :threshold="f.threshold" :events="f.events" :alerts="f.alerts"
                      :compare="overlayPoints" :compare-label="overlay ? labelOf(overlay) : undefined" />
        <p v-if="picked !== 'hybrid'" class="small muted">Вывод ниже и предупреждения считает основной гибрид. На графике: {{ labelOf(picked) }}.</p>
        <p v-if="compareError" class="small muted">{{ compareError }}</p>
        <section class="answer" :class="tone">
          <h2>{{ firstGap ? `Дальше кассовый разрыв в ${money(firstGap.shortfall)}` : 'Кассового разрыва в прогнозе не видно' }}</h2>
          <p v-if="firstGap" class="small muted">
            {{ `С ${humanDate(firstGap.start)} · ${chanceWords(firstGap.probability)} (${percent(firstGap.probability)})${firstGap.worst_case ? ', только в плохом сценарии' : ''}.` }}
          </p>
          <p v-if="f.last_balance < f.threshold" class="note">{{ f.headline }}</p>
          <p v-if="f.low_history" class="note">Истории пока мало, поэтому прогноз приблизительный.</p>
          <p v-for="w in f.warnings" :key="w" class="note">{{ w }}</p>
        </section>
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
.models { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 4px 0 8px; }
.mbtn { padding: 4px 12px; font-size: 13px; border: 1px solid var(--line, #d0d7de); border-radius: 8px; background: #fff; cursor: pointer; }
.mbtn.on { border-color: var(--brand); color: var(--brand); font-weight: 600; }
.models select { padding: 5px 8px; border-radius: 8px; border: 1px solid var(--line, #d0d7de); }
.loading { display: grid; gap: 16px; }
.home { display: grid; gap: 20px; }
.answer { margin-top: 20px; padding-left: 20px; border-left: 4px solid var(--brand); }
.answer.warn { border-left-color: var(--warn); }
.answer.risk { border-left-color: var(--risk); }
.page-title, .answer h2 { font-size: clamp(26px, 3.4vw, 38px); line-height: 1.15; font-weight: 700; letter-spacing: -0.025em; }
.answer > .small { margin-top: 8px; }
.note { color: var(--warn); margin-top: 8px; font-size: 14px; }

.kpis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
.kpi { padding: 16px 20px; display: grid; gap: 2px; }
.kpi + .kpi { border-left: 1px solid var(--line); }
.k-label { font-size: 14px; color: var(--ink-2); font-weight: 550; }
.k-value { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2; }
.kpi-risk .k-value, .v-risk { color: var(--risk); }

.grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 20px; align-items: start; }
.chart-card { min-width: 0; }
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
