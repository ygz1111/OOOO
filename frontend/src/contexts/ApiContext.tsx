import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef, ReactNode } from 'react'
import { apiService } from '../services/api'
import { LoadPredictionResponse, WeatherResponse, SystemStatus, LoadOverviewData } from '../types'

interface DataState {
  prediction: LoadPredictionResponse | null
  weather: WeatherResponse | null
  systemStatus: SystemStatus | null
  overview: LoadOverviewData | null
}
type Resource = keyof DataState
type ResourceMap<T> = Record<Resource, T>
const initialData: DataState = { prediction: null, weather: null, systemStatus: null, overview: null }
const flags = (): ResourceMap<boolean> => ({ prediction: false, weather: false, systemStatus: false, overview: false })
const emptyValues = (): ResourceMap<null> => ({ prediction: null, weather: null, systemStatus: null, overview: null })

interface ApiContextType extends DataState {
  isLoading: ResourceMap<boolean>
  isInitialLoad: ResourceMap<boolean>
  lastUpdated: ResourceMap<number | null>
  errors: ResourceMap<string | null>
  loadPrediction: (forceRefresh?: boolean) => Promise<void>
  loadWeather: (forceRefresh?: boolean) => Promise<void>
  loadSystemStatus: () => Promise<void>
  loadOverview: (forceRefresh?: boolean) => Promise<void>
  refreshAll: (forceRefresh?: boolean) => Promise<void>
  clearErrors: () => void
  isConnecting: boolean
}

const ApiContext = createContext<ApiContextType | undefined>(undefined)
export const useApi = () => {
  const context = useContext(ApiContext)
  if (!context) throw new Error('useApi must be used within an ApiProvider')
  return context
}

export const ApiProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  // 页面之间共享数据，路由切换不会销毁总览结果或重新启动轮询。
  const [data, setData] = useState<DataState>(initialData)
  const [isLoading, setIsLoading] = useState(flags)
  const [errors, setErrors] = useState<ResourceMap<string | null>>(emptyValues)
  const [lastUpdated, setLastUpdated] = useState<ResourceMap<number | null>>(emptyValues)
  const failures = useRef(flags())
  const preparing = useRef(flags())
  const pending = useRef<Partial<Record<Resource, Promise<void>>>>({})
  const refreshPromise = useRef<Promise<void> | null>(null)
  const lastRefresh = useRef(0)
  const lastPollAttempt = useRef<number | null>(null)

  const load = useCallback(<K extends Resource>(key: K, fetch: () => Promise<NonNullable<DataState[K]>>): Promise<void> => {
    const existing = pending.current[key]
    if (existing) return existing
    setIsLoading(previous => ({ ...previous, [key]: true }))
    const task = (async () => {
      try {
        const result = await fetch()
        setData(previous => ({ ...previous, [key]: result }))
        setLastUpdated(previous => ({ ...previous, [key]: Date.now() }))
        setErrors(previous => ({ ...previous, [key]: null }))
        const quality = 'input_quality' in result ? result.input_quality : null
        preparing.current[key] = !!quality?.refresh_in_progress
        failures.current[key] = preparing.current[key] || Object.values(quality?.components ?? {}).some(component => component.status === 'unavailable' || component.status === 'cached')
      } catch (error) {
        preparing.current[key] = false
        failures.current[key] = true
        setErrors(previous => ({ ...previous, [key]: error instanceof Error ? error.message : '数据加载失败，请稍后重试' }))
      } finally {
        delete pending.current[key]
        setIsLoading(previous => ({ ...previous, [key]: false }))
      }
    })()
    pending.current[key] = task
    return task
  }, [])

  const loadPrediction = useCallback((force?: boolean) => load('prediction', () => apiService.predictLoad(undefined, undefined, force)), [load])
  const loadWeather = useCallback((force?: boolean) => load('weather', () => apiService.getCurrentWeather(force)), [load])
  const loadSystemStatus = useCallback(() => load('systemStatus', () => apiService.getSystemStatus()), [load])
  const loadOverview = useCallback((force?: boolean) => load('overview', async () => (await apiService.getLoadOverview(force)).data), [load])

  const refreshAll = useCallback((force?: boolean): Promise<void> => {
    if (refreshPromise.current) return refreshPromise.current
    const task = (async () => {
      // 手动刷新先更新共享预测；随后图表绕过自己的旧缓存读取同一份结果。
      // 天气下载由预测端统一触发，避免单独更新天气却继续显示旧预测。
      if (force) await loadPrediction(true)
      await Promise.all([...(force ? [] : [loadPrediction()]), loadSystemStatus(), loadOverview(force), loadWeather()])
      lastRefresh.current = Date.now()
      lastPollAttempt.current = lastRefresh.current
    })().finally(() => { refreshPromise.current = null })
    refreshPromise.current = task
    return task
  }, [loadPrediction, loadWeather, loadSystemStatus, loadOverview])

  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const pollDelay = () => Object.values(preparing.current).some(Boolean) ? 5000
      : Object.values(failures.current).some(Boolean) ? 35000 : 300000
    const remaining = () => lastPollAttempt.current == null ? 0
      : Math.max(0, lastPollAttempt.current + pollDelay() - Date.now())
    const schedule = () => {
      clearTimeout(timer)
      if (stopped || document.hidden) return
      timer = setTimeout(run, remaining())
    }
    const run = async () => {
      if (stopped || document.hidden) return
      if (remaining() > 0) {
        schedule()
        return
      }
      const failed = (Object.keys(failures.current) as Resource[]).filter(key => failures.current[key])
      if (failed.length && Date.now() - lastRefresh.current < 300000) {
        const loaders = { prediction: loadPrediction, weather: loadWeather, systemStatus: loadSystemStatus, overview: loadOverview }
        await Promise.all(failed.map(key => loaders[key]()))
      } else {
        await refreshAll()
      }
      lastPollAttempt.current = Date.now()
      clearTimeout(timer)
      schedule()
    }
    const onVisibility = () => {
      clearTimeout(timer)
      if (!document.hidden) {
        if (remaining() === 0) void run()
        else schedule()
      }
    }
    void run()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stopped = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [refreshAll, loadPrediction, loadWeather, loadSystemStatus, loadOverview])

  const clearErrors = useCallback(() => setErrors(emptyValues()), [])
  const value = useMemo<ApiContextType>(() => ({
    ...data, isLoading, errors, lastUpdated,
    isInitialLoad: { prediction: !data.prediction, weather: !data.weather, systemStatus: !data.systemStatus, overview: !data.overview },
    isConnecting: !data.prediction || !data.weather || !data.systemStatus,
    loadPrediction, loadWeather, loadSystemStatus, loadOverview, refreshAll, clearErrors,
  }), [data, isLoading, errors, lastUpdated, loadPrediction, loadWeather, loadSystemStatus, loadOverview, refreshAll, clearErrors])

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}
