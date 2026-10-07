// @vitest-environment jsdom
import { StrictMode } from 'react'
import { act } from 'react-dom/test-utils'
import { createRoot, Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import apiService from '../services/api'
import { usePriceBacktest } from '../hooks/usePriceBacktest'
import PriceForecast from '../pages/PriceForecast'

vi.mock('../services/api', () => ({ default: { getPriceBacktest: vi.fn(), getPriceForecast: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ token: scope }) }))
vi.mock('recharts', () => {
  const Container = ({ children }: any) => <div>{children}</div>
  const Chart = ({ children, data }: any) => <div data-chart={JSON.stringify(data)}>{children}</div>
  const Empty = () => null
  return { ResponsiveContainer: Container, LineChart: Chart, Line: Empty, CartesianGrid: Empty,
    XAxis: Empty, YAxis: Empty, Tooltip: Empty, Legend: Empty }
})
let root: Root
let host: HTMLDivElement
let current: ReturnType<typeof usePriceBacktest>
let scopeNumber = 0
let scope: string
const range = { earliest: '2026-01-01', latest: '2026-09-30' }
const response = (date: string | null) => ({ data: { date, available_date_range: range, points: [], metrics: null } })
const deferred = () => {
  let resolve!: (value: any) => void
  let reject!: (value: any) => void
  const promise = new Promise<any>((success, failure) => { resolve = success; reject = failure })
  return { promise, resolve, reject }
}
function Consumer() {
  current = usePriceBacktest(scope)
  return <span>{current.data?.date ?? 'empty'}</span>
}
const render = async () => {
  await act(async () => root.render(<StrictMode><Consumer /></StrictMode>))
}
beforeEach(() => {
  vi.resetAllMocks()
  scope = `price-backtest-${++scopeNumber}`
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  vi.mocked(apiService.getPriceBacktest).mockResolvedValue(response(null) as any)
  vi.mocked(apiService.getPriceForecast).mockResolvedValue({ predictions: [], timestamp: '2026-10-01T00:00:00-04:00' } as any)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.useRealTimers()
})

it('only fetches the range on entry and merges StrictMode initialization', async () => {
  await render()
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(1)
  expect(apiService.getPriceBacktest).toHaveBeenCalledWith()
  expect(current.date).toBe(range.latest)
  expect(current.data).toBeNull()
})

it('advances the visible date range without starting an unrequested backtest', async () => {
  vi.useFakeTimers()
  await render()
  const advancedRange = { ...range, latest: '2026-10-01' }
  vi.mocked(apiService.getPriceBacktest).mockResolvedValueOnce({ data: { available_date_range: advancedRange, points: [] } } as any)
  await act(async () => { await vi.advanceTimersByTimeAsync(300000) })
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(2)
  expect(apiService.getPriceBacktest).toHaveBeenLastCalledWith()
  expect(current.range).toEqual(advancedRange)
  expect(current.date).toBe('2026-10-01')
  expect(current.data).toBeNull()
})

it('refreshes newly available real labels for the selected historical date every five minutes', async () => {
  vi.useFakeTimers()
  await render()
  vi.mocked(apiService.getPriceBacktest).mockResolvedValueOnce(response('2026-09-29') as any)
  await act(async () => { await current.selectDate('2026-09-29') })
  const updated = { ...response('2026-09-29').data, points: [{ timestamp: '2026-09-29T01:00:00-04:00', price_actual: 55 }] }
  vi.mocked(apiService.getPriceBacktest).mockImplementation(async date => date
    ? { data: updated } as any : response(null) as any)
  await act(async () => { await vi.advanceTimersByTimeAsync(300000) })
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(4)
  expect(current.date).toBe('2026-09-29')
  expect(current.data?.points[0].price_actual).toBe(55)
  expect(current.loading).toBe(false)
})

it('pauses hidden history polling and refreshes the range when the page becomes visible', async () => {
  vi.useFakeTimers()
  await render()
  Object.defineProperty(document, 'hidden', { configurable: true, value: true })
  await act(async () => { await vi.advanceTimersByTimeAsync(600000) })
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(1)
  const advancedRange = { ...range, latest: '2026-10-01' }
  vi.mocked(apiService.getPriceBacktest).mockResolvedValueOnce({ data: { available_date_range: advancedRange, points: [] } } as any)
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(2)
  expect(current.range).toEqual(advancedRange)
  expect(current.data).toBeNull()
})

it('does not reload an old date when selection changes during automatic range refresh', async () => {
  vi.useFakeTimers()
  await render()
  vi.mocked(apiService.getPriceBacktest).mockResolvedValueOnce(response('2026-09-28') as any)
  await act(async () => { await current.selectDate('2026-09-28') })
  const pendingRange = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(pendingRange.promise)
  await act(async () => { await vi.advanceTimersByTimeAsync(300000) })
  vi.mocked(apiService.getPriceBacktest).mockResolvedValueOnce(response('2026-09-29') as any)
  await act(async () => { await current.selectDate('2026-09-29') })
  await act(async () => { pendingRange.resolve(response(null)) })
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(4)
  expect(current.date).toBe('2026-09-29')
  expect(current.data?.date).toBe('2026-09-29')
  expect(current.loading).toBe(false)
})

