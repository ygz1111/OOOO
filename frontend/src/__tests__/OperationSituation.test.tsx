// @vitest-environment jsdom
import { act } from 'react-dom/test-utils'
import { StrictMode } from 'react'
import { createRoot, Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import OperationSituationPage from '../pages/OperationSituation'
import apiService from '../services/api'

vi.mock('../services/api', () => ({ default: {
  getOperationSituation: vi.fn(), getHourlyErrorDiagnostics: vi.fn(), getFeatureSensitivity: vi.fn(),
} }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ token: scope }) }))
vi.mock('recharts', () => Object.fromEntries([
  'Area', 'AreaChart', 'ComposedChart', 'Bar', 'BarChart', 'CartesianGrid', 'Cell', 'Legend', 'Line',
  'ResponsiveContainer', 'Tooltip', 'XAxis', 'YAxis',
].map(name => [name, name === 'ResponsiveContainer' ? ({ children }: any) => <>{children}</>
  : name === 'BarChart' ? ({ data }: any) => <div data-error-chart={JSON.stringify(data)} /> : () => null])))
vi.mock('../components/MetricCard', () => ({ default: ({ title, value }: any) => <p data-metric={title}>{value}</p> }))
vi.mock('../components/ui/MicroInteractions', () => ({ RefreshButton: ({ onClick }: any) => <button onClick={onClick}>刷新</button> }))

let root: Root
let host: HTMLDivElement
let scopeNumber = 0
let scope: string
const deferred = () => {
  let resolve!: (value: any) => void
  let reject!: (value: any) => void
  const promise = new Promise<any>((success, failure) => { resolve = success; reject = failure })
  return { promise, resolve, reject }
}
const diagnostics = (days = 7, insight = '') => ({ data: {
  days, sample_count: 1, hourly: [{ hour: 0, count: 0, mae_mw: null, mape: null, bias_mw: null }],
  heatmap: [], insight, method_note: '统计真实回填记录',
} })
const selectDays = async (days: number) => {
  await act(async () => {
    const select = host.querySelector<HTMLSelectElement>('select[aria-label="误差诊断样本范围"]')!
    select.value = String(days)
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}
const data = () => ({
  generated_at: '2026-09-22T07:03:00', input_quality: null,
  data_scope: { region: 'NewEngland', horizon_hours: 1, pv_coverage_hours: 0, renewable_note: '' },
  hourly: [{ timestamp: '2026-09-22T08:00:00', time_label: '08:00', load_mw: 1000, pv_mw: null, renewable_mw: null, net_load_mw: null, renewable_share_percent: null }],
  renewable: { average_share_percent: null, highest_share_time: '—', highest_share_percent: null, total_energy_mwh: null },
  peak_valley: { spread_mw: 77, peak_time: '08:00', peak_load_mw: 1000, valley_load_mw: 923, valley_time: '08:00', peak_net_load_mw: null, peak_net_load_time: '—', renewable_peak_reduction_mw: null },
  supply_demand: { maximum_net_load_mw: null, maximum_net_load_time: '—', maximum_net_load_ramp_mw: null, ramp_time: '—', interpretation: '' },
  risks: [], model: { inference_time_ms: 3, data_source: 'live' },
})
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-22T11:07:00Z'))
  vi.resetAllMocks()
  scope = `operation-${++scopeNumber}`
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  vi.mocked(apiService.getOperationSituation).mockResolvedValue({ data: data() } as any)
  vi.mocked(apiService.getHourlyErrorDiagnostics).mockImplementation(async days => diagnostics(days) as any)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.useRealTimers()
})

it('renders missing PV as unavailable while keeping load metrics', async () => {
  await act(async () => root.render(<OperationSituationPage />))
  expect(host.querySelector('[data-metric="电网最大净负荷"]')?.textContent).toBe('—')
  expect(host.querySelector('[data-metric="预测区间光伏电量"]')?.textContent).toBe('—')
  expect(host.querySelector('[data-metric="负荷峰谷差"]')?.textContent).toBe('77')
  expect(host.textContent).not.toContain('NaN')
})

it('expires old derived metrics at the hour boundary even when the API stays stale', async () => {
  await act(async () => root.render(<OperationSituationPage />))
  await act(async () => { await vi.advanceTimersByTimeAsync(53 * 60000 + 20) })
  expect(host.querySelector('[data-metric="负荷峰谷差"]')).toBeNull()
  expect(host.textContent).toContain('正在更新预测区间')
})

it('refreshes an expired first hour immediately instead of waiting for the five-minute deadline', async () => {
  vi.setSystemTime(new Date('2026-09-22T11:57:00Z'))
  await act(async () => root.render(<OperationSituationPage />))
  const next = data()
  vi.mocked(apiService.getOperationSituation).mockResolvedValueOnce({ data: {
    ...next, generated_at: '2026-09-22T08:00:00',
    hourly: [{ ...next.hourly[0], timestamp: '2026-09-22T09:00:00', time_label: '09:00' }],
    peak_valley: { ...next.peak_valley, spread_mw: 99 },
  } } as any)
  await act(async () => { await vi.advanceTimersByTimeAsync(3 * 60000 + 20) })
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(2)
  expect(host.querySelector('[data-metric="负荷峰谷差"]')?.textContent).toBe('99')
  expect(host.textContent).not.toContain('正在更新预测区间')
})

