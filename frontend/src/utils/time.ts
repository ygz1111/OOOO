// ============================================================================
// 时间工具 — 统一 America/New_York（新英格兰）时区
// ============================================================================
// 后端所有时间戳都是 naive ISO（新英格兰墙钟时间，无时区后缀），例如
// "2026-08-13T02:00:00"。若直接用 new Date(iso) 解析，浏览器会把它当作
// 本地时区（如 CST）解析，导致真实时刻偏移 12 小时、图表"现在"标记和
// 小时轴全部错位。本模块把 naive ISO 解析为 America/New_York 的真实时刻
// （自动处理 EST/EDT 夏令时），并把所有展示统一格式化为 ET 墙钟时间。

const ET_TIME_ZONE = 'America/New_York'

// ET 在给定 epoch 时刻的 UTC 偏移（毫秒，EST=-5h / EDT=-4h）
function etUtcOffsetMs(epoch: number): number {
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  })
  const parts = dtf.formatToParts(new Date(epoch))
  const comps: Record<string, number> = {}
  for (const p of parts) {
    if (p.type !== 'literal') comps[p.type] = Number(p.value)
  }
  const hour = comps.hour === 24 ? 0 : comps.hour
  const asUTC = Date.UTC(
    comps.year, comps.month - 1, comps.day,
    hour, comps.minute, comps.second,
  )
  return asUTC - epoch
}

/**
 * 把后端 naive ISO（新英格兰墙钟时间）解析为真实时刻 Date。
 * 先按 UTC 构造基准 epoch，再按 ET 偏移迭代修正（两次迭代覆盖夏令时边界）。
 */
export function parseEasternISO(iso: string): Date {
  if (/(Z|[+-]\d{2}:?\d{2})$/i.test(iso)) return new Date(iso)
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):?(\d{2})?/.exec(iso)
  if (!m) return new Date(iso)
  const wallUTC = Date.UTC(
    Number(m[1]), Number(m[2]) - 1, Number(m[3]),
    Number(m[4]), Number(m[5]), Number(m[6] || 0),
  )
  let epoch = wallUTC
  for (let i = 0; i < 2; i++) {
    const next = wallUTC - etUtcOffsetMs(epoch)
    if (next === epoch) break
    epoch = next
  }
  return new Date(epoch)
}

export function forecastIntervalOpen(timestamp: string, now: number, basis: 'hour_end' | 'hour_start' = 'hour_end'): boolean {
  const startOrEnd = parseEasternISO(timestamp).getTime()
  return Number.isFinite(startOrEnd) && startOrEnd + (basis === 'hour_start' ? 3_600_000 : 0) > now
}

/** 把给定时刻按 ET 墙钟格式化显示 */
export function formatEastern(date: Date, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: ET_TIME_ZONE,
    ...options,
  }).format(date)
}

/** 后端 naive ISO → ET 墙钟显示字符串 */
export function formatEasternISO(iso: string, options?: Intl.DateTimeFormatOptions): string {
  return formatEastern(parseEasternISO(iso), options)
}

/** naive ISO 相对当前真实时刻的小时偏移（正=未来，负=过去） */
export function easternHourOffset(iso: string, nowMs: number): number {
  return Math.round((parseEasternISO(iso).getTime() - nowMs) / 3600000)
}

/**
 * 取 naive ISO 对应的东部（America/New_York）墙钟小时（0-23）。
 * 注意不能用 new Date(iso).getHours()——那返回浏览器本地时区的小时，
 * 在非 ET 时区（如北京）的整小时偏移下数值恰好巧合相同，但 DST 边界
 * 与真实语义均不可靠。统一按 ET 墙钟解析。
 */
export function easternHourOf(iso: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_TIME_ZONE,
    hour: '2-digit',
    hour12: false,
  }).formatToParts(parseEasternISO(iso))
  const h = parts.find((p) => p.type === 'hour')?.value ?? '0'
  return Number(h) % 24
}

/** 当前真实时刻对应的 ET 墙钟日期（YYYY-MM-DD，用于日期选择器缺省值兜底） */
export function easternDateISO(nowMs: number = Date.now()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: ET_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(nowMs))
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  return `${get('year')}-${get('month')}-${get('day')}`
}

// 常用格式（zh-CN + ET 时区）
export const ET_DATE_TIME: Intl.DateTimeFormatOptions = {
  month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit',
  hour12: false,
}
export const ET_TIME: Intl.DateTimeFormatOptions = {
  hour: '2-digit', minute: '2-digit', second: '2-digit',
  hour12: false,
}
export const ET_TIME_HM: Intl.DateTimeFormatOptions = {
  hour: '2-digit', minute: '2-digit',
  hour12: false,
}
export const ET_DATE: Intl.DateTimeFormatOptions = {
  year: 'numeric', month: '2-digit', day: '2-digit',
}
export const ET_FULL: Intl.DateTimeFormatOptions = {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit',
  hour12: false,
}
