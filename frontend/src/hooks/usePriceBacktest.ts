import { useCallback, useEffect, useRef, useState } from 'react'
import apiService from '../services/api'
import type { PriceBacktestData } from '../types'

type DateRange = PriceBacktestData['available_date_range']
let rangeCache: { scope: string; fetchedAt: number; range: DateRange } | undefined
let rangePending: { scope: string; promise: Promise<DateRange> } | undefined
const loadRange = (scope: string, forceRefresh = false) => {
  if (!forceRefresh && rangeCache?.scope === scope && Date.now() - rangeCache.fetchedAt < 300000) return Promise.resolve(rangeCache.range)
  if (rangePending?.scope === scope) return rangePending.promise
  const promise = apiService.getPriceBacktest().then(response => {
    const range = response.data.available_date_range
    rangeCache = { scope, fetchedAt: Date.now(), range }
    return range
  }).finally(() => { if (rangePending?.promise === promise) rangePending = undefined })
  rangePending = { scope, promise }
  return promise
}

/** Only the current date and latest request can publish a backtest result. */
export function usePriceBacktest(scope: string) {
  const [date, setDate] = useState('')
  const [range, setRange] = useState<DateRange | null>(null)
  const [data, setData] = useState<PriceBacktestData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sequence = useRef(0)
  const rangeSequence = useRef(0)
  const selectedDate = useRef('')
  const backtestStarted = useRef(false)
  const requests = useRef(new Map<string, Promise<PriceBacktestData>>())

  const initialize = useCallback(async (forceRefresh = false) => {
    const version = sequence.current
    const rangeVersion = ++rangeSequence.current
    try {
      const available = await loadRange(scope, forceRefresh)
      if (rangeVersion !== rangeSequence.current) return
      setRange(available)
      if (!selectedDate.current || !backtestStarted.current) {
        selectedDate.current = available.latest
        setDate(available.latest)
      }
      if (version === sequence.current) setError(null)
    } catch (requestError) {
      if (rangeVersion === rangeSequence.current && version === sequence.current) setError(requestError instanceof Error ? requestError.message : '电价回测日期范围加载失败')
    }
  }, [scope])

  useEffect(() => {
    selectedDate.current = ''
    backtestStarted.current = false
    setDate('')
    setRange(null)
    setData(null)
    setError(null)
    setLoading(false)
    requests.current = new Map()
    void initialize()
    return () => { sequence.current += 1; rangeSequence.current += 1 }
  }, [initialize])

  const load = useCallback(async (requestedDate: string) => {
    const version = ++sequence.current
    selectedDate.current = requestedDate
    backtestStarted.current = Boolean(requestedDate)
    setDate(requestedDate)
    setData(previous => previous?.date === requestedDate ? previous : null)
    setError(null)
    if (!requestedDate) { setLoading(false); return }
    setLoading(true)
    try {
      const activeRequests = requests.current
      let request = activeRequests.get(requestedDate)
      if (!request) {
        request = apiService.getPriceBacktest(requestedDate).then(response => response.data)
          .finally(() => { activeRequests.delete(requestedDate) })
        activeRequests.set(requestedDate, request)
      }
      const result = await request
      if (version !== sequence.current) return
      if (result.date !== requestedDate) throw new Error(`回测返回日期 ${result.date ?? '--'} 与所选日期 ${requestedDate} 不一致，请重试`)
      setRange(result.available_date_range)
      setData(result)
    } catch (requestError) {
      if (version === sequence.current) setError(requestError instanceof Error ? requestError.message : '电价历史回测加载失败')
    } finally {
      if (version === sequence.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    let polling = false
    const poll = async () => {
      if (!active || polling || document.hidden) return
      polling = true
      const version = sequence.current
      const requestedDate = selectedDate.current
      const reload = backtestStarted.current && !requests.current.has(requestedDate)
      try {
        await initialize(true)
        if (active && reload && version === sequence.current && selectedDate.current === requestedDate) {
          await load(requestedDate)
        }
      } finally {
        polling = false
      }
    }
    const timer = setInterval(() => { void poll() }, 300000)
    const onVisibility = () => { if (!document.hidden) void poll() }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      active = false
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [initialize, load])

  const refresh = useCallback(() => selectedDate.current ? load(selectedDate.current) : initialize(), [load, initialize])
  return { date, range, data, loading, error, selectDate: load, refresh }
}
