<script setup lang="ts">
// «Что если»: настройки слева, результат справа — две линии на одном графике и разница словами.
import { computed, inject, reactive, ref, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type Dashboard, type ScenarioResult } from '../api'
import BalanceChart from '../components/BalanceChart.vue'
import { humanDate, rub } from '../format'

const dashboard = inject<Ref<Dashboard | null>>('dashboard')!
const route = useRoute()
const form = reactive({ client: '', weeks: 3, revenueDrop: 0, fixedUp: 0, expenseDate: '', expenseAmount: 0 })
const result = ref<ScenarioResult | null>(null)
const error = ref('')
const busy = ref(false)

function preset(kind: 'delay' | 'drop') {
  reset()
  if (kind === 'delay' && dashboard.value?.top_clients[0]) form.client = dashboard.value.top_clients[0].counterparty_key
  if (kind === 'drop') form.revenueDrop = 20
  run()
}

function reset() {
  Object.assign(form, { client: '', weeks: 3, revenueDrop: 0, fixedUp: 0, expenseDate: '', expenseAmount: 0 })
  result.value = null
}

async function run() {
  error.value = ''
  busy.value = true
  try {
    result.value = await api.scenario(route.params.id as string, {
      client_delays: form.client ? [{ counterparty_key: form.client, weeks: form.weeks }] : [],
      revenue_drop_pct: form.revenueDrop,
      fixed_cost_increase_pct: form.fixedUp,
      extra_expenses: form.expenseDate && form.expenseAmount > 0
        ? [{ date: form.expenseDate, amount: String(form.expenseAmount), title: 'Внеплановый расход' }] : [],
    })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось посчитать сценарий'
  } finally {
    busy.value = false
  }
}

const verdict = computed(() => {
  const d = result.value?.delta
  if (!d) return ''
  if (!d.scenario_first_gap) return 'Даже в этом случае денег хватит.'
  const when = humanDate(d.scenario_first_gap)
  const was = d.base_first_gap ? ` вместо ${humanDate(d.base_first_gap)}` : ''
  const more = d.extra_shortfall > 0 ? `, не хватит ещё ${rub(d.extra_shortfall)}` : ''
  return `Нехватка начнётся ${when}${was}${more}.`
})
</script>

<template>
  <div v-if="dashboard" class="layout">
    <form class="card controls" @submit.prevent="run">
      <div class="presets">
        <button type="button" class="btn" @click="preset('delay')">Клиент задержит оплату на 3 недели</button>
        <button type="button" class="btn" @click="preset('drop')">Выручка −20%</button>
      </div>
      <label class="field">Крупный клиент заплатит позже
        <select v-model="form.client">
          <option value="">— никто —</option>
          <option v-for="c in dashboard.top_clients" :key="c.counterparty_key" :value="c.counterparty_key">
            {{ c.name }} ({{ Math.round(c.share * 100) }}% поступлений)
          </option>
        </select>
      </label>
      <label v-if="form.client" class="field">На сколько недель: {{ form.weeks }}
        <input v-model.number="form.weeks" type="range" min="1" max="8" />
      </label>
      <label class="field">Выручка упадёт на {{ form.revenueDrop }}%
        <input v-model.number="form.revenueDrop" type="range" min="0" max="50" step="5" />
      </label>
      <label class="field">Постоянные расходы вырастут на {{ form.fixedUp }}%
        <input v-model.number="form.fixedUp" type="range" min="0" max="50" step="5" />
      </label>
      <fieldset class="field">
        <legend>Внеплановый расход</legend>
        <input v-model="form.expenseDate" type="date" :min="dashboard.forecast.as_of" aria-label="Дата расхода" />
        <input v-model.number="form.expenseAmount" type="number" min="0" placeholder="Сумма, ₽" aria-label="Сумма расхода" />
      </fieldset>
      <div class="row">
        <button type="button" class="btn" @click="reset">Сбросить</button>
        <button class="btn btn-primary" :disabled="busy">{{ busy ? 'Считаем…' : 'Посчитать' }}</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </form>

    <section class="card">
      <p v-if="!result" class="muted">Задайте неприятное событие — покажем, как изменится остаток и появится ли нехватка.</p>
      <template v-else>
        <h2 class="verdict">{{ verdict }}</h2>
        <BalanceChart :history="dashboard.history" :points="result.base.points" :threshold="result.base.threshold"
                      :compare="result.scenario.points" />
        <p class="muted">Сплошная линия — как сейчас, пунктир — если так случится.</p>
      </template>
    </section>
  </div>
</template>

<style scoped>
.layout { display: grid; gap: 20px; grid-template-columns: minmax(280px, 1fr) minmax(0, 2fr); }
.presets { display: grid; gap: 8px; margin-bottom: 16px; }
fieldset { border: 0; padding: 0; margin: 0 0 12px; }
legend { margin-bottom: 4px; }
.row { display: flex; gap: 8px; justify-content: flex-end; }
.verdict { font-size: 22px; margin-bottom: 12px; }
.muted { color: var(--muted); }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
</style>
