<script setup lang="ts">
// «Что если»: слева ползунки, справа обе линии на одном графике (стартуют из одной точки) и вывод словами.
// Пересчёт автоматический через полсекунды после изменения: модель не переобучается, это быстро.
import { RotateCcw } from 'lucide-vue-next'
import { computed, inject, onBeforeUnmount, reactive, ref, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type Dashboard, type ScenarioResult } from '../api'
import BalanceChart from '../components/BalanceChart.vue'
import { humanDate, percent, rub } from '../format'

const dashboard = inject<Ref<Dashboard | null>>('dashboard')!
const route = useRoute()
const blank = { client: '', weeks: 3, revenueDrop: 0, fixedUp: 0, expenseDate: '', expenseAmount: null as number | null }
const form = reactive({ ...blank })
const result = ref<ScenarioResult | null>(null)
const error = ref('')
const busy = ref(false)
const isEmpty = computed(() => !form.client && !form.revenueDrop && !form.fixedUp && !(form.expenseDate && form.expenseAmount))
let seq = 0

async function run() {
  const my = ++seq
  if (isEmpty.value) { result.value = null; error.value = ''; busy.value = false; return }
  error.value = ''
  busy.value = true
  try {
    const r = await api.scenario(route.params.id as string, {
      client_delays: form.client ? [{ counterparty_key: form.client, weeks: form.weeks }] : [],
      revenue_drop_pct: form.revenueDrop,
      fixed_cost_increase_pct: form.fixedUp,
      extra_expenses: form.expenseDate && form.expenseAmount && form.expenseAmount > 0
        ? [{ date: form.expenseDate, amount: String(form.expenseAmount), title: 'Внеплановый расход' }] : [],
    })
    if (my === seq) result.value = r
  } catch (e) {
    if (my === seq) error.value = e instanceof ApiError ? e.message : 'Не удалось посчитать сценарий'
  } finally {
    if (my === seq) busy.value = false
  }
}
let timer: number | undefined
watch(form, () => {
  ++seq
  window.clearTimeout(timer)
  result.value = null
  error.value = ''
  busy.value = false
  timer = window.setTimeout(run, 450)
}, { deep: true })
onBeforeUnmount(() => { window.clearTimeout(timer); ++seq })

function preset(kind: 'delay' | 'drop' | 'expense' | 'costs') {
  Object.assign(form, blank)
  const asOf = dashboard.value?.forecast.as_of
  if (kind === 'delay' && dashboard.value?.top_clients[0]) form.client = dashboard.value.top_clients[0].counterparty_key
  if (kind === 'drop') form.revenueDrop = 20
  if (kind === 'costs') form.fixedUp = 15
  if (kind === 'expense' && asOf) {
    const d = new Date(asOf)
    d.setDate(d.getDate() + 10)
    form.expenseDate = d.toISOString().slice(0, 10)
    form.expenseAmount = 300000
  }
}
const reset = () => Object.assign(form, blank)

const verdict = computed(() => {
  const d = result.value?.delta
  if (!d) return null
  if (!d.scenario_first_gap) return { tone: 'ok', text: 'Даже в этом случае денег хватит.' }
  const when = humanDate(d.scenario_first_gap)
  const shortfall = result.value!.scenario.alerts.find((a) => a.start === d.scenario_first_gap)?.shortfall
  return { tone: 'risk', text: `В этом сценарии ${when} не хватит ${shortfall ? rub(shortfall) : 'денег'}.` }
})
const clientName = (key: string) => dashboard.value?.top_clients.find((c) => c.counterparty_key === key)?.name ?? ''
</script>

