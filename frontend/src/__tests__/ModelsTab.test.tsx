// @vitest-environment jsdom
import type { ReactNode } from 'react'
import { act } from 'react-dom/test-utils'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ModelsTab } from '../pages/historical/ModelsTab'
import type { ModelComparisonItem, SystemStatus } from '../types'

type TooltipFormatter = (value: unknown, name: unknown) => [string, string]
const chartProps = vi.hoisted(() => ({ tooltips: [] as Array<{ formatter: TooltipFormatter }> }))
vi.mock('../contexts/ApiContext', () => ({ useApi: () => apiState }))
vi.mock('recharts', () => {
  const Container = ({ children }: { children?: ReactNode }) => <div>{children}</div>
  return {
    ResponsiveContainer: Container,
    BarChart: ({ children, data }: { children?: ReactNode; data: unknown }) => <div data-chart={JSON.stringify(data)}>{children}</div>,
    Bar: ({ children, dataKey, maxBarSize }: { children?: ReactNode; dataKey: string; maxBarSize: number }) => <div data-bar={dataKey} data-max-bar-size={maxBarSize}>{children}</div>,
    Tooltip: (props: { formatter: TooltipFormatter }) => { chartProps.tooltips.push(props); return null },
    XAxis: () => null, YAxis: () => null, CartesianGrid: () => null, Legend: () => null, Cell: () => null,
  }
})

let root: Root
let host: HTMLDivElement
let apiState: { systemStatus: SystemStatus | null; isLoading: { systemStatus: boolean }; errors: { systemStatus: string | null } }
const setHours = vi.fn()
const refresh = vi.fn()
const modelDetails: NonNullable<SystemStatus['model_details']> = [
  { id: 'tf_load_split_v1', name: 'TensorFlow 负荷预测模型（TF Split v1）', task: '未来24小时负荷预测', architecture: 'BiGRU-GRU', framework: 'TensorFlow', loaded: true },
  { id: 'tf_price_split_v1', name: 'TensorFlow 电价预测模型（TF Split v1）', task: '未来24小时P10/P50/P90电价预测', architecture: 'BiGRU-GRU Quantile', framework: 'TensorFlow', loaded: true },
  { id: 'pv_v2', name: 'TensorFlow 光伏预测模型（PV v2）', task: '未来24小时光伏发电预测', architecture: 'TCN-GRU-Attention', framework: 'TensorFlow', loaded: true },
]
const productionStatus = (details = modelDetails): SystemStatus => ({
  status: 'healthy', models_loaded: details.filter(model => model.loaded).length, models_total: details.length,
  model_details: details, device: 'tensorflow', total_inferences: 20, average_inference_time_ms: 40,
  ensemble_weights: {}, uptime_seconds: 60, timestamp: '2026-10-06T00:00:00Z',
})
const comparison = (overrides: Partial<ModelComparisonItem> = {}): ModelComparisonItem => ({
  model_name: 'tf_split_v1', count: 40, metric_count: 16, mape: 1.23456, rmse: 321.456,
  mae: 210.987, avg_inference_time_ms: 1900.45, comparison_scope: 'single_model_window', ...overrides,
})
const inventory = () => host.querySelector<HTMLElement>('[aria-labelledby="production-models-title"]')!
const metrics = () => host.querySelector<HTMLElement>('[aria-labelledby="load-model-metrics-title"]')!
const render = async (data: Record<string, ModelComparisonItem> = {}, hours = 24, loading = false, error: string | null = null) => {
  chartProps.tooltips.length = 0
  await act(async () => root.render(<ModelsTab modelComparison={data} modelCompareHours={hours} setModelCompareHours={setHours} loading={{ models: loading }} errors={{ models: error }} loadModelComparison={refresh} />))
}

beforeEach(() => {
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  apiState = { systemStatus: productionStatus(), isLoading: { systemStatus: false }, errors: { systemStatus: null } }
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
})

