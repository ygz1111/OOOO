// @vitest-environment jsdom
import { act } from 'react-dom/test-utils'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import apiService from '../services/api'
import LoadForecast from '../pages/LoadForecast'
import HistoricalAnalysis from '../pages/HistoricalAnalysis'
import type { DayBacktestData, DayBacktestRangeData } from '../types'

vi.mock('../services/api', () => ({ default: {
  getPredictionHistory: vi.fn(), getAccuracyStats: vi.fn(), getDayBacktest: vi.fn(),
} }))
vi.mock('../contexts/ApiContext', () => ({ useApi: () => apiState }))
vi.mock('../components/LoadForecastChart', () => ({ default: () => <div>负荷图</div> }))
vi.mock('../pages/historical/OverviewTab', () => ({ OverviewTab: () => null }))
vi.mock('../pages/historical/HistoryTab', () => ({ HistoryTab: () => null }))
vi.mock('../pages/historical/ModelsTab', () => ({ ModelsTab: () => null }))
vi.mock('../pages/historical/TrendsTab', () => ({ TrendsTab: () => null }))
vi.mock('../pages/historical/ErrorsTab', () => ({ ErrorsTab: () => null }))
vi.mock('../pages/historical/DriftTab', () => ({ DriftTab: () => null }))
vi.mock('../pages/historical/BacktestTab', () => ({ BacktestTab: (props: any) => (
  <div>
    <input aria-label="回测日期" value={props.date ?? ''} max={props.range?.latest ?? ''}
      onChange={event => props.onDateChange(event.target.value)} />
    <button onClick={props.onRefresh}>回测刷新</button>
    <span data-testid="result-date">{props.data?.date ?? ''}</span>
    <span data-testid="result-note">{props.data?.note ?? ''}</span>
    <span data-testid="error">{props.error ?? ''}</span>
    <span data-testid="loading">{String(props.loading)}</span>
  </div>
) }))

let root: Root
let host: HTMLDivElement
let apiState: any
let latest: string
let revision: string
const range = (): DayBacktestRangeData => ({ available_date_range: { earliest: '2026-10-01', latest } })
const backtest = (date: string): DayBacktestData => ({
  ...range(), date, timezone: 'America/New_York', pairs: [], metrics: null, weather: [], note: revision,
})
const response = (data: DayBacktestData | DayBacktestRangeData) => ({
  status: 'success', message: '', timestamp: new Date().toISOString(), data,
})
const deferred = () => {
  let resolve!: (value: any) => void
  const promise = new Promise<any>(success => { resolve = success })
  return { promise, resolve }
}
const text = (testId: string) => host.querySelector(`[data-testid="${testId}"]`)!.textContent
const selectedDate = () => (host.querySelector('[aria-label="回测日期"]') as HTMLInputElement).value
const chooseDate = async (date: string) => {
  const input = host.querySelector('[aria-label="回测日期"]') as HTMLInputElement
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, date)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const enterBacktest = async () => {
  await act(async () => root.render(<HistoricalAnalysis />))
  await act(async () => (host.querySelector('#historical-tab-backtest') as HTMLButtonElement).click())
}
const visibility = async (state: DocumentVisibilityState) => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: state })
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-03T05:00:00Z')) // 01:00 ET
  vi.resetAllMocks()
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  latest = '2026-10-03'
  revision = '首次响应'
  vi.mocked(apiService.getPredictionHistory).mockResolvedValue({ data: [] } as any)
  vi.mocked(apiService.getAccuracyStats).mockResolvedValue({ data: null } as any)
  vi.mocked(apiService.getDayBacktest).mockImplementation(async date => response(date ? backtest(date) : range()))
  apiState = {
    prediction: null, overview: null, isLoading: { prediction: false, overview: false },
    isInitialLoad: { prediction: false }, errors: {}, loadPrediction: vi.fn().mockResolvedValue(undefined),
    loadOverview: vi.fn().mockResolvedValue(undefined),
  }
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.useRealTimers()
})

