<script setup lang="ts">
// График остатка: факт (серый) + прогноз (зелёная линия) + «обычный разброс» P10–P90 (полоса) + порог (красный пунктир).
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
    grid: { left: 64, right: 16, top: 16, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      formatter: (items: { seriesName: string; value: [string, number] }[]) => {
        const d = items[0]?.value[0]
        const p = props.points.find((x) => x.date === d)
        const rows = items.filter((i) => !i.seriesName.startsWith('_')).map((i) => `${i.seriesName}: ${rub(i.value[1])}`)
        if (p && p.prob_below > 0.05) rows.push(`шанс нехватки: ${Math.round(p.prob_below * 100)}%`)
        return [humanDate(d), ...rows].join('<br/>')
      },
    },
    xAxis: { type: 'time', axisLabel: { formatter: (v: number) => humanDate(new Date(v).toISOString().slice(0, 10)) } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => rub(v) }, splitLine: { lineStyle: { color: '#e6ece9' } } },
    series: [
      { name: '_low', type: 'line', data: lower, stack: 'band', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 } },
      { name: '_band', type: 'line', data: band, stack: 'band', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: '#cfe3d8' } },
      { name: 'Было', type: 'line', data: hist, symbol: 'none', lineStyle: { color: '#7c8c85', width: 2 } },
      { name: 'Прогноз', type: 'line', data: p50, symbol: 'none', lineStyle: { color: '#0f7b57', width: 2 },
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: props.threshold }],
                    lineStyle: { color: '#b42318', type: 'dashed' }, label: { formatter: 'порог', position: 'insideStartTop', color: '#b42318' } } },
      ...(props.compare ? [{ name: 'Если так случится', type: 'line', data: [...joint, ...props.compare.map((p) => [p.date, p.p50])],
                             symbol: 'none', lineStyle: { color: '#a8650f', width: 2, type: 'dashed' } }] : []),
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
watch(() => [props.points, props.compare, props.history, props.threshold], render, { deep: true })
</script>

<template>
  <div ref="el" class="chart" role="img" aria-label="График остатка на счёте: факт и прогноз" />
</template>

<style scoped>
.chart { width: 100%; height: 320px; }
</style>
