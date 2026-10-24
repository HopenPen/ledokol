<script setup lang="ts">
// Остаток: факт (серый) → «сегодня» → прогноз (зелёная линия) с коридором обычного разброса (10–90%).
// Ниже порога — красная зона. Начало каждой нехватки отмечено точкой. Сценарий — вторая, пунктирная линия.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Alert, FutureEvent, Point } from '../api'
import { echarts, tokens } from '../charts'
import { humanDate, money, percent, rub, shortDate, SOURCE_LABEL } from '../format'

const props = withDefaults(defineProps<{
  history: { date: string; balance: number }[]
  points: Point[]
  threshold: number
  events?: FutureEvent[]
  alerts?: Alert[]
  compare?: Point[]
  compareLabel?: string
  height?: number
  historyDays?: number
}>(), { events: () => [], alerts: () => [], compareLabel: 'Если так случится', height: 340, historyDays: 45 })

const el = ref<HTMLDivElement>()
let chart: ReturnType<typeof echarts.init> | null = null

function escape(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

function render() {
  if (!chart) return
  const t = tokens()
  const narrow = (el.value?.clientWidth ?? 800) < 520
  const hist = props.history.slice(-props.historyDays)
  const last = hist.at(-1)
  const joint = last ? [[last.date, last.balance]] : []      // прогноз продолжает факт, без разрыва линии
  const p50 = [...joint, ...props.points.map((p) => [p.date, p.p50])]
  const lower = [...joint, ...props.points.map((p) => [p.date, p.p10])]
  const band = [...(last ? [[last.date, 0]] : []), ...props.points.map((p) => [p.date, p.p90 - p.p10])]
  const values = [...hist.map((h) => h.balance), ...props.points.flatMap((p) => [p.p10, p.p90]),
    ...(props.compare ?? []).map((p) => p.p50), props.threshold]
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const pad = (hi - lo) * 0.08 || 1
  const yMin = lo - pad
  const eventsByDay = new Map<string, FutureEvent[]>()
  for (const e of props.events) eventsByDay.set(e.date, [...(eventsByDay.get(e.date) ?? []), e])

  chart.setOption({
    animationDuration: 500,
    textStyle: { fontFamily: t.font },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis', confine: true, backgroundColor: t.surface, borderColor: t.line, padding: [10, 12],
      textStyle: { color: t.ink, fontSize: 13 },
      axisPointer: { type: 'line', lineStyle: { color: t.ink3, type: 'dashed' } },
      formatter: (items: { value: [string, number] }[]) => {
        const d = items[0]?.value[0]
        if (!d) return ''
        const p = props.points.find((x) => x.date === d)
        const h = hist.find((x) => x.date === d)
        const c = props.compare?.find((x) => x.date === d)
        const rows = [`<b>${humanDate(d, true)}</b>`]
        if (h && !p) rows.push(`Было на счёте: <b>${money(h.balance)}</b>`)
        if (p) {
          rows.push(`Прогноз: <b>${money(Math.round(p.p50))}</b>`)
          rows.push(`<span style="color:${t.ink2}">Обычный разброс: ${rub(p.p10)} … ${rub(p.p90)}</span>`)
          if (p.prob_below >= 0.05) rows.push(`<span style="color:${t.risk}">Шанс нехватки: ${percent(p.prob_below)}</span>`)
        }
        if (c) rows.push(`${escape(props.compareLabel)}: <b>${money(Math.round(c.p50))}</b>`)
        for (const e of (eventsByDay.get(d) ?? []).slice(0, 4)) {
          rows.push(`<span style="color:${t.ink2}">${e.direction === 'in' ? '+' : '−'}${rub(e.amount)} · ${escape(e.title)} · ${SOURCE_LABEL[e.source] ?? e.source}</span>`)
        }
        return rows.join('<br/>')
      },
    },
    xAxis: {
      type: 'time', splitNumber: narrow ? 3 : 6, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false },
      axisLabel: { color: t.ink3, hideOverlap: true, formatter: (v: number) => shortDate(new Date(v).toISOString()) },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value', min: yMin, scale: true, axisLabel: { color: t.ink3, formatter: (v: number) => rub(v) },
      splitLine: { lineStyle: { color: t.line, type: 'dashed' } },
    },
    series: [
      { name: '_low', type: 'line', data: lower, stack: 'band', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 }, silent: true },
      { name: '_band', type: 'line', data: band, stack: 'band', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 },
        areaStyle: { color: t.band, opacity: 0.85 }, silent: true },
      { name: 'Было', type: 'line', data: hist.map((h) => [h.date, h.balance]), symbol: 'none', lineStyle: { color: t.ink3, width: 2 },
        markLine: last ? { silent: true, symbol: 'none', data: [{ xAxis: last.date }], lineStyle: { color: t.ink2, type: 'solid', width: 1 },
                            label: { formatter: 'сегодня', position: 'insideEndTop', color: t.ink2, fontSize: 12 } } : undefined },
      { name: 'Прогноз', type: 'line', data: p50, symbol: 'none', lineStyle: { color: t.brand, width: 2.5 }, z: 4,
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: props.threshold }], lineStyle: { color: t.risk, type: 'dashed', width: 1.5 },
                    label: { formatter: props.threshold > 0 ? 'неснижаемый остаток' : 'ноль', position: 'insideStartTop', color: t.risk, fontSize: 12 } },
        markArea: { silent: true, itemStyle: { color: t.riskSoft, opacity: 0.7 }, data: [[{ yAxis: yMin }, { yAxis: props.threshold }]] } },
      ...(props.compare ? [{
        name: props.compareLabel, type: 'line', data: [...joint, ...props.compare.map((p) => [p.date, p.p50])], symbol: 'none', z: 5,
        lineStyle: { color: t.risk, width: 2.5, type: 'dashed' },
      }] : []),
      { name: '_gaps', type: 'scatter', z: 6, symbolSize: 11, itemStyle: { color: t.risk, borderColor: t.surface, borderWidth: 2 },
        data: props.alerts.map((a, i) => {
          const p = props.points.find((x) => x.date === a.start)
          // Подпись только у первой нехватки: соседние даты иначе налезают друг на друга.
          return p ? { value: [a.start, p.p50], label: { show: i === 0 } } : null
        }).filter(Boolean),
        label: { position: 'top', color: t.risk, fontWeight: 600, fontSize: 12,
                 formatter: (x: { value: [string, number] }) => shortDate(x.value[0]) } },
    ],
  }, true)
}