it('does not loop when the hour-boundary refresh still returns the same expired hour', async () => {
  vi.setSystemTime(new Date('2026-09-22T11:57:00Z'))
  await act(async () => root.render(<OperationSituationPage />))
  // 上游可返回新生成时间但相同旧目标小时；不能据此不断立即重试。
  vi.mocked(apiService.getOperationSituation).mockResolvedValue({ data: {
    ...data(), generated_at: '2026-09-22T08:00:01',
  } } as any)
  await act(async () => { await vi.advanceTimersByTimeAsync(3 * 60000 + 20) })
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(2)
  expect(host.querySelector('[data-metric="负荷峰谷差"]')).toBeNull()
})

it('retries a pending snapshot without waiting five minutes', async () => {
  vi.mocked(apiService.getOperationSituation).mockResolvedValueOnce({ data: {
    ...data(), hourly: [], input_quality: { refresh_in_progress: true, notice: '准备中' },
  } } as any)
  await act(async () => root.render(<OperationSituationPage />))
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(2)
  expect(host.querySelector('[data-metric="负荷峰谷差"]')?.textContent).toBe('77')
})

it('waits for the core snapshot before requesting diagnostics and merges StrictMode entry', async () => {
  const pending = deferred()
  vi.mocked(apiService.getOperationSituation).mockReturnValueOnce(pending.promise)
  await act(async () => root.render(<StrictMode><OperationSituationPage /></StrictMode>))
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(1)
  expect(apiService.getHourlyErrorDiagnostics).not.toHaveBeenCalled()
  await act(async () => { pending.resolve({ data: data() }) })
  expect(apiService.getHourlyErrorDiagnostics).toHaveBeenCalledTimes(1)
})

it('does not show an older range result or finish the newer range loading state', async () => {
  const older = deferred()
  const newer = deferred()
  vi.mocked(apiService.getHourlyErrorDiagnostics).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
  await act(async () => root.render(<OperationSituationPage />))
  await selectDays(14)
  await act(async () => { older.resolve(diagnostics(7, '七天旧诊断')) })
  expect(host.textContent).not.toContain('七天旧诊断')
  expect(host.textContent).not.toContain('暂无可诊断的误差样本')
  await act(async () => { newer.resolve(diagnostics(14, '十四天新诊断')) })
  expect(host.textContent).toContain('十四天新诊断')
})

it('ignores old range errors after another range has succeeded', async () => {
  const older = deferred()
  vi.mocked(apiService.getHourlyErrorDiagnostics).mockReturnValueOnce(older.promise)
  await act(async () => root.render(<OperationSituationPage />))
  await selectDays(30)
  await act(async () => { older.reject(new Error('七天请求失败')) })
  expect(host.textContent).not.toContain('七天请求失败')
  expect(host.querySelector<HTMLSelectElement>('select')?.value).toBe('30')
  expect(host.textContent).toContain('统计真实回填记录')
})

it('retains a healthy snapshot and diagnostics across route changes until their five-minute deadline', async () => {
  await act(async () => root.render(<OperationSituationPage />))
  await act(async () => root.render(<p>其他页面</p>))
  await act(async () => { await vi.advanceTimersByTimeAsync(90000) })
  await act(async () => root.render(<OperationSituationPage />))
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(1)
  expect(apiService.getHourlyErrorDiagnostics).toHaveBeenCalledTimes(1)
  expect(host.querySelector('[data-metric="负荷峰谷差"]')?.textContent).toBe('77')
})

it('keeps valid metrics on refresh failure and recovers after 35 seconds', async () => {
  await act(async () => root.render(<OperationSituationPage />))
  vi.mocked(apiService.getOperationSituation).mockRejectedValueOnce(new Error('暂时不可用'))
  await act(async () => host.querySelector<HTMLButtonElement>('.page-actions button')!.click())
  expect(host.textContent).toContain('暂时不可用')
  expect(host.querySelector('[data-metric="负荷峰谷差"]')?.textContent).toBe('77')
  await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(3)
  expect(host.textContent).not.toContain('暂时不可用')
})

it('preserves an hour without real samples as unavailable instead of zero error', async () => {
  await act(async () => root.render(<OperationSituationPage />))
  const chart = JSON.parse(host.querySelector('[data-error-chart]')!.getAttribute('data-error-chart')!)
  expect(chart[0].mae_mw).toBeNull()
})

it('retains diagnostic charts on a temporary refresh failure and retries automatically', async () => {
  await act(async () => root.render(<OperationSituationPage />))
  vi.mocked(apiService.getHourlyErrorDiagnostics).mockRejectedValueOnce(new Error('诊断暂时不可用'))
  await act(async () => host.querySelector<HTMLButtonElement>('select')!.closest('.data-toolbar')!.querySelector<HTMLButtonElement>('button')!.click())
  expect(host.textContent).toContain('诊断暂时不可用')
  expect(host.querySelector('[data-error-chart]')).not.toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
  expect(host.textContent).not.toContain('诊断暂时不可用')
  expect(apiService.getHourlyErrorDiagnostics).toHaveBeenCalledTimes(3)
})

it('retries incomplete PV input without immediately reloading healthy diagnostics', async () => {
  vi.mocked(apiService.getOperationSituation).mockResolvedValueOnce({ data: {
    ...data(), input_quality: { components: { load: { status: 'fresh' }, pv: { status: 'unavailable' } } },
  } } as any)
  await act(async () => root.render(<OperationSituationPage />))
  await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
  expect(apiService.getOperationSituation).toHaveBeenCalledTimes(2)
  expect(apiService.getHourlyErrorDiagnostics).toHaveBeenCalledTimes(1)
})
