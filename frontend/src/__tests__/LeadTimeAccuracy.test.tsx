// @vitest-environment jsdom
import { act } from 'react-dom/test-utils'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { LeadTimeAccuracyPanel } from '../pages/historical/LeadTimeAccuracyPanel'
import { OverviewTab } from '../pages/historical/OverviewTab'
import type { AccuracyStats, LeadTimeAccuracyGroup, LeadTimeInputQualityMetrics } from '../types'

let root: Root
let host: HTMLDivElement
const emptyMetrics = { count: 0, mae: null, rmse: null, mape: null, bias: null, r2: null }
const quality = (quality: LeadTimeInputQualityMetrics['quality'], count = 0): LeadTimeInputQualityMetrics => ({
  ...emptyMetrics,
  quality,
  label: quality,
  count,
  mae: count ? 15 : null,
  rmse: count ? 18 : null,
  mape: count ? 0.75 : null,
})
const group = (key: LeadTimeAccuracyGroup['key'], count = 0): LeadTimeAccuracyGroup => {
  const [min_hour, max_hour] = key.split('_').map(Number)
  return {
    ...emptyMetrics,
    key,
    label: `提前 ${min_hour}–${max_hour} 小时`,
    min_hour,
    max_hour,
    count,
    mae: count ? 123.4 : null,
    rmse: count ? 234.5 : null,
    mape: count ? 1.25 : null,
    input_quality: [quality('complete', count ? 1 : 0), quality('estimated', count ? 1 : 0), quality('unknown', count ? 1 : 0)],
  }
}
const stats = (groups: LeadTimeAccuracyGroup[]): AccuracyStats => ({
  count: 15,
  mae: 50,
  rmse: 60,
  mape: 0.5,
  r2: null,
  metric_scope: 'latest_snapshot_per_target',
  lead_time_scope: 'earliest_snapshot_per_target_within_lead_group',
  lead_time_groups: groups,
})
const render = async (data: AccuracyStats | null, loading = false) => {
  await act(async () => root.render(<LeadTimeAccuracyPanel stats={data} loading={loading} />))
}

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

it('shows three independently counted horizons and actual-load metric units in the overview', async () => {
  const data = stats([group('1_6', 3), group('7_12', 3), group('13_24', 3)])
  await act(async () => root.render(<OverviewTab loading={{}} accuracyStats={data} accuracyDays={7} setAccuracyDays={() => {}} history={[]} pvHealth={null} errors={{}} refreshOverview={() => {}} />))
  const panel = host.querySelector('[aria-labelledby="lead-time-accuracy-title"]')!
  expect(panel).not.toBeNull()
  expect(panel.querySelectorAll('section[aria-label]')).toHaveLength(3)
  expect(panel.textContent).toContain('ISO-NE 实际负荷')
  expect(panel.textContent).toContain('每个目标小时的最新快照')
  expect(panel.textContent).toContain('三组小时数不可相加作为总样本数')
  for (const card of Array.from(panel.querySelectorAll('section[aria-label]'))) {
    expect(card.textContent).toContain('3 个独立目标小时')
    expect(card.textContent).toContain('MAE (MW)123.4')
    expect(card.textContent).toContain('RMSE (MW)234.5')
    expect(card.textContent).toContain('MAPE (%)1.25')
  }
})

it('keeps complete, estimated and unknown input counts visible with separate metrics in expandable details', async () => {
  await render(stats([group('1_6', 3)]))
  const card = host.querySelector('section[aria-label]')!
  const outsideDetails = Array.from(card.querySelectorAll('div')).filter(element => element.closest('details') === null).map(element => element.textContent).join('')
  expect(outsideDetails).toContain('完整输入1 个小时')
  expect(outsideDetails).toContain('估计补齐输入1 个小时')
  expect(outsideDetails).toContain('输入质量未留档1 个小时')
  const details = card.querySelector('details')!
  expect(details.open).toBe(false)
  await act(async () => details.querySelector('summary')!.click())
  expect(details.open).toBe(true)
  const rows = Array.from(details.querySelectorAll('tbody tr'))
  expect(rows).toHaveLength(3)
  expect(rows[0].textContent).toBe('完整输入115.018.00.75')
  expect(rows[1].textContent).toBe('估计补齐输入115.018.00.75')
  expect(rows[2].textContent).toBe('输入质量未留档115.018.00.75')
  expect(host.textContent).toContain('比较依据始终为实际负荷')
})

it('shows an empty paired-observation state and placeholders instead of zero errors', async () => {
  const misleadingZero = { ...group('1_6'), mae: 0, rmse: 0, mape: 0 }
  await render(stats([misleadingZero, group('7_12'), group('13_24')]))
  expect(host.querySelectorAll('dd')).toHaveLength(9)
  expect(Array.from(host.querySelectorAll('dd')).every(value => value.textContent === '--')).toBe(true)
  expect(host.querySelectorAll('details')).toHaveLength(0)
  expect(host.textContent?.match(/暂无已对齐实测/g)).toHaveLength(3)
})

it('does not derive horizon errors from latest-snapshot totals when grouping is absent', async () => {
  await render({ count: 50, mae: 20, rmse: 30, mape: 0.2, r2: null })
  expect(host.textContent).toContain('暂无按提前量统计的数据')
  expect(host.querySelectorAll('section[aria-label]')).toHaveLength(0)
  expect(host.querySelectorAll('dd')).toHaveLength(0)
})

it('hides the previous-period metrics while a new period is loading', async () => {
  await render(stats([group('1_6', 3)]), true)
  expect(host.querySelectorAll('section[aria-label]')).toHaveLength(0)
  expect(host.textContent).not.toContain('123.4')
})