<template>
  <div v-if="dashboard" class="sc">
    <div class="intro">
      <h1>Сценарии «что если»</h1>
      <p class="muted small">Задайте неприятное событие и сравните с обычным прогнозом. Ваши данные не меняются.</p>
    </div>

    <div class="layout">
      <form class="card controls" @submit.prevent="run">
        <p class="label">Быстрые сценарии</p>
        <div class="presets">
          <button type="button" class="btn btn-sm" :disabled="!dashboard.top_clients.length" @click="preset('delay')">Крупный клиент задержит оплату</button>
          <button type="button" class="btn btn-sm" @click="preset('drop')">Выручка −20%</button>
          <button type="button" class="btn btn-sm" @click="preset('expense')">Ремонт за 300 тыс.</button>
          <button type="button" class="btn btn-sm" @click="preset('costs')">Аренда и закупки +15%</button>
        </div>

        <label class="field">Клиент заплатит позже
          <select v-model="form.client">
            <option value="">Никто</option>
            <option v-for="c in dashboard.top_clients" :key="c.counterparty_key" :value="c.counterparty_key">
              {{ c.name }} · {{ percent(c.share) }} поступлений
            </option>
          </select>
        </label>
        <label v-if="form.client" class="field">На сколько недель позже: <b class="num">{{ form.weeks }}</b>
          <input v-model.number="form.weeks" type="range" min="1" max="8" />
        </label>
        <label class="field">Выручка упадёт на <b class="num">{{ form.revenueDrop }}%</b>
          <input v-model.number="form.revenueDrop" type="range" min="0" max="50" step="5" />
        </label>
        <label class="field">Постоянные расходы вырастут на <b class="num">{{ form.fixedUp }}%</b>
          <span class="hint">Аренда, закупки, коммунальные, связь</span>
          <input v-model.number="form.fixedUp" type="range" min="0" max="50" step="5" />
        </label>
        <fieldset class="field">
          <legend>Внеплановый расход</legend>
          <div class="expense">
            <input v-model="form.expenseDate" type="date" :min="dashboard.forecast.as_of" aria-label="Дата расхода" />
            <input v-model.number="form.expenseAmount" type="number" inputmode="decimal" min="0" placeholder="Сумма, ₽" aria-label="Сумма расхода" />
          </div>
        </fieldset>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="isEmpty" @click="reset"><RotateCcw />Сбросить</button>
      </form>

      <section class="card result" :aria-busy="busy">
        <template v-if="!result">
          <h2 class="placeholder">Выберите сценарий слева</h2>
          <p class="muted">Покажем, как изменится остаток и появится ли нехватка денег.</p>
          <BalanceChart :history="dashboard.history" :points="dashboard.forecast.points" :threshold="dashboard.forecast.threshold" />
        </template>
        <template v-else>
          <p class="verdict" :class="verdict?.tone">{{ verdict?.text }}</p>
          <p v-if="form.client" class="small muted">{{ clientName(form.client) }} платит на {{ form.weeks }} нед. позже.</p>
          <dl class="delta">
            <div><dt>Первая нехватка</dt>
              <dd><span class="was">{{ result.delta.base_first_gap ? humanDate(result.delta.base_first_gap) : 'нет' }}</span> →
                <b>{{ result.delta.scenario_first_gap ? humanDate(result.delta.scenario_first_gap) : 'нет' }}</b></dd></div>
            <div><dt>Минимум остатка</dt>
              <dd class="num"><span class="was">{{ rub(result.delta.base_min_p50) }}</span> → <b>{{ rub(result.delta.scenario_min_p50) }}</b></dd></div>
            <div><dt>Дополнительно не хватит</dt>
              <dd class="num"><b>{{ result.delta.extra_shortfall > 0 ? rub(result.delta.extra_shortfall) : '0 ₽' }}</b></dd></div>
          </dl>
          <div :class="{ dim: busy }">
            <BalanceChart :history="dashboard.history" :points="result.base.points" :threshold="result.base.threshold"
                          :compare="result.scenario.points" :alerts="result.scenario.alerts" compare-label="Если так случится" />
          </div>
        </template>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.sc { display: grid; gap: 16px; }
.intro h1 { margin-bottom: 4px; }
.layout { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 20px; align-items: start; }
.controls { position: sticky; top: 84px; }
.label { font-size: 13px; font-weight: 600; color: var(--ink-2); margin-bottom: 8px; }
.presets { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 20px; }
legend { font-size: 14px; font-weight: 550; margin-bottom: 6px; }
.expense { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.result { display: grid; gap: 12px; min-width: 0; }
.placeholder { font-size: 20px; }
.verdict { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2; }
.verdict.ok { color: var(--brand); }
.verdict.risk { color: var(--risk); }
.delta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 0; padding: 12px 0; border-block: 1px solid var(--line); }
.delta dt { font-size: 13px; color: var(--ink-3); }
.delta dd { margin: 2px 0 0; }
.was { color: var(--ink-3); }
.dim { opacity: 0.55; transition: opacity 150ms; }
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
  .controls { position: static; }
  .delta { grid-template-columns: 1fr; }
}
</style>
