import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef, ReactNode } from 'react'
import { apiService } from '../services/api'
import { LoadPredictionResponse, WeatherResponse, SystemStatus } from '../types'

interface ApiContextType {
  // 数据状态
  prediction: LoadPredictionResponse | null
  weather: WeatherResponse | null
  systemStatus: SystemStatus | null

  // 加载状态（包含刷新）
  isLoading: {
    prediction: boolean
    weather: boolean
    systemStatus: boolean
  }

  // 是否为首次加载（尚无任何数据）
  isInitialLoad: {
    prediction: boolean
    weather: boolean
    systemStatus: boolean
  }

  // 最后更新时间戳
  lastUpdated: {
    prediction: number | null
    weather: number | null
    systemStatus: number | null
  }

  // 错误状态
  errors: {
    prediction: string | null
    weather: string | null
    systemStatus: string | null
  }

  // API 方法
  loadPrediction: (forceRefresh?: boolean) => Promise<void>
  loadWeather: (forceRefresh?: boolean) => Promise<void>
  loadSystemStatus: () => Promise<void>
  refreshAll: (forceRefresh?: boolean) => Promise<void>
  clearErrors: () => void
}

const ApiContext = createContext<ApiContextType | undefined>(undefined)

export const useApi = () => {
  const context = useContext(ApiContext)
  if (!context) {
    throw new Error('useApi must be used within an ApiProvider')
  }
  return context
}

interface ApiProviderProps {
  children: ReactNode
}

