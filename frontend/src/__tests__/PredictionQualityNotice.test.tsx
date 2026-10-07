// @vitest-environment jsdom
import { act } from 'react-dom/test-utils'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import PredictionQualityNotice from '../components/PredictionQualityNotice'
import type { LoadInputQuality } from '../types'

let root: Root
let host: HTMLDivElement
const quality = (overrides: Partial<LoadInputQuality> = {}): LoadInputQuality => ({
  origin_lag_hours: 0,
  day_ahead_imputed: [],
  partial_pv_hours: [],
  pv_minimum_samples_per_zone: 8,
  ...overrides,
})
const render = async (value?: LoadInputQuality | null, task?: string) => {
  await act(async () => root.render(<PredictionQualityNotice quality={value} task={task} />))
}
const isOutsideDetails = (element: Element | null) => element !== null && element.closest('details') === null

beforeEach(() => {
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
})

it('renders no quality panel when quality is absent', async () => {
  await render(null)
  expect(host.childElementCount).toBe(0)
})

it('keeps the core notice, original cache generation, estimate marker and failure reasons outside details', async () => {
  await render(quality({
    notice: '最新资料获取失败，保留仍有效的预测。',
    components: {
      load: { status: 'cached', input_status: 'estimated_inputs', generated_at: '2026-10-01T08:00:00', notice: '仅保留尚未结束时段', reason: '电网历史暂未更新' },
      price: { status: 'unavailable', notice: '数据不足，暂不提供电价预测', reason: 'RT-LMP 缺失' },
    },
  }))
  const rows = Array.from(host.querySelectorAll('.quality-component-row'))
  expect(rows[0].textContent).toContain('负荷沿用此前预测原预测含估计输入')
  expect(rows[0].textContent).toContain('原预测生成于')
  expect(rows[0].querySelector('time')?.getAttribute('datetime')).toBe('2026-10-01T08:00:00')
  expect(rows[0].textContent).toContain('08:00（ET）')
  expect(rows[0].textContent).toContain('电网历史暂未更新')
  expect(rows[1].textContent).toContain('电价暂不可用')
  expect(rows[1].textContent).toContain('RT-LMP 缺失')
  expect(isOutsideDetails(host.querySelector('.quality-status-header'))).toBe(true)
  expect(rows.every(isOutsideDetails)).toBe(true)
  expect(host.querySelector('.quality-status-panel')?.getAttribute('data-tone')).toBe('unavailable')
  expect(rows[0].getAttribute('data-tone')).toBe('caution')
})

it('shows short estimation and incomplete observation warnings before any collapsed explanation', async () => {
  await render(quality({
    components: { load: { status: 'estimated_inputs' } },
    estimated_inputs: [{ field: 'load_mw', target_time: '2026-10-01T08:00:00', source_time: '2026-09-30T08:00:00', method: 'same_hour_persistence' }],
    day_ahead_imputed: [{ field: 'da_lmp', target_time: '2026-10-01T09:00:00', source_time: '2026-09-30T09:00:00', method: 'same_hour_persistence' }],
    rt_lmp_derived_hours: [{ time: '2026-10-01T07:00:00', samples_per_hour: 12 }],
    partial_load_hours: [{ time: '2026-10-01T08:00:00', samples_per_zone: 8 }],
  }), 'load')
  const summary = host.querySelector('.quality-summary')
  expect(isOutsideDetails(summary)).toBe(true)
  expect(summary?.textContent).toContain('昨日同小时观测补齐')
  expect(summary?.textContent).toContain('估计值不计作实测')
  expect(summary?.textContent).toContain('未发布的日前输入')
  expect(summary?.textContent).toContain('五分钟聚合')
  expect(summary?.textContent).toContain('不作为官方小时实测计算误差')
  expect(summary?.textContent).toContain('采样不足12次')
  expect(host.querySelector('.quality-status-panel')?.getAttribute('data-tone')).toBe('caution')
})

it('filters market failures and market estimates out of a healthy PV panel', async () => {
  const value = quality({
    components: { load: { status: 'cached' }, price: { status: 'unavailable', reason: 'RT-LMP 缺失' }, pv: { status: 'fresh' } },
    estimated_inputs: [{ field: 'load_mw', target_time: '2026-10-01T08:00:00', source_time: '2026-09-30T08:00:00', method: 'same_hour_persistence' }],
    partial_load_hours: [{ time: '2026-10-01T08:00:00', samples_per_zone: 8 }],
    rt_lmp_derived_hours: [{ time: '2026-10-01T07:00:00', samples_per_hour: 12 }],
  })
  await render(value, 'pv')
  expect(host.querySelectorAll('.quality-component-row')).toHaveLength(1)
  expect(host.textContent).toContain('光伏本次预测')
  expect(host.textContent).not.toContain('RT-LMP 缺失')
  expect(host.querySelector('.quality-summary')).toBeNull()
  expect(host.querySelector('.quality-status-panel')?.getAttribute('data-tone')).toBe('ready')
  await render({ ...value, partial_pv_hours: [{ time: '2026-10-01T08:00:00', samples_per_zone: 8 }] }, 'pv')
  expect(host.querySelector('.quality-status-panel')?.getAttribute('data-tone')).toBe('caution')
  expect(host.querySelector('.quality-summary')?.textContent).toContain('光伏 1 个小时')
})

it('distinguishes preparation from a completed failure and keeps native source details expandable', async () => {
  await render(quality({ refresh_in_progress: true, components: { price: { status: 'unavailable', notice: '首次准备数据中' } } }), 'price')
  expect(host.querySelector('.quality-status-panel')?.getAttribute('data-tone')).toBe('preparing')
  expect(host.textContent).toContain('首次准备数据中')
  await render(quality({ components: { price: { status: 'fresh', observed_through: '2026-10-01T07:00:00' } }, coverage_hours: 24 }), 'price')
  const details = host.querySelector('details')!
  expect(details.open).toBe(false)
  expect(details.querySelector('summary')?.textContent).toBe('数据来源与时间说明')
  expect(details.textContent).toContain('电价观测截至')
  expect(details.textContent).toContain('24 个小时区间')
  await act(async () => details.querySelector('summary')!.click())
  expect(details.open).toBe(true)
  await act(async () => details.querySelector('summary')!.click())
  expect(details.open).toBe(false)
  expect(host.querySelector('.quality-status-panel')?.getAttribute('data-tone')).toBe('ready')
})
