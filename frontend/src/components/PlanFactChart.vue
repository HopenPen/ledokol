<script setup lang="ts">
// План-факт по дням: прошлый прогноз (линия + полоса разброса) против фактического остатка.
// Дни, где факт вышел за полосу, — красные точки: это и есть «отклонения выделены» из ТЗ.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { DayCompare } from '../api'
import { echarts } from '../charts'
import { humanDate, rub } from '../format'

const props = defineProps<{ rows: DayCompare[] }>()
const el = ref<HTMLDivElement>()
let chart: ReturnType<typeof echarts.init> | null = null

function render() {
  if (!chart) return
  const r = props.rows
  chart.setOption({
    animation: false,
    grid: { left: 64, right: 16, top: 16, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      formatter: (items: { value: [string, number] }[]) => {
        const row = r.find((x) => x.date === items[0]?.value[0])
        if (!row) return ''
        const sign = row.deviation >= 0 ? '+' : '−'
        return [humanDate(row.date), `ожидали: ${rub(row.plan)}`, `было: ${rub(row.fact)}`,
                `разница: ${sign}${rub(Math.abs(row.deviation))}`,
                row.flagged ? '<b>вне обычного разброса</b>' : ''].filter(Boolean).join('<br/>')
      },
    },
    xAxis: { type: 'time', axisLabel: { formatter: (v: number) => humanDate(new Date(v).toISOString().slice(0, 10)) } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => rub(v) }, splitLine: { lineStyle: { color: '#e6ece9' } } },
    series: [
      { name: '_low', type: 'line', data: r.map((x) => [x.date, x.low]), stack: 'b', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 } },
      { name: '_band', type: 'line', data: r.map((x) => [x.date, x.high - x.low]), stack: 'b', stackStrategy: 'all', symbol: 'none',
        lineStyle: { opacity: 0 }, areaStyle: { color: '#cfe3d8' } },
      { name: 'Ожидали', type: 'line', data: r.map((x) => [x.date, x.plan]), symbol: 'none', lineStyle: { color: '#0f7b57', width: 2, type: 'dashed' } },
      { name: 'Было', type: 'line', data: r.map((x) => [x.date, x.fact]), symbol: 'circle', symbolSize: 4, lineStyle: { color: '#13241d', width: 2 } },
      { name: 'Отклонение', type: 'scatter', data: r.filter((x) => x.flagged).map((x) => [x.date, x.fact]), symbolSize: 10,
        itemStyle: { color: '#b42318' }, z: 5 },
    ],
  }, true)
}

const onResize = () => chart?.resize()
onMounted(() => { chart = echarts.init(el.value!); render(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
watch(() => props.rows, render, { deep: true })
</script>

<template>
  <div ref="el" class="chart" role="img" aria-label="План и факт остатка по дням" />
</template>

<style scoped>
.chart { width: 100%; height: 300px; }
</style>
