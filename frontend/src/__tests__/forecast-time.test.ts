import { describe, expect, it } from 'vitest'
import { forecastIntervalOpen, parseEasternISO } from '../utils/time'

describe('hour interval contract', () => {
  it('09:40 must not expose ended HE09, but HE10 and PV HS09 remain open', () => {
    const now = Date.parse('2026-09-22T13:40:00Z')
    expect(forecastIntervalOpen('2026-09-22 09:00:00', now)).toBe(false)
    expect(forecastIntervalOpen('2026-09-22 10:00:00', now)).toBe(true)
    expect(forecastIntervalOpen('2026-09-22 09:00:00', now, 'hour_start')).toBe(true)
  })
  it('expires at the exact ending boundary and across midnight', () => {
    expect(forecastIntervalOpen('2026-09-23 00:00:00', Date.parse('2026-09-23T04:00:00Z'))).toBe(false)
    expect(forecastIntervalOpen('2026-09-23 01:00:00', Date.parse('2026-09-23T04:00:00Z'))).toBe(true)
  })
  it('respects explicit timezone offsets', () => {
    expect(parseEasternISO('2026-09-22T09:00:00-04:00').toISOString()).toBe('2026-09-22T13:00:00.000Z')
  })
})