it('forces the load-page prediction refresh before requesting a refreshed historical chart', async () => {
  const prediction = deferred()
  apiState.loadPrediction.mockReturnValueOnce(prediction.promise)
  await act(async () => root.render(<LoadForecast />))
  const button = Array.from(host.querySelectorAll('button')).find(item => item.textContent?.trim() === '刷新')!
  await act(async () => button.click())
  expect(apiState.loadPrediction).toHaveBeenCalledWith(true)
  expect(apiState.loadOverview).not.toHaveBeenCalled()
  await act(async () => prediction.resolve(undefined))
  expect(apiState.loadOverview).toHaveBeenCalledWith(true)
})

it('continues syncing the selected historical date and its range from 01:00 through 05:00 without remounting', async () => {
  await enterBacktest()
  expect(selectedDate()).toBe('2026-10-03')
  for (let hour = 2; hour <= 5; hour += 1) {
    revision = `响应版本 ${hour}`
    await act(async () => { await vi.advanceTimersByTimeAsync(60 * 60 * 1000) })
    expect(text('result-note')).toBe(revision)
    expect(text('result-date')).toBe('2026-10-03')
  }
  expect(apiService.getDayBacktest).toHaveBeenCalledTimes(98) // Initial range/date + 48 range/date polls.
  const datedCalls = vi.mocked(apiService.getDayBacktest).mock.calls.filter(([date]) => date)
  expect(datedCalls).toHaveLength(49)
  expect(datedCalls.every(([date, force]) => date === '2026-10-03' && force === false)).toBe(true)
})

it('pauses a hidden backtest tab and immediately synchronizes it when the page becomes visible', async () => {
  await enterBacktest()
  await visibility('hidden')
  revision = '返回页面后的响应'
  await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60 * 1000) })
  expect(apiService.getDayBacktest).toHaveBeenCalledTimes(2)
  await visibility('visible')
  expect(apiService.getDayBacktest).toHaveBeenCalledTimes(4)
  expect(text('result-note')).toBe(revision)
  expect(selectedDate()).toBe('2026-10-03')
})

it('a late range response cannot reset a newer user-selected date or overwrite its result', async () => {
  await enterBacktest()
  const pendingRange = deferred()
  vi.mocked(apiService.getDayBacktest).mockReturnValueOnce(pendingRange.promise)
  await act(async () => { await vi.advanceTimersByTimeAsync(5 * 60 * 1000) })
  await chooseDate('2026-10-02')
  expect(text('result-date')).toBe('2026-10-02')
  latest = '2026-10-04'
  await act(async () => pendingRange.resolve(response(range())))
  expect(selectedDate()).toBe('2026-10-02')
  expect(text('result-date')).toBe('2026-10-02')
  expect((host.querySelector('[aria-label="回测日期"]') as HTMLInputElement).max).toBe('2026-10-04')
})

it('updates the available range across an ET midnight without changing the selected day', async () => {
  vi.setSystemTime(new Date('2026-10-04T03:58:00Z')) // 23:58 ET on October 3.
  await enterBacktest()
  latest = '2026-10-04'
  await act(async () => { await vi.advanceTimersByTimeAsync(5 * 60 * 1000) })
  expect((host.querySelector('[aria-label="回测日期"]') as HTMLInputElement).max).toBe('2026-10-04')
  expect(selectedDate()).toBe('2026-10-03')
  expect(text('result-date')).toBe('2026-10-03')
})

it('recovers after a date request fails when visibility triggers the next normal synchronization', async () => {
  await enterBacktest()
  vi.mocked(apiService.getDayBacktest).mockResolvedValueOnce(response(range()))
    .mockRejectedValueOnce(new Error('真实负荷回填暂时不可用'))
  await act(async () => { await vi.advanceTimersByTimeAsync(5 * 60 * 1000) })
  expect(text('error')).toBe('真实负荷回填暂时不可用')
  await visibility('hidden')
  await visibility('visible')
  expect(text('error')).toBe('')
  expect(text('loading')).toBe('false')
  expect(text('result-date')).toBe('2026-10-03')
})

it('keeps the explicit manual backtest refresh forced while also refreshing the date range', async () => {
  await enterBacktest()
  await act(async () => (host.querySelector('button:not([role="tab"])') as HTMLButtonElement).click())
  expect(apiService.getDayBacktest).toHaveBeenCalledTimes(4)
  expect(apiService.getDayBacktest).toHaveBeenLastCalledWith('2026-10-03', true)
})
