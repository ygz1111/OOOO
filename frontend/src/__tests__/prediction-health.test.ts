import { expect, it } from 'vitest'
import type { LoadPredictionResponse, SystemStatus } from '../types'
import { predictionHealth } from '../utils/predictionHealth'

const system = { status: 'healthy' } as SystemStatus
const now = Date.parse('2026-10-01T08:30:00Z')
const prediction = (status: string) => ({ predictions: [{ timestamp: '2026-10-01T05:00:00', load_forecast_mw: 15000, pv_estimation_mw: 0, price_p50: 35 }], input_quality: {
  components: Object.fromEntries(['load', 'price', 'pv'].map(task => [task, { status }]))
} }) as unknown as LoadPredictionResponse

it('distinguishes model readiness from forecast preparation and HTTP failure', () => {
  expect(predictionHealth(system, null, null, now).text).toContain('准备中')
  const pending = prediction('fresh')
  pending.predictions = []
  pending.input_quality!.refresh_in_progress = true
  expect(predictionHealth(system, pending, null, now).text).toContain('准备中')
  expect(predictionHealth(system, prediction('fresh'), 'timeout', now).text).toContain('失败')
})

it('reports usable fresh results during a background update instead of first preparation', () => {
  const existing = prediction('fresh')
  existing.input_quality!.refresh_in_progress = true
  const health = predictionHealth(system, existing, null, now)
  expect(health.text).toBe('预测可用 · 后台更新中')
  expect(health.indicator).toBe('status-online')
  expect(health.text).not.toContain('准备中')
})

it.each([
  ['cached', '此前'],
  ['estimated_inputs', '估计'],
  ['unavailable', '不可用'],
])('keeps %s quality visible while an existing result updates', (status, notice) => {
  const existing = prediction(status)
  existing.input_quality!.refresh_in_progress = true
  const health = predictionHealth(system, existing, null, now)
  expect(health.text).toContain(notice)
  expect(health.text).toContain('后台更新中')
  expect(health.text).not.toContain('准备中')
  expect(health.text).not.toContain('系统正常')
  expect(health.indicator).toBe('status-warning')
})

it('marks cached and estimated forecasts and stops reporting healthy after targets expire', () => {
  expect(predictionHealth(system, prediction('fresh'), null, now).text).toBe('系统正常')
  expect(predictionHealth(system, prediction('cached'), null, now).text).toContain('此前')
  expect(predictionHealth(system, prediction('estimated_inputs'), null, now).text).toContain('估计')
  expect(predictionHealth(system, prediction('unavailable'), null, now).text).toContain('不可用')
  expect(predictionHealth(system, prediction('fresh'), null, now + 3600000).text).toContain('不可用')
})

it.each([false, true])('does not keep expired targets usable at the exact hour boundary (updating=%s)', updating => {
  const expired = prediction('fresh')
  expired.input_quality!.refresh_in_progress = updating
  const health = predictionHealth(system, expired, null, Date.parse('2026-10-01T09:00:00Z'))
  expect(health.indicator).toBe('status-warning')
  expect(health.text).toContain(updating ? '准备中' : '不可用')
  expect(health.text).not.toContain('预测可用')
})

it('requires a finite result as well as an open target interval', () => {
  const invalid = prediction('fresh')
  invalid.predictions[0].load_forecast_mw = Number.NaN
  invalid.predictions[0].pv_estimation_mw = null
  invalid.predictions[0].price_p50 = null
  invalid.input_quality!.refresh_in_progress = true
  expect(predictionHealth(system, invalid, null, now).text).toContain('准备中')
})

it.each([false, true])('retains input estimates even when a component reports fresh (updating=%s)', updating => {
  const existing = prediction('fresh')
  existing.input_quality!.components!.price.input_status = 'estimated_inputs'
  existing.input_quality!.refresh_in_progress = updating
  const health = predictionHealth(system, existing, null, now)
  expect(health.text).toContain('估计')
  expect(health.indicator).toBe('status-warning')
})

it('keeps service degradation and incomplete quality separate from normal operation', () => {
  const existing = prediction('fresh')
  existing.input_quality!.refresh_in_progress = true
  expect(predictionHealth({ ...system, status: 'degraded' }, existing, null, now).text).toBe('系统降级 · 后台更新中')
  delete existing.input_quality!.components!.pv
  expect(predictionHealth(system, existing, null, now).indicator).toBe('status-warning')
})

it('does not accept an unknown component state as a healthy forecast', () => {
  expect(predictionHealth(system, prediction('unknown'), null, now).text).toBe('系统降级')
})
