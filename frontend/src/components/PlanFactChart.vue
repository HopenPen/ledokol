<script setup lang="ts">
// План-факт по дням: прошлый прогноз (пунктир + полоса разброса) против фактического остатка.
// Дни, где факт вышел за полосу, — красные точки: «отклонения выделены» из кейса.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { DayCompare } from '../api'
import { echarts, tokens } from '../charts'
import { humanDate, money, rub, shortDate } from '../format'

const props = defineProps<{ rows: DayCompare[] }>()
const el = ref<HTMLDivElement>()
let chart: ReturnType<typeof echarts.init> | null = null

function render() {
  if (!chart) return
  const t = tokens()
  const r = props.rows
  chart.setOption({
    animationDuration: 400,
    textStyle: { fontFamily: t.font },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis', confine: true, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.ink, fontSize: 13 },
      formatter: (items: { value: [string, number] }[]) => {
        const row = r.find((x) => x.date === items[0]?.value[0])
        if (!row) return ''
        const sign = row.deviation >= 0 ? '+' : '−'
        return [`<b>${humanDate(row.date, true)}</b>`, `Ожидали: ${money(Math.round(row.plan))}`, `Было: <b>${money(Math.round(row.fact))}</b>`,
                `Разница: ${sign}${rub(Math.abs(row.deviation))}`,
                row.flagged ? `<span style="color:${t.risk}">Вне обычного разброса</span>` : ''].filter(Boolean).join('<br/>')
      },
    },
    xAxis: { type: 'time', axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false },
             axisLabel: { color: t.ink3, hideOverlap: true, formatter: (v: number) => shortDate(new Date(v).toISOString()) } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: t.ink3, formatter: (v: number) => rub(v) },
             splitLine: { lineStyle: { color: t.line, type: 'dashed' } } },
    series: [
      { name: '_low', type: 'line', data: r.map((x) => [x.date, x.low]), stack: 'b', stackStrategy: 'all', symbol: 'none', lineStyle: { opacity: 0 }, silent: true },
      { name: '_band', type: 'line', data: r.map((x) => [x.date, x.high - x.low]), stack: 'b', stackStrategy: 'all', symbol: 'none',
        lineStyle: { opacity: 0 }, areaStyle: { color: t.band, opacity: 0.85 }, silent: true },
      { name: 'Ожидали', type: 'line', data: r.map((x) => [x.date, x.plan]), symbol: 'none', lineStyle: { color: t.brand, width: 2, type: 'dashed' } },
      { name: 'Было', type: 'line', data: r.map((x) => [x.date, x.fact]), symbol: 'circle', symbolSize: 5, itemStyle: { color: t.ink },
        lineStyle: { color: t.ink, width: 2 } },
      { name: 'Отклонение', type: 'scatter', data: r.filter((x) => x.flagged).map((x) => [x.date, x.fact]), symbolSize: 11, z: 5,
        itemStyle: { color: t.risk, borderColor: t.surface, borderWidth: 2 } },
    ],
  }, true)
}

let observer: ResizeObserver | null = null
onMounted(() => { chart = echarts.init(el.value!); render(); observer = new ResizeObserver(() => chart?.resize()); observer.observe(el.value!) })
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
watch(() => props.rows, render, { deep: true })
</script>

<template>
  <div>
    <div ref="el" class="chart" role="img" aria-label="План и факт остатка по дням" />
    <ul class="legend" aria-hidden="true">
      <li><i class="k-plan" />ожидали</li><li><i class="k-band" />обычный разброс</li><li><i class="k-fact" />было</li><li><i class="k-dot" />отклонение</li>
    </ul>
  </div>
</template>

<style scoped>
.chart { width: 100%; height: 300px; }
.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 0; margin: 8px 0 0; font-size: 13px; color: var(--ink-2); }
.legend li { display: inline-flex; align-items: center; gap: 6px; }
.legend i { display: inline-block; width: 16px; border-top: 2px solid var(--ink); }
.k-plan { border-top: 2px dashed var(--brand) !important; }
.k-band { height: 10px; border: 0 !important; background: var(--brand-band); border-radius: 2px; }
.k-dot { width: 10px !important; height: 10px; border: 0 !important; background: var(--risk); border-radius: 50%; }
</style>
