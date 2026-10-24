// Подключаем из ECharts только то, что рисуем: так бандл в разы легче, чем `import * as echarts`.
import { LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, ScatterChart, GridComponent, LegendComponent, TooltipComponent, MarkLineComponent, CanvasRenderer])

export { echarts }