it('does not let late range initialization overwrite the selected date or its loading state', async () => {
  const initialization = deferred()
  const request = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(initialization.promise).mockReturnValueOnce(request.promise)
  await render()
  await act(async () => { void current.selectDate('2026-09-29') })
  await act(async () => { initialization.resolve(response(null)) })
  expect(current.date).toBe('2026-09-29')
  expect(current.range).toEqual(range)
  expect(current.loading).toBe(true)
  await act(async () => { request.resolve(response('2026-09-29')) })
  expect(current.data?.date).toBe('2026-09-29')
})

it('ignores out-of-order successes and cannot end the newer request loading state', async () => {
  await render()
  const older = deferred()
  const newer = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
  await act(async () => { void current.selectDate('2026-09-28'); void current.selectDate('2026-09-29') })
  await act(async () => { older.resolve(response('2026-09-28')) })
  expect(current.date).toBe('2026-09-29')
  expect(current.data).toBeNull()
  expect(current.loading).toBe(true)
  await act(async () => { newer.resolve(response('2026-09-29')) })
  expect(host.textContent).toBe('2026-09-29')
  expect(current.loading).toBe(false)
})

it('ignores an older failure after the newer result and clears the old result when selecting another date', async () => {
  await render()
  const older = deferred()
  const newer = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
  await act(async () => { void current.selectDate('2026-09-28'); void current.selectDate('2026-09-29') })
  await act(async () => { newer.resolve(response('2026-09-29')) })
  await act(async () => { older.reject(new Error('old request failed')) })
  expect(current.error).toBeNull()
  expect(current.data?.date).toBe('2026-09-29')
  const pending = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(pending.promise)
  await act(async () => { void current.selectDate('2026-09-30') })
  expect(current.data).toBeNull()
  expect(current.date).toBe('2026-09-30')
  await act(async () => { pending.resolve(response('2026-09-30')) })
})

it('recovers the current date after failure and combines concurrent duplicate refreshes', async () => {
  await render()
  vi.mocked(apiService.getPriceBacktest).mockRejectedValueOnce(new Error('历史数据超时'))
  await act(async () => { await current.selectDate('2026-09-29') })
  expect(current.error).toBe('历史数据超时')
  vi.mocked(apiService.getPriceBacktest).mockResolvedValueOnce(response('2026-09-29') as any)
  await act(async () => { await Promise.all([current.refresh(), current.refresh()]) })
  expect(current.data?.date).toBe('2026-09-29')
  expect(current.error).toBeNull()
  expect(current.loading).toBe(false)
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(3)
})

it('isolates pending requests across login sessions and an old completion cannot delete the new request', async () => {
  await render()
  const older = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(older.promise)
  await act(async () => { void current.selectDate('2026-09-29') })
  scope = `another-login-${++scopeNumber}`
  await render()
  const newer = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(newer.promise)
  await act(async () => { void current.selectDate('2026-09-29') })
  await act(async () => { older.resolve(response('2026-09-29')) })
  expect(current.data).toBeNull()
  expect(current.loading).toBe(true)
  await act(async () => { void current.refresh() })
  expect(apiService.getPriceBacktest).toHaveBeenCalledTimes(4)
  await act(async () => { newer.resolve(response('2026-09-29')) })
  expect(current.data?.date).toBe('2026-09-29')
  expect(current.loading).toBe(false)
})

it('rejects a mismatched result date and can clear the date while a request is pending', async () => {
  await render()
  vi.mocked(apiService.getPriceBacktest).mockResolvedValueOnce(response('2026-09-28') as any)
  await act(async () => { await current.selectDate('2026-09-29') })
  expect(current.error).toContain('与所选日期')
  expect(current.data).toBeNull()
  const pending = deferred()
  vi.mocked(apiService.getPriceBacktest).mockReturnValueOnce(pending.promise)
  await act(async () => { void current.selectDate('2026-09-29'); void current.selectDate('') })
  await act(async () => { pending.resolve(response('2026-09-29')) })
  expect(current.date).toBe('')
  expect(current.data).toBeNull()
  expect(current.loading).toBe(false)
})

it('shows the result date and predicted curve without claiming missing labels are measured errors', async () => {
  vi.mocked(apiService.getPriceBacktest).mockImplementation(async date => date ? ({ data: {
    ...response(date).data,
    points: [{ hour: 1, timestamp: `${date}T01:00:00-04:00`, price_p10: 10, price_p50: 20, price_p90: 30, price_actual: null, error_p50: null }],
    label_quality: { evaluated_hours: 0, excluded_hours: 24, notice: '五分钟采样仅用于输入，不计真实误差' },
  } } as any) : response(null) as any)
  await act(async () => root.render(<StrictMode><PriceForecast /></StrictMode>))
  const selected = host.querySelector('input[type=date]') as HTMLInputElement
  // Scope the action to its backtest section, independent of the date label's layout.
  const refresh = [...selected.closest('section')!.querySelectorAll('button')]
    .find(button => button.textContent?.trim() === '刷新')!
  await act(async () => { refresh.click() })
  expect(host.textContent).toContain(`结果日期：${range.latest}`)
  expect(host.textContent).toContain('真实配对 0 小时 · 排除 24 小时')
  expect(host.textContent).toContain('本日暂无完整官方小时真实标签')
  expect(host.textContent).not.toContain('历史 MAE')
  expect([...host.querySelectorAll('[data-chart]')].some(chart => chart.getAttribute('data-chart')?.includes('"预测 P50":20'))).toBe(true)
})