const onResize = () => chart?.resize()
let observer: ResizeObserver | null = null
onMounted(() => {
  chart = echarts.init(el.value!)
  render()
  observer = new ResizeObserver(onResize)
  observer.observe(el.value!)
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
watch(() => [props.points, props.compare, props.history, props.threshold, props.alerts, props.events], render, { deep: true })
</script>

<template>
  <div class="wrap">
    <div ref="el" class="chart" :style="{ height: `${height}px` }" role="img"
         :aria-label="`График остатка: факт и прогноз на ${points.length} рабочих дней`" />
    <ul class="legend" aria-hidden="true">
      <li><i class="k-hist" />было</li>
      <li><i class="k-fc" />прогноз</li>
      <li><i class="k-band" />обычный разброс</li>
      <li v-if="compare"><i class="k-cmp" />{{ compareLabel.toLowerCase() }}</li>
      <li><i class="k-th" />{{ threshold > 0 ? 'неснижаемый остаток' : 'ноль' }}</li>
    </ul>
  </div>
</template>

<style scoped>
.chart { width: 100%; }
.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 0; margin: 8px 0 0; font-size: 13px; color: var(--ink-2); }
.legend li { display: inline-flex; align-items: center; gap: 6px; }
.legend i { display: inline-block; width: 16px; height: 0; border-top: 2.5px solid; }
.k-hist { border-color: var(--ink-3) !important; }
.k-fc { border-color: var(--brand) !important; }
.k-band { height: 10px !important; border: 0 !important; background: var(--brand-band); border-radius: 2px; }
.k-cmp { border-color: var(--risk) !important; border-top-style: dashed !important; }
.k-th { border-color: var(--risk) !important; border-top-style: dashed !important; border-top-width: 1.5px !important; }
</style>