it('shows the three actual production tasks, architectures, framework and reported loading states', async () => {
  apiState.systemStatus = productionStatus(modelDetails.map(model => model.id === 'pv_v2' ? { ...model, loaded: false } : model))
  await render({ tf_split_v1: comparison() })
  expect(inventory().querySelectorAll('article')).toHaveLength(3)
  expect(inventory().textContent).toContain('已加载 2 / 3')
  for (const model of modelDetails) {
    const card = inventory().querySelector(`[aria-label="${model.name}"]`)!
    expect(card.textContent).toContain(model.task)
    expect(card.textContent).toContain(model.architecture)
    expect(card.textContent).toContain('框架：TensorFlow')
  }
  expect(inventory().querySelector('[aria-label="TensorFlow 光伏预测模型（PV v2）"]')!.textContent).toContain('未加载')
  expect(metrics().querySelector('tbody')!.querySelectorAll('tr')).toHaveLength(1)
})

it('does not invent production models or a loaded count when shared status has not arrived', async () => {
  apiState.systemStatus = null
  await render()
  expect(inventory().querySelectorAll('article')).toHaveLength(0)
  expect(inventory().textContent).toContain('暂未获得生产模型明细')
  expect(inventory().textContent).not.toContain('已加载 3 / 3')
  apiState.isLoading.systemStatus = true
  await render()
  expect(inventory().textContent).toContain('正在获取生产模型状态')
})

it('labels a failed status refresh as unconfirmed and retains only the previous reported inventory', async () => {
  apiState.errors.systemStatus = '服务暂不可用'
  await render()
  expect(inventory().querySelector('[role="alert"]')!.textContent).toContain('下列为上次报告，无法确认当前加载状态')
  expect(inventory().textContent).toContain('上次报告已加载 3 / 3')
  expect(inventory().querySelectorAll('article')).toHaveLength(3)
  expect(Array.from(inventory().querySelectorAll('article')).every(card => card.textContent?.includes('上次报告：已加载'))).toBe(true)
  apiState.systemStatus = null
  await render()
  expect(inventory().querySelector('[role="alert"]')!.textContent).toContain('无法确认当前生产模型及加载状态')
  expect(inventory().querySelectorAll('article')).toHaveLength(0)
})

it('reports abnormal service status and absent details without manufacturing three loaded cards', async () => {
  apiState.systemStatus = { ...productionStatus([]), status: 'error', models_loaded: 0, models_total: 3 }
  await render()
  expect(inventory().textContent).toContain('系统运行状态异常')
  expect(inventory().textContent).toContain('已加载 0 / 3')
  expect(inventory().textContent).toContain('暂未获得生产模型明细')
  expect(inventory().querySelectorAll('article')).toHaveLength(0)
})

it('keeps the inventory visible when load history is empty, loading or unavailable', async () => {
  await render()
  expect(metrics().textContent).toContain('暂无负荷版本统计记录')
  expect(inventory().querySelectorAll('article')).toHaveLength(3)
  await render({}, 24, true)
  expect(inventory().querySelectorAll('article')).toHaveLength(3)
  await render({}, 24, false, '历史统计请求失败')
  expect(metrics().textContent).toContain('历史统计请求失败')
  expect(inventory().querySelectorAll('article')).toHaveLength(3)
})

it('describes a single load version as model metrics with forecast-hour and paired-hour counts', async () => {
  await render({ tf_split_v1: comparison() })
  expect(metrics().querySelector('h2')!.textContent).toBe('负荷模型指标')
  expect(metrics().textContent).toContain('当前负荷版本的实测配对指标')
  expect(metrics().textContent).toContain('窗口内只有 1 个负荷版本属正常情况')
  const cells = metrics().querySelectorAll('tbody td')
  expect(Array.from(cells).slice(1).map(cell => cell.textContent)).toEqual(['40', '16', '1.23', '321.5', '211.0', '1900.5'])
  expect(metrics().textContent).toContain('MAPE (%)')
  expect(metrics().textContent).toContain('RMSE (MW)')
  expect(metrics().textContent).toContain('目标小时（含未来）')
  expect(metrics().textContent).toContain('实测配对小时')
  expect(metrics().textContent).toContain('预测记录平均耗时 (ms)')
  expect(metrics().textContent).toContain('并非此负荷模型单独计时')
  expect(metrics().textContent).toContain('不等同于固定提前 24 小时的精度')
})

