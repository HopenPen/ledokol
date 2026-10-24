<script setup lang="ts">
// График остатка: факт + прогноз (синий) + «обычный разброс» P10–P90 и порог (серый пунктир).
// Сравнение сценария — вторая линия (оранжевая). Одна ось Y, без двойных шкал.
import { echarts } from '../charts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Point } from '../api'
import { humanDate, rub } from '../format'

const props = defineProps<{
  history: { date: string; balance: number }[]
  points: Point[]
  threshold: number
  compare?: Point[]
  compareLabel?: string
  forecastLabel?: string
}>()

const el = ref<HTMLDivElement>()
let chart: ReturnType<typeof echarts.init> | null = null

function render() {
  if (!chart) return
  const hist = props.history.map((h) => [h.date, h.balance])
  const last = props.history.at(-1)
  const joint = last ? [[last.date, last.balance]] : []   // прогноз начинается от последнего факта — без разрыва линии
  const p50 = [...joint, ...props.points.map((p) => [p.date, p.p50])]
  const lower = props.points.map((p) => [p.date, p.p10])
  const band = props.points.map((p) => [p.date, p.p90 - p.p10])
  chart.setOption({
    animation: false,
    grid: { left: 8, right: 12, top: 48, bottom: 36, containLabel: true },
    legend: { data: ['Было', props.forecastLabel ?? 'Прогноз', ...(props.compare ? [props.compareLabel ?? 'Если так случится'] : [])],
              top: 8, left: 0, textStyle: { color: '#4a5d55' } },
    tooltip: {
      trigger: 'axis',
      formatter: (items: { seriesName: string; value: [string, number] }[]) => {
        const d = items[0]?.value[0]
        const p = props.points.find((x) => x.date === d)
        const compared = props.compare?.find((x) => x.date === d)
        const rows = items.filter((i) => !i.seriesName.startsWith('_')).map((i) => `${i.seriesName}: ${rub(i.value[1])}`)
        if (p && compared) {
          rows.push(`Риск (${props.forecastLabel ?? 'прогноз'}): ${Math.round(p.prob_below * 100)}%`)
          rows.push(`Риск (${props.compareLabel ?? 'сценарий'}): ${Math.round(compared.prob_below * 100)}%`)
        } else if (p && p.prob_below > 0.05) rows.push(`Шанс нехватки: ${Math.round(p.prob_below * 100)}%`)
        return [humanDate(d), ...rows].join('<br/>')
      },
    },
    xAxis: { type: 'time', name: 'Дата', nameLocation: 'middle', nameGap: 28,
             axisLabel: { hideOverlap: true, formatter: (v: number) => humanDate(new Date(v).toISOString().slice(0, 10)) } },
    yAxis: { type: 'value', name: 'Остаток, ₽', nameGap: 18, axisLabel: { formatter: (v: number) => rub(v) }, splitLine: { lineStyle: { color: '#dde6e1' } } },
    series: [
      { name: '_low', type: 'line', data: lower, stack: 'band', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 } },
      { name: '_band', type: 'line', data: band, stack: 'band', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(42, 120, 214, 0.18)' } },
      { name: 'Было', type: 'line', data: hist, symbol: 'none', itemStyle: { color: '#13241d' }, lineStyle: { color: '#13241d', width: 2 } },
      { name: props.forecastLabel ?? 'Прогноз', type: 'line', data: p50, symbol: 'none', itemStyle: { color: '#2a78d6' }, lineStyle: { color: '#2a78d6', width: 2 },
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: props.threshold }],
                    lineStyle: { color: '#4a5d55', type: 'dashed' }, label: { formatter: 'порог', position: 'insideStartTop', color: '#4a5d55' } } },
      ...(props.compare ? [{ name: props.compareLabel ?? 'Если так случится', type: 'line', data: [...joint, ...props.compare.map((p) => [p.date, p.p50])],
                             symbol: 'none', itemStyle: { color: '#eb6834' }, lineStyle: { color: '#eb6834', width: 2, type: 'dashed' } }] : []),
    ],
  }, true)
}

onMounted(() => {
  chart = echarts.init(el.value!)
  render()
  window.addEventListener('resize', onResize)
})
const onResize = () => chart?.resize()
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
watch(() => [props.points, props.compare, props.history, props.threshold, props.compareLabel, props.forecastLabel], render, { deep: true })
</script>

<template>
  <div ref="el" class="chart" role="img" aria-label="График остатка на счёте: факт и прогноз" />
</template>

<style scoped>
.chart { width: 100%; height: 320px; }
</style>
