// Подключаем из ECharts только то, что рисуем: так бандл в разы легче, чем `import * as echarts`.
import { LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, ScatterChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer])

/** Цвета графиков берём из CSS-токенов: один источник правды для интерфейса и графиков. */
export function tokens() {
  const s = getComputedStyle(document.documentElement)
  const v = (name: string) => s.getPropertyValue(name).trim()
  return {
    brand: v('--brand'), band: v('--brand-band'), ink: v('--ink'), ink2: v('--ink-2'), ink3: v('--ink-3'),
    line: v('--line'), risk: v('--risk'), riskSoft: v('--risk-soft'), warn: v('--warn'), surface: v('--surface'),
    font: s.fontFamily,
  }
}

export { echarts }
