<script setup lang="ts">
// Все модели рядом: гибрид, CatBoost, ансамбль для выбранной компании. Только просмотр.
import { echarts } from '../charts'
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type ModelsCompare } from '../api'
import { humanDate, rub } from '../format'

const route = useRoute()
const data = ref<ModelsCompare | null>(null)
const error = ref('')
const loading = ref(false)
const el = ref<HTMLDivElement>()
let chart: ReturnType<typeof echarts.init> | null = null
const COLORS: Record<string, string> = { hybrid: '#7d8a96', catboost: '#1f6feb', ensemble: '#8250df' }

async function load() {
  loading.value = true
  error.value = ''
  data.value = null
  try { data.value = await api.models(route.params.id as string) }
  catch (e) { error.value = e instanceof ApiError ? e.message : 'Не удалось получить оценки моделей' }
  loading.value = false
  await nextTick()
  draw()
}

function draw() {
  if (!el.value || !data.value) return
  chart ??= echarts.init(el.value)
  const ok = data.value.models.filter((m) => m.available && m.points)
  chart.setOption({
    animation: false,
    grid: { left: 8, right: 12, top: 48, bottom: 36, containLabel: true },
    legend: { data: ok.map((m) => m.title), top: 8, left: 0 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => rub(v) },
    xAxis: { type: 'category', data: ok[0]?.points?.map((p) => humanDate(p.date)) ?? [], axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', name: 'Остаток, ₽', axisLabel: { formatter: (v: number) => rub(v) } },
    series: [
      ...ok.map((m) => ({ name: m.title, type: 'line', showSymbol: false, lineStyle: { width: m.key === 'ensemble' ? 3 : 2, color: COLORS[m.key] },
                          itemStyle: { color: COLORS[m.key] }, data: m.points!.map((p) => p.p50) })),
      { name: '_порог', type: 'line', showSymbol: false, silent: true, tooltip: { show: false }, lineStyle: { type: 'dashed', color: '#d03b3b', width: 1 },
        data: (ok[0]?.points ?? []).map(() => data.value!.threshold), markLine: undefined },
    ],
  })
}
watch(() => route.params.id, load, { immediate: true })
onBeforeUnmount(() => chart?.dispose())
const pct = (p?: number) => (p === undefined ? '—' : `${Math.round(p * 100)}%`)
</script>

<template>
  <section>
    <h2>Модели рядом</h2>
    <p class="muted">Вероятность кассового разрыва в ближайшие 30 рабочих дней по разным моделям. Тревога — вероятность не ниже порога, подобранного проверкой на 150 компаниях.</p>
    <p v-if="loading">Считаем (первый запрос может занять до минуты)…</p>
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="data">
      <div class="cards">
        <article v-for="m in data.models" :key="m.key" class="card" :class="{ alert: m.alert }">
          <h3>{{ m.title }}</h3>
          <template v-if="m.available">
            <div class="big">{{ pct(m.probability) }}</div>
            <div>{{ m.alert ? 'Тревога' : 'Спокойно' }} · порог {{ pct(m.threshold) }}</div>
          </template>
          <p v-else class="muted">{{ m.reason }}</p>
        </article>
      </div>
      <div ref="el" class="chart" />
      <p class="muted">Линии — медианный прогноз остатка каждой моделью. Красный пунктир — неснижаемый остаток.</p>

      <p v-for="n in data.notes" :key="n" class="muted">{{ n }}</p>
    </template>
  </section>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 16px 0; }
.card { border: 1px solid #d0d7de; border-radius: 12px; padding: 14px 16px; background: #fff; }
.card.alert { border-color: #d03b3b; background: #fff5f5; }
.card h3 { margin: 0 0 6px; font-size: 15px; }
.big { font-size: 34px; font-weight: 700; }
.chart { height: 340px; margin-top: 8px; }
.tbl { border-collapse: collapse; width: 100%; max-width: 720px; }
.tbl th, .tbl td { padding: 8px 10px; border-bottom: 1px solid #e3e8e5; text-align: left; }
.muted { color: #5b6b63; }
.error { color: #d03b3b; }
</style>