it('uses a comparison heading only for multiple recorded load versions and limits bar width', async () => {
  await render({ tf_split_v1: comparison(), tf_v2: comparison({ model_name: 'tf_v2', comparison_scope: 'common_targets' }) })
  expect(metrics().querySelector('h2')!.textContent).toBe('负荷模型版本对比')
  expect(metrics().querySelectorAll('tbody tr')).toHaveLength(2)
  expect(metrics().textContent).toContain('多版本只使用共同目标小时')
  expect(Array.from(metrics().querySelectorAll('[data-bar]')).map(bar => bar.getAttribute('data-max-bar-size'))).toEqual(['56', '56', '56'])
})

it('keeps null metrics as placeholders in the table and chart instead of zero errors', async () => {
  await render({ tf_split_v1: comparison({ mape: null, rmse: null, mae: null, avg_inference_time_ms: null, metric_count: 0 }) })
  const values = Array.from(metrics().querySelectorAll('tbody td')).slice(3).map(cell => cell.textContent)
  expect(values).toEqual(['--', '--', '--', '--'])
  const chart = JSON.parse(metrics().querySelector('[data-chart]')!.getAttribute('data-chart')!)
  expect(chart[0]).toMatchObject({ mape: null, rmse: null, mae: null })
})

it('provides a labelled generation-time filter and explains targets beyond the selected window', async () => {
  await render({ tf_split_v1: comparison() }, 24)
  const filter = metrics().querySelector<HTMLSelectElement>('select')!
  expect(metrics().querySelector('label')!.htmlFor).toBe(filter.id)
  expect(metrics().querySelector('label')!.textContent).toBe('预测生成时间范围')
  expect(Array.from(filter.options).map(option => option.textContent)).toEqual(['最近 6 小时', '最近 24 小时', '最近 72 小时', '最近 168 小时', '最近 720 小时'])
  expect(document.getElementById(filter.getAttribute('aria-describedby')!)!.textContent).toContain('按生成时间筛选最近 24 小时')
  expect(metrics().textContent).toContain('含尚未到期的未来目标，因此可能大于筛选小时数')
  expect(metrics().textContent).toContain('实测配对小时仅包括已回填真实值的小时')
  await act(async () => { filter.value = '72'; filter.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(setHours).toHaveBeenCalledWith(72)
})

it('formats both chart tooltips with stable precision, units and null placeholders', async () => {
  await render({ tf_split_v1: comparison() })
  expect(chartProps.tooltips).toHaveLength(2)
  for (const { formatter } of chartProps.tooltips) {
    expect(formatter(1.23456, 'MAPE (%)')).toEqual(['1.23%', 'MAPE (%)'])
    expect(formatter(321.456, 'RMSE (MW)')).toEqual(['321.5 MW', 'RMSE (MW)'])
    expect(formatter(210.987, 'MAE (MW)')).toEqual(['211.0 MW', 'MAE (MW)'])
    expect(formatter(null, 'MAPE (%)')).toEqual(['--', 'MAPE (%)'])
    expect(formatter(undefined, 'RMSE (MW)')).toEqual(['--', 'RMSE (MW)'])
    expect(formatter(Number.NaN, 'MAE (MW)')).toEqual(['--', 'MAE (MW)'])
    expect(formatter(0, 'MAE (MW)')).toEqual(['0.0 MW', 'MAE (MW)'])
  }
})
