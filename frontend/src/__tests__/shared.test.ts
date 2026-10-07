import { describe, it, expect } from 'vitest'
import { toNum, formatNumber, formatTime, getInferenceColor, MODEL_COLORS } from '../pages/historical/shared'
import { easternDateISO, parseEasternISO } from '../utils/time'

describe('toNum', () => {
  it('null/undefined -> 0', () => {
    expect(toNum(null)).toBe(0)
    expect(toNum(undefined)).toBe(0)
  })

  it('number passthrough', () => {
    expect(toNum(12.5)).toBe(12.5)
  })

  it('numeric string parsed', () => {
    expect(toNum('12.5')).toBe(12.5)
  })

  it('non-numeric string -> 0', () => {
    expect(toNum('abc')).toBe(0)
  })
})

describe('formatNumber', () => {
  it('null/undefined -> --', () => {
    expect(formatNumber(null)).toBe('--')
    expect(formatNumber(undefined)).toBe('--')
  })

  it('rounds to digits', () => {
    expect(formatNumber(3.14159, 2)).toBe('3.14')
  })

  it('non-numeric -> --', () => {
    expect(formatNumber(Number('abc'), 1)).toBe('--')
  })
})

describe('formatTime', () => {
  it('formats ISO string as ET wall-clock (zh-CN 用 / 分隔)', () => {
    const out = formatTime('2026-07-31T10:00:00')
    expect(out).toMatch(/\d{2,4}[/-]\d{2}[/-]\d{2} \d{2}:\d{2}:\d{2}/)
  })

  it('falls back to raw on invalid input', () => {
    expect(formatTime('not-a-date')).toBe('not-a-date')
  })
})

describe('getInferenceColor', () => {
  it('fast < 100ms -> success', () => expect(getInferenceColor(50)).toBe('text-success-700'))
  it('medium < 500ms -> warning', () => expect(getInferenceColor(200)).toBe('text-warning-700'))
  it('slow >= 500ms -> danger', () => expect(getInferenceColor(800)).toBe('text-danger-700'))
})

describe('MODEL_COLORS', () => {
  it('has 6 colors for up to 6 models', () => {
    expect(MODEL_COLORS.length).toBe(6)
  })
})

describe('easternDateISO', () => {
  it('returns ET wall-clock date in YYYY-MM-DD format', () => {
    expect(easternDateISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('is consistent with parseEasternISO day in ET (no browser-local off-by-one)', () => {
    // 中午 12:00 UTC：ET 仍是当天（UTC-4/5），日期不应与 UTC 相差超过 1 天
    const noonUTC = Date.UTC(2026, 7, 19, 12, 0, 0)
    const iso = easternDateISO(noonUTC)
    const back = parseEasternISO(`${iso}T12:00:00`)
    expect(back.getUTCFullYear()).toBe(2026)
    expect(Math.abs(back.getUTCDate() - 19)).toBeLessThanOrEqual(1)
  })
})
