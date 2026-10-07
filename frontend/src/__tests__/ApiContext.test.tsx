// @vitest-environment jsdom
import { StrictMode } from 'react'
import { act } from 'react-dom/test-utils'
import { createRoot, Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiProvider, useApi } from '../contexts/ApiContext'
import { apiService } from '../services/api'

vi.mock('../services/api', () => ({ apiService: {
  predictLoad: vi.fn(), getCurrentWeather: vi.fn(), getSystemStatus: vi.fn(), getLoadOverview: vi.fn(),
} }))

let root: Root
let host: HTMLDivElement
let current: ReturnType<typeof useApi>
function Consumer() {
  current = useApi()
  return <span>{current.overview ? 'loaded' : 'loading'}</span>
}
const render = async (key = 'dashboard') => {
  await act(async () => root.render(<StrictMode><ApiProvider><Consumer key={key} /></ApiProvider></StrictMode>))
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  vi.mocked(apiService.predictLoad).mockResolvedValue({ marker: 'prediction' } as any)
  vi.mocked(apiService.getCurrentWeather).mockResolvedValue({ marker: 'weather' } as any)
  vi.mocked(apiService.getSystemStatus).mockResolvedValue({ marker: 'system' } as any)
  vi.mocked(apiService.getLoadOverview).mockResolvedValue({ data: { marker: 'overview' } } as any)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.useRealTimers()
})

it('shares first-load requests under StrictMode and preserves data across page remounts', async () => {
  await render()
  await act(async () => { await vi.advanceTimersByTimeAsync(90000) })
  await render('load-forecast')
  expect(host.textContent).toBe('loaded')
  for (const mock of Object.values(apiService)) expect(mock).toHaveBeenCalledTimes(1)
})

it('returning before five minutes reuses data and preserves the original refresh deadline', async () => {
  await render()
  Object.defineProperty(document, 'hidden', { configurable: true, value: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await act(async () => { await vi.advanceTimersByTimeAsync(90000) })
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  for (const mock of Object.values(apiService)) expect(mock).toHaveBeenCalledTimes(1)
  expect(current.isInitialLoad.prediction).toBe(false)
  await act(async () => { await vi.advanceTimersByTimeAsync(209999) })
  expect(apiService.predictLoad).toHaveBeenCalledTimes(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  for (const mock of Object.values(apiService)) expect(mock).toHaveBeenCalledTimes(2)
})

it('a manual update retains visible data and moves the next automatic refresh deadline', async () => {
  await render()
  const old = current.prediction
  await act(async () => { await vi.advanceTimersByTimeAsync(240000) })
  let finish!: (value: any) => void
  vi.mocked(apiService.predictLoad).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  await act(async () => { void current.refreshAll(true) })
  expect(current.prediction).toBe(old)
  expect(current.isLoading.prediction).toBe(true)
  expect(current.isInitialLoad.prediction).toBe(false)
  await act(async () => { finish({ marker: 'updated' }) })
  await act(async () => { await vi.advanceTimersByTimeAsync(299999) })
  expect(apiService.predictLoad).toHaveBeenCalledTimes(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(apiService.predictLoad).toHaveBeenCalledTimes(3)
})

it('refreshes the chart with the other cards and merges concurrent refresh clicks', async () => {
  await render()
  await act(async () => { await Promise.all([current.refreshAll(), current.refreshAll()]) })
  for (const mock of Object.values(apiService)) expect(mock).toHaveBeenCalledTimes(2)
  expect(Object.values(current.isLoading).some(Boolean)).toBe(false)
})

it('manual refresh updates the shared prediction before requesting a fresh chart', async () => {
  await render()
  const order: string[] = []
  vi.mocked(apiService.predictLoad).mockImplementationOnce(async () => {
    order.push('prediction')
    return { marker: 'new' } as any
  })
  vi.mocked(apiService.getLoadOverview).mockImplementationOnce(async () => {
    order.push('overview')
    return { data: { marker: 'new' } } as any
  })
  await act(async () => { await current.refreshAll(true) })
  expect(order).toEqual(['prediction', 'overview'])
  expect(apiService.predictLoad).toHaveBeenLastCalledWith(undefined, undefined, true)
  expect(apiService.getLoadOverview).toHaveBeenLastCalledWith(true)
  expect(apiService.getCurrentWeather).not.toHaveBeenCalledWith(true)
})

it('keeps the last chart on failure, reports the error and retries only the failed resource', async () => {
  await render()
  const oldChart = current.overview
  vi.mocked(apiService.getLoadOverview).mockRejectedValueOnce(new Error('请求超时'))
  await act(async () => { await vi.advanceTimersByTimeAsync(300000) })
  expect(current.overview).toBe(oldChart)
  expect(current.errors.overview).toBe('请求超时')
  await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
  expect(apiService.getLoadOverview).toHaveBeenCalledTimes(3)
  expect(apiService.predictLoad).toHaveBeenCalledTimes(2)
  expect(current.errors.overview).toBeNull()
})

it('pauses polling in a hidden tab and refreshes on returning', async () => {
  await render()
  Object.defineProperty(document, 'hidden', { configurable: true, value: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await act(async () => { await vi.advanceTimersByTimeAsync(600000) })
  expect(apiService.getLoadOverview).toHaveBeenCalledTimes(1)
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(apiService.getLoadOverview).toHaveBeenCalledTimes(2)
})

it('continues refreshing healthy resources when another source keeps failing', async () => {
  vi.mocked(apiService.getLoadOverview).mockRejectedValue(new Error('upstream unavailable'))
  await render()
  await act(async () => { await vi.advanceTimersByTimeAsync(350000) })
  expect(apiService.predictLoad).toHaveBeenCalledTimes(2)
  expect(current.errors.overview).toBe('upstream unavailable')
})

it('retries a pending forecast without showing an HTTP error or refetching healthy resources', async () => {
  vi.mocked(apiService.predictLoad).mockResolvedValueOnce({ predictions: [], input_quality: { refresh_in_progress: true } } as any)
  await render()
  expect(current.errors.prediction).toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(apiService.predictLoad).toHaveBeenCalledTimes(2)
  expect(apiService.getCurrentWeather).toHaveBeenCalledTimes(1)
})

it('retries a completed but unavailable component and recovers without a page refresh', async () => {
  vi.mocked(apiService.predictLoad).mockResolvedValueOnce({ predictions: [], input_quality: { components: { load: { status: 'unavailable' } } } } as any)
  await render()
  await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
  expect(apiService.predictLoad).toHaveBeenCalledTimes(2)
  expect(apiService.getCurrentWeather).toHaveBeenCalledTimes(1)
  expect(current.errors.prediction).toBeNull()
})
