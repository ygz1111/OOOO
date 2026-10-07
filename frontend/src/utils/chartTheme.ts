/** 所有业务图表共用的数据色；颜色与线型共同区分实测、预测及回测。 */
export const CHART_COLORS = {
  forecast: 'var(--chart-forecast)',
  actual: 'var(--chart-actual)',
  replay: 'var(--chart-replay)',
  solar: 'var(--chart-solar)',
  lower: 'var(--chart-replay)',
  upper: 'var(--chart-solar)',
  error: 'var(--chart-error)',
  grid: 'var(--chart-grid)',
  axis: 'var(--chart-axis)',
  reference: 'var(--chart-reference)',
} as const

export const CHART_AXIS = { fill: CHART_COLORS.axis, fontSize: 12 }
export const CHART_GRID = { stroke: CHART_COLORS.grid, strokeDasharray: '3 5', vertical: false }
export const CHART_LEGEND = { paddingTop: 16, color: CHART_COLORS.actual, fontSize: 12 }
