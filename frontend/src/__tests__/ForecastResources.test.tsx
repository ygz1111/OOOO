// @vitest-environment jsdom
import { StrictMode } from 'react'
import { act } from 'react-dom/test-utils'
import { createRoot, Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createForecastResource, useForecastResource } from '../hooks/useForecastResource'
import type { LoadInputQuality } from '../types'

type Result = { marker: string; input_quality?: LoadInputQuality; historical?: { pairs: { target_time: string }[] } }
let root: Root
let host: HTMLDivElement
let current: ReturnType<typeof useForecastResource<Result>>
let fetch: ReturnType<typeof vi.fn<(force: boolean) => Promise<Result>>>
let resource: ReturnType<typeof createForecastResource<Result>>
function Consumer({ scope = 'session' }: { scope?: string }) {
  current = useForecastResource(resource, scope)
  return <span>{current.data?.marker ?? 'empty'}</span>
}
const render = async (scope = 'session') => {
  await act(async () => root.render(<StrictMode><Consumer scope={scope} /></StrictMode>))
}
beforeEach(() => {
  vi.useFakeTimers()
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  fetch = vi.fn().mockResolvedValue({ marker: 'ready' })
  resource = createForecastResource(fetch, data => data.input_quality, 'price', '加载失败')
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.useRealTimers()
})

it('merges StrictMode requests and reuses valid data after route remount', async () => {
  await render()
  expect(fetch).toHaveBeenCalledTimes(1)
  await act(async () => root.render(<span>another route</span>))
  await act(async () => { await vi.advanceTimersByTimeAsync(90000) })
  await render()
  expect(host.textContent).toBe('ready')
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('visible return at 90 seconds keeps healthy results until the original five-minute deadline', async () => {
  await render()
  Object.defineProperty(document, 'hidden', { configurable: true, value: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await act(async () => { await vi.advanceTimersByTimeAsync(90000) })
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(host.textContent).toBe('ready')
  await act(async () => { await vi.advanceTimersByTimeAsync(209999) })
  expect(fetch).toHaveBeenCalledTimes(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('returning during a retry interval does not duplicate a failed request', async () => {
  fetch.mockRejectedValueOnce(new Error('temporary source error'))
  await render()
  Object.defineProperty(document, 'hidden', { configurable: true, value: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch).toHaveBeenCalledTimes(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(34000) })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(current.error).toBeNull()
})

it('polls preparation at five seconds and then returns to five minutes', async () => {
  fetch.mockResolvedValueOnce({ marker: 'preparing', input_quality: { refresh_in_progress: true } as any })
  await render()
  await act(async () => { await vi.advanceTimersByTimeAsync(4999) })
  expect(fetch).toHaveBeenCalledTimes(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(host.textContent).toBe('ready')
  expect(fetch).toHaveBeenCalledTimes(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(299999) })
  expect(fetch).toHaveBeenCalledTimes(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(fetch).toHaveBeenCalledTimes(3)
})

it('retains previous data on failure and recovers at 35 seconds', async () => {
  await render()
  fetch.mockRejectedValueOnce(new Error('ISO-NE unavailable'))
  await act(async () => { await current.refresh() })
  expect(current.error).toBe('ISO-NE unavailable')
  expect(host.textContent).toBe('ready')
  await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
  expect(current.error).toBeNull()
  expect(current.loading).toBe(false)
  expect(fetch).toHaveBeenCalledTimes(3)
})

it.each(['cached', 'unavailable'])('retries the selected %s component without retrying a healthy component', async status => {
  fetch.mockResolvedValueOnce({ marker: status, input_quality: { components: { price: { status } } } as any })
  await render()
  await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
  expect(fetch).toHaveBeenCalledTimes(2)
  fetch.mockResolvedValueOnce({ marker: 'healthy', input_quality: { components: { pv: { status: 'unavailable' }, price: { status: 'fresh' } } } as any })
  await act(async () => { await current.refresh(); await vi.advanceTimersByTimeAsync(35000) })
  expect(fetch).toHaveBeenCalledTimes(3)
})

it('pauses hidden polling and resumes promptly on returning', async () => {
  await render()
  Object.defineProperty(document, 'hidden', { configurable: true, value: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await act(async () => { await vi.advanceTimersByTimeAsync(600000) })
  expect(fetch).toHaveBeenCalledTimes(1)
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('updates PV history after hours pass in the same mounted session and the page becomes visible', async () => {
  resource = createForecastResource(fetch, data => data.input_quality, 'pv', '加载失败')
  fetch.mockResolvedValueOnce({ marker: '01:00', historical: { pairs: [{ target_time: '2026-10-04T01:00:00-04:00' }] } })
  await render()
  expect(current.data?.historical?.pairs[0].target_time).toBe('2026-10-04T01:00:00-04:00')
  Object.defineProperty(document, 'hidden', { configurable: true, value: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await act(async () => { await vi.advanceTimersByTimeAsync(4 * 3600000) })
  expect(fetch).toHaveBeenCalledTimes(1)
  fetch.mockResolvedValueOnce({ marker: '05:00', historical: { pairs: [{ target_time: '2026-10-04T05:00:00-04:00' }] } })
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(current.data?.historical?.pairs[0].target_time).toBe('2026-10-04T05:00:00-04:00')
  expect(host.textContent).toBe('05:00')
})

it('merges manual refreshes and passes the force flag', async () => {
  await render()
  await act(async () => { await Promise.all([current.refresh(), current.refresh()]) })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch).toHaveBeenLastCalledWith(true)
  expect(current.loading).toBe(false)
})

it('isolates results between login sessions', async () => {
  await render()
  fetch.mockResolvedValueOnce({ marker: 'new-session' })
  await render('another-session')
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(host.textContent).toBe('new-session')
})