export const ApiProvider: React.FC<ApiProviderProps> = ({ children }) => {
  const [prediction, setPrediction] = useState<LoadPredictionResponse | null>(null)
  const [weather, setWeather] = useState<WeatherResponse | null>(null)
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)

  const [isLoading, setIsLoading] = useState({
    prediction: false,
    weather: false,
    systemStatus: false
  })

  const [errors, setErrors] = useState({
    prediction: null as string | null,
    weather: null as string | null,
    systemStatus: null as string | null
  })

  const [lastUpdated, setLastUpdated] = useState({
    prediction: null as number | null,
    weather: null as number | null,
    systemStatus: null as number | null
  })

  // 跟踪是否已获取到初始数据（用 ref 避免 useEffect 闭包陷阱）
  const hasInitialDataRef = useRef(false)
  // 跟踪是否处于初始连接阶段（首次成功获取数据之前）
  const isConnectingRef = useRef(true)

  // ── 使用 useCallback 稳定函数引用，避免 useEffect 无限重渲染 ──

  const loadPrediction = useCallback(async (forceRefresh?: boolean) => {
    setIsLoading(prev => ({ ...prev, prediction: true }))
    // 刷新时不清除旧数据，不清除旧错误（避免闪烁）

    try {
      const data = await apiService.predictLoad(undefined, undefined, forceRefresh)
      setPrediction(data)
      setLastUpdated(prev => ({ ...prev, prediction: Date.now() }))
      setErrors(prev => ({ ...prev, prediction: null }))
      hasInitialDataRef.current = true
      isConnectingRef.current = false
    } catch (error) {
      // 初始连接阶段不显示刺眼错误，只静默重试
      if (!isConnectingRef.current) {
        const message = error instanceof Error ? error.message : '预测加载失败'
        setErrors(prev => ({ ...prev, prediction: message }))
      }
    } finally {
      setIsLoading(prev => ({ ...prev, prediction: false }))
    }
  }, [])

  const loadWeather = useCallback(async (forceRefresh?: boolean) => {
    setIsLoading(prev => ({ ...prev, weather: true }))

    try {
      const data = await apiService.getCurrentWeather(forceRefresh)
      setWeather(data)
      setLastUpdated(prev => ({ ...prev, weather: Date.now() }))
      setErrors(prev => ({ ...prev, weather: null }))
      hasInitialDataRef.current = true
      isConnectingRef.current = false
    } catch (error) {
      if (!isConnectingRef.current) {
        const message = error instanceof Error ? error.message : '气象数据加载失败'
        setErrors(prev => ({ ...prev, weather: message }))
      }
    } finally {
      setIsLoading(prev => ({ ...prev, weather: false }))
    }
  }, [])

  const loadSystemStatus = useCallback(async () => {
    setIsLoading(prev => ({ ...prev, systemStatus: true }))

    try {
      const data = await apiService.getSystemStatus()
      setSystemStatus(data)
      setLastUpdated(prev => ({ ...prev, systemStatus: Date.now() }))
      setErrors(prev => ({ ...prev, systemStatus: null }))
      hasInitialDataRef.current = true
      isConnectingRef.current = false
    } catch (error) {
      if (!isConnectingRef.current) {
        const message = error instanceof Error ? error.message : '系统状态加载失败'
        setErrors(prev => ({ ...prev, systemStatus: message }))
      }
    } finally {
      setIsLoading(prev => ({ ...prev, systemStatus: false }))
    }
  }, [])

  const refreshAll = useCallback(async (forceRefresh?: boolean) => {
    await Promise.all([
      loadPrediction(forceRefresh),
      loadWeather(forceRefresh),
      loadSystemStatus()
    ])
  }, [loadPrediction, loadWeather, loadSystemStatus])

  const clearErrors = useCallback(() => {
    setErrors({
      prediction: null,
      weather: null,
      systemStatus: null
    })
  }, [])

  // 初始加载 + 自动重试机制
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null
    let retryInterval: ReturnType<typeof setInterval> | null = null

    // 首次加载数据：用短间隔重试，直到成功为止
    const startInitialRetry = () => {
      if (retryInterval) return
      // 立即尝试一次
      refreshAll()
      // 每 10 秒重试一次，直到获取到数据
      retryInterval = setInterval(async () => {
        if (hasInitialDataRef.current) {
          stopInitialRetry()
          startPolling()
          return
        }
        await refreshAll()
      }, 10000)
    }

    const stopInitialRetry = () => {
      if (retryInterval) {
        clearInterval(retryInterval)
        retryInterval = null
      }
    }

    // 正常轮询：5 分钟间隔
    const startPolling = () => {
      if (interval) return
      interval = setInterval(() => {
        refreshAll()
      }, 300000) // 5 分钟刷新
    }

    const stopPolling = () => {
      if (interval) {
        clearInterval(interval)
        interval = null
      }
    }

    // 页面可见时轮询，隐藏时暂停（节省资源 & 避免无效请求）
    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopPolling()
        stopInitialRetry()
      } else {
        if (hasInitialDataRef.current) {
          refreshAll()
          startPolling()
        } else {
          startInitialRetry()
        }
      }
    }

    startInitialRetry()
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      stopPolling()
      stopInitialRetry()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [])

  // 派生：是否为首次加载（尚无数据）— 使用 useMemo 避免每次渲染创建新对象
  const isInitialLoad = useMemo(() => ({
    prediction: prediction === null,
    weather: weather === null,
    systemStatus: systemStatus === null,
  }), [prediction, weather, systemStatus])

  // 使用 useMemo 稳定 value 引用，避免所有消费者组件不必要地重渲染
  const value: ApiContextType = useMemo(() => ({
    prediction,
    weather,
    systemStatus,
    isLoading,
    isInitialLoad,
    lastUpdated,
    errors,
    loadPrediction,
    loadWeather,
    loadSystemStatus,
    refreshAll,
    clearErrors
  }), [
    prediction,
    weather,
    systemStatus,
    isLoading,
    isInitialLoad,
    lastUpdated,
    errors,
    loadPrediction,
    loadWeather,
    loadSystemStatus,
    refreshAll,
    clearErrors
  ])

  return (
    <ApiContext.Provider value={value}>
      {children}
    </ApiContext.Provider>
  )
}
