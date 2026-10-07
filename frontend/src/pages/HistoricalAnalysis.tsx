import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import apiService from '../services/api'
import {
  PredictionRecord,
  AccuracyStats,
  ModelComparisonItem,
  TrendDataPoint,
  ErrorDistribution,
  DriftDetection,
  DayBacktestData,
  DayBacktestRangeData,
} from '../types'
import { AnalysisTab, TABS, type SortField, type SortDirection } from './historical/shared'
import { parseEasternISO, easternHourOf, easternDateISO } from '../utils/time'
import { OverviewTab } from './historical/OverviewTab'
import { HistoryTab } from './historical/HistoryTab'
import { ModelsTab } from './historical/ModelsTab'
import { TrendsTab } from './historical/TrendsTab'
import { ErrorsTab } from './historical/ErrorsTab'
import { DriftTab } from './historical/DriftTab'
import { BacktestTab } from './historical/BacktestTab'

const HistoricalAnalysis: React.FC = () => {
  // ---- 状态管理 ----
  const [activeTab, setActiveTab] = useState<AnalysisTab>('overview')
  const [loading, setLoading] = useState<Record<string, boolean>>({})
  const [errors, setErrors] = useState<Record<string, string | null>>({})

  // 数据
  const [history, setHistory] = useState<PredictionRecord[]>([])
  const [accuracyStats, setAccuracyStats] = useState<AccuracyStats | null>(null)
  const [modelComparison, setModelComparison] = useState<Record<string, ModelComparisonItem>>({})
  const [trends, setTrends] = useState<TrendDataPoint[]>([])
  const [errorDist, setErrorDist] = useState<ErrorDistribution | null>(null)
  const [driftResult, setDriftResult] = useState<DriftDetection | null>(null)
  const [backtestDate, setBacktestDate] = useState<string | null>(null)
  const [backtestData, setBacktestData] = useState<DayBacktestData | null>(null)
  const [backtestRange, setBacktestRange] = useState<{ earliest: string | null; latest: string | null } | null>(null)

  // 日期回测请求序号：快速切换日期时丢弃过期响应，避免旧结果覆盖新选择
  const backtestReqRef = useRef(0)
  const backtestRangeReqRef = useRef(0)
  const backtestDateRef = useRef<string | null>(null)
  const requestSeqRef = useRef<Record<string, number>>({})

  // 筛选参数
  const [historyLimit, setHistoryLimit] = useState(50)
  const [accuracyDays, setAccuracyDays] = useState(7)
  const [trendWindow, setTrendWindow] = useState<'hourly' | 'daily' | 'weekly'>('hourly')
  const [trendDays, setTrendDays] = useState(1)
  const [errorDays, setErrorDays] = useState(7)
  const [modelCompareHours, setModelCompareHours] = useState(24)

  // 光伏数据健康检测状态
  const [pvHealth, setPvHealth] = useState<{
    totalRecords: number
    nullCount: number
    negativeCount: number
    nightNonZeroCount: number
    dayZeroCount: number
    maxPv: number
    avgPv: number
    anomalies: string[]
    isHealthy: boolean
  } | null>(null)

  // 排序状态
  const [sortField, setSortField] = useState<SortField>(null)
  const [sortDir, setSortDir] = useState<SortDirection>(null)

  // ---- 数据加载 ----
  const setLoadingState = (key: string, val: boolean) => {
    setLoading(prev => ({ ...prev, [key]: val }))
  }
  const setErrorState = (key: string, val: string | null) => {
    setErrors(prev => ({ ...prev, [key]: val }))
  }
  const beginRequest = (key: string) => {
    const next = (requestSeqRef.current[key] ?? 0) + 1
    requestSeqRef.current[key] = next
    return next
  }
  const isLatestRequest = (key: string, requestId: number) => requestSeqRef.current[key] === requestId

  const loadHistory = useCallback(async () => {
    const requestId = beginRequest('history')
    setLoadingState('history', true)
    setErrorState('history', null)
    try {
      const res = await apiService.getPredictionHistory({ limit: historyLimit })
      // 2026-08 优化：后端 naive 东部时间戳用 parseEasternISO 解析后排序，
      // 避免 new Date() 按浏览器本地时区解析（非整小时时区/DST 边界会错序）
      const data = (res.data || []).slice().sort((a, b) => {
        const ta = parseEasternISO(a.prediction_timestamp).getTime()
        const tb = parseEasternISO(b.prediction_timestamp).getTime()
        if (tb !== ta) return tb - ta
        return parseEasternISO(b.target_timestamp).getTime() - parseEasternISO(a.target_timestamp).getTime()
      })
      if (isLatestRequest('history', requestId)) setHistory(data)
    } catch (e) {
      if (isLatestRequest('history', requestId)) setErrorState('history', e instanceof Error ? e.message : '加载失败')
    } finally {
      if (isLatestRequest('history', requestId)) setLoadingState('history', false)
    }
  }, [historyLimit])

  const loadAccuracy = useCallback(async () => {
    const requestId = beginRequest('accuracy')
    setLoadingState('accuracy', true)
    setErrorState('accuracy', null)
    try {
      const res = await apiService.getAccuracyStats(accuracyDays)
      if (isLatestRequest('accuracy', requestId)) setAccuracyStats(res.data || null)
    } catch (e) {
      if (isLatestRequest('accuracy', requestId)) setErrorState('accuracy', e instanceof Error ? e.message : '加载失败')
    } finally {
      if (isLatestRequest('accuracy', requestId)) setLoadingState('accuracy', false)
    }
  }, [accuracyDays])

  const loadModelComparison = useCallback(async () => {
    const requestId = beginRequest('models')
    setLoadingState('models', true)
    setErrorState('models', null)
    try {
      const res = await apiService.compareModels(modelCompareHours)
      if (isLatestRequest('models', requestId)) setModelComparison(res.data || {})
    } catch (e) {
      if (isLatestRequest('models', requestId)) setErrorState('models', e instanceof Error ? e.message : '加载失败')
    } finally {
      if (isLatestRequest('models', requestId)) setLoadingState('models', false)
    }
  }, [modelCompareHours])

  const loadTrends = useCallback(async () => {
    const requestId = beginRequest('trends')
    setLoadingState('trends', true)
    setErrorState('trends', null)
    try {
      const res = await apiService.analyzeTemporalTrends(trendWindow, trendDays)
      const data = res.data as any
      if (isLatestRequest('trends', requestId)) setTrends(data?.trends || [])
    } catch (e) {
      if (isLatestRequest('trends', requestId)) setErrorState('trends', e instanceof Error ? e.message : '加载失败')
    } finally {
      if (isLatestRequest('trends', requestId)) setLoadingState('trends', false)
    }
  }, [trendWindow, trendDays])

  const loadErrorDist = useCallback(async () => {
    const requestId = beginRequest('errors')
    setLoadingState('errors', true)
    setErrorState('errors', null)
    try {
      const res = await apiService.analyzeErrorDistribution(errorDays)
      if (isLatestRequest('errors', requestId)) setErrorDist(res.data || null)
    } catch (e) {
      if (isLatestRequest('errors', requestId)) setErrorState('errors', e instanceof Error ? e.message : '加载失败')
    } finally {
      if (isLatestRequest('errors', requestId)) setLoadingState('errors', false)
    }
  }, [errorDays])

  const loadDrift = useCallback(async () => {
    const requestId = beginRequest('drift')
    setLoadingState('drift', true)
    setErrorState('drift', null)
    try {
      const res = await apiService.checkModelDrift()
      if (isLatestRequest('drift', requestId)) setDriftResult(res.data || null)
    } catch (e) {
      if (isLatestRequest('drift', requestId)) setErrorState('drift', e instanceof Error ? e.message : '加载失败')
    } finally {
      if (isLatestRequest('drift', requestId)) setLoadingState('drift', false)
    }
  }, [])

  // 任意日期历史回测：按所选日期重跑模型与真实负荷对比（重型端点，按需加载）
  const loadBacktestData = useCallback(async (d: string, forceRefresh = false) => {
    const reqId = ++backtestReqRef.current
    setLoadingState('backtest', true)
    setErrorState('backtest', null)
    try {
      const res = await apiService.getDayBacktest(d, forceRefresh)
      if (reqId === backtestReqRef.current && res.data && 'pairs' in res.data) {
        setBacktestData(res.data as DayBacktestData)
      }
    } catch (e) {
      if (reqId === backtestReqRef.current) {
        setErrorState('backtest', e instanceof Error ? e.message : '加载失败')
      }
    } finally {
      if (reqId === backtestReqRef.current) {
        setLoadingState('backtest', false)
      }
    }
  }, [])

  const loadBacktestRange = useCallback(async () => {
    const reqId = ++backtestRangeReqRef.current
    if (!backtestDateRef.current) setLoadingState('backtest', true)
    setErrorState('backtestRange', null)
    try {
      const res = await apiService.getDayBacktest()
      if (reqId !== backtestRangeReqRef.current) return
      const payload = res.data as DayBacktestRangeData | undefined
      const range = payload?.available_date_range ?? null
      setBacktestRange(range)
      // 只在首次进入时选最新一天；范围刷新不能覆盖用户已选日期。
      if (!backtestDateRef.current) {
        const defaultDate = range?.latest ?? easternDateISO()
        backtestDateRef.current = defaultDate
        setBacktestDate(defaultDate)
        setBacktestData(null)
        if (defaultDate) await loadBacktestData(defaultDate)
      }
    } catch (e) {
      if (reqId === backtestRangeReqRef.current) {
        setErrorState('backtestRange', e instanceof Error ? e.message : '加载失败')
        if (!backtestDateRef.current) setLoadingState('backtest', false)
      }
    }
  }, [loadBacktestData])

  const handleBacktestDateChange = useCallback((d: string) => {
    backtestDateRef.current = d
    setBacktestDate(d)
    setBacktestData(previous => previous?.date === d ? previous : null)
    loadBacktestData(d)
  }, [loadBacktestData])

  const refreshBacktest = useCallback(async (forceRefresh = false) => {
    const selectedDate = backtestDateRef.current
    await Promise.all([
      loadBacktestRange(),
      ...(selectedDate ? [loadBacktestData(selectedDate, forceRefresh)] : []),
    ])
  }, [loadBacktestRange, loadBacktestData])

  const refreshOverview = useCallback(async () => {
    await Promise.all([loadHistory(), loadAccuracy()])
  }, [loadHistory, loadAccuracy])

  // 光伏数据健康检测 — 依赖 history 数据
  useEffect(() => {
    if (history.length === 0) {
      setPvHealth(null)
      return
    }

    // 同一目标小时可能因页面刷新产生多条预测快照；健康检查只看最新一条。
    const latestByTarget = new Map<string, PredictionRecord>()
    for (const record of history) {
      const key = String(record.target_timestamp)
      if (!latestByTarget.has(key)) latestByTarget.set(key, record)
    }
    const pvSnapshots = Array.from(latestByTarget.values())

    let nullCount = 0
    let negativeCount = 0
    let nightNonZeroCount = 0
    let dayZeroCount = 0
    let maxPv = 0
    let pvSum = 0
    let pvValidCount = 0
    const anomalies: string[] = []

    for (const r of pvSnapshots) {
      const pv = r.pv_estimation_mw
      if (pv === null || pv === undefined) {
        nullCount++
        continue
      }
      const pvNum = Number(pv)
      if (isNaN(pvNum)) {
        nullCount++
        continue
      }

      pvValidCount++
      pvSum += pvNum
      if (pvNum > maxPv) maxPv = pvNum

      if (pvNum < 0) {
        negativeCount++
      }

      // 判断昼夜：根据 target_timestamp 的东部墙钟小时
      // 2026-08 修复：此前 new Date() 按浏览器本地时区解析 naive ET 时间戳
      try {
        const hour = easternHourOf(String(r.target_timestamp))
        // 只检查全年都可靠的核心昼夜区间，避免固定日出/日落边界在冬夏季误报。
        const isNighttime = hour <= 4 || hour >= 22
        const isDaytime = hour >= 10 && hour <= 15

        if (isNighttime && pvNum > 0.5) {
          nightNonZeroCount++
        }
        if (isDaytime && pvNum < 0.01) {
          dayZeroCount++
        }
      } catch {
        // 忽略时间解析错误
      }
    }

    const avgPv = pvValidCount > 0 ? pvSum / pvValidCount : 0

    if (nullCount > pvSnapshots.length * 0.5) {
      anomalies.push(`光伏数据缺失率过高: ${nullCount}/${pvSnapshots.length} 个目标小时无光伏值`)
    }
    if (negativeCount > 0) {
      anomalies.push(`发现 ${negativeCount} 条负值光伏数据（不合理）`)
    }
    if (nightNonZeroCount > pvSnapshots.length * 0.1) {
      anomalies.push(`夜间时段光伏非零: ${nightNonZeroCount} 条记录（应为0）`)
    }
    if (dayZeroCount > pvSnapshots.length * 0.3) {
      anomalies.push(`白天时段光伏为零: ${dayZeroCount} 条记录（应大于0）`)
    }
    setPvHealth({
      totalRecords: pvSnapshots.length,
      nullCount,
      negativeCount,
      nightNonZeroCount,
      dayZeroCount,
      maxPv,
      avgPv,
      anomalies,
      isHealthy: anomalies.length === 0,
    })
  }, [history])

  // 进入页面、切换标签或修改筛选条件时都重新请求，避免保留过期快照。
  useEffect(() => {
    if (activeTab === 'overview' || activeTab === 'history') void refreshOverview()
    if (activeTab === 'models') void loadModelComparison()
    if (activeTab === 'trends') void loadTrends()
    if (activeTab === 'errors') void loadErrorDist()
    if (activeTab === 'drift') void loadDrift()
    if (activeTab === 'backtest') void refreshBacktest()
  }, [activeTab, loadModelComparison, loadTrends, loadErrorDist, loadDrift, refreshOverview, refreshBacktest])

  // 历史数据会持续由后端回填；页面可见时每5分钟同步当前标签数据。
  useEffect(() => {
    const syncVisibleTab = () => {
      if (document.visibilityState !== 'visible') return
      if (activeTab === 'overview' || activeTab === 'history') void refreshOverview()
      if (activeTab === 'models') void loadModelComparison()
      if (activeTab === 'trends') void loadTrends()
      if (activeTab === 'errors') void loadErrorDist()
      if (activeTab === 'drift') void loadDrift()
      if (activeTab === 'backtest') void refreshBacktest()
    }
    const timer = window.setInterval(syncVisibleTab, 5 * 60 * 1000)
    document.addEventListener('visibilitychange', syncVisibleTab)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', syncVisibleTab)
    }
  }, [activeTab, refreshOverview, loadModelComparison, loadTrends, loadErrorDist, loadDrift, refreshBacktest])

  // ---- 排序逻辑 ----
  const handleSort = (field: string) => {
    if (sortField === field) {
      if (sortDir === 'asc') setSortDir('desc')
      else if (sortDir === 'desc') { setSortField(null); setSortDir(null) }
      else setSortDir('asc')
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }

  const sortedHistory = useMemo(() => {
    if (!sortField || !sortDir) return history
    const sorted = [...history].sort((a: any, b: any) => {
      const av = a[sortField]
      const bv = b[sortField]
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortDir === 'asc' ? av - bv : bv - av
      }
      const as = String(av)
      const bs = String(bv)
      return sortDir === 'asc' ? as.localeCompare(bs) : bs.localeCompare(as)
    })
    return sorted
  }, [history, sortField, sortDir])

  // ---- 主渲染 ----
  return (
    <div className="space-y-6 animate-fade-in relative">
      <div className="page-header relative z-10">
        <div className="page-title-block">
          <h1>历史数据分析</h1>
          <p>在线预测记录、历史回测、误差统计及模型版本比较。</p>
        </div>
      </div>

      {/* Tab 导航 — 卡片式布局 */}
      <div className="tab-card-grid relative z-10" role="tablist" aria-label="历史分析功能">
        {TABS.map(tab => (
          <button
            key={tab.id}
            id={`historical-tab-${tab.id}`}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls="historical-analysis-panel"
            className={`tab-card ${activeTab === tab.id ? 'tab-card-active' : ''}`}
          >
            <span className="tab-card-icon">{tab.icon}</span>
            <span className="tab-card-label">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <div id="historical-analysis-panel" role="tabpanel" aria-labelledby={`historical-tab-${activeTab}`} className="relative z-10 min-w-0">
        {/* 2026-08 优化：数据口径说明，避免"历史记录 vs 24h 负荷图回测"数值不一致的困惑 */}
        <details className="data-scope-note mb-4">
          <summary className="data-scope-note-summary">
            <span className="data-scope-note-title">数据口径说明</span>
            <span className="data-scope-note-preview">在线快照记录当时预测；历史回测使用事后气象</span>
          </summary>
          <p className="data-scope-note-body">
            本页"历史记录"为每次预测请求入库的<b>实时快照</b>（同一时刻可能多次预测、含回填的
            ISO-NE 实际负荷）；24h 负荷图中的“历史回测”是事后用<b>历史气象回放</b>重新调用模型得到的
            验证值。两者预测口径不同，数值差异属正常。实际负荷仅在 ISO-NE 发布后回填（当天数据滞后约 1 小时）。
          </p>
        </details>
        {activeTab === 'overview' && <OverviewTab loading={loading} accuracyStats={accuracyStats} accuracyDays={accuracyDays} setAccuracyDays={setAccuracyDays} history={history} pvHealth={pvHealth} errors={errors} refreshOverview={refreshOverview} />}
        {activeTab === 'history' && <HistoryTab history={history} sortedHistory={sortedHistory} sortField={sortField} sortDir={sortDir} handleSort={handleSort} historyLimit={historyLimit} setHistoryLimit={setHistoryLimit} loading={loading} errors={errors} loadHistory={loadHistory} />}
        {activeTab === 'models' && <ModelsTab modelComparison={modelComparison} modelCompareHours={modelCompareHours} setModelCompareHours={setModelCompareHours} loading={loading} errors={errors} loadModelComparison={loadModelComparison} />}
        {activeTab === 'trends' && <TrendsTab trends={trends} trendWindow={trendWindow} setTrendWindow={setTrendWindow} trendDays={trendDays} setTrendDays={setTrendDays} loading={loading} errors={errors} loadTrends={loadTrends} />}
        {activeTab === 'errors' && <ErrorsTab errorDist={errorDist} errorDays={errorDays} setErrorDays={setErrorDays} loading={loading} errors={errors} loadErrorDist={loadErrorDist} />}
        {activeTab === 'drift' && <DriftTab driftResult={driftResult} loading={loading} errors={errors} loadDrift={loadDrift} />}
        {activeTab === 'backtest' && <BacktestTab date={backtestDate} range={backtestRange} data={backtestData} loading={!!loading['backtest']} error={errors['backtest'] ?? errors['backtestRange'] ?? null} onDateChange={handleBacktestDateChange} onRefresh={() => refreshBacktest(true)} />}
      </div>
    </div>
  )
}

export default HistoricalAnalysis
