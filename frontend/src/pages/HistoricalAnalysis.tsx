import React, { useState, useEffect, useCallback, useMemo } from 'react'
import apiService from '../services/api'
import {
  PredictionRecord,
  AccuracyStats,
  ModelComparisonItem,
  TrendDataPoint,
  ErrorDistribution,
  DriftDetection,
} from '../types'
import { AnalysisTab, TABS, type SortField, type SortDirection } from './historical/shared'
import { OverviewTab } from './historical/OverviewTab'
import { HistoryTab } from './historical/HistoryTab'
import { ModelsTab } from './historical/ModelsTab'
import { TrendsTab } from './historical/TrendsTab'
import { ErrorsTab } from './historical/ErrorsTab'
import { DriftTab } from './historical/DriftTab'

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

  // 筛选参数
  const [historyLimit, setHistoryLimit] = useState(50)
  const [trendWindow, setTrendWindow] = useState<'hourly' | 'daily' | 'weekly'>('daily')
  const [trendDays, setTrendDays] = useState(7)
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

  const loadHistory = useCallback(async () => {
    setLoadingState('history', true)
    setErrorState('history', null)
    try {
      const res = await apiService.getPredictionHistory({ limit: historyLimit })
      const data = (res.data || []).slice().sort((a, b) => {
        const ta = new Date(a.prediction_timestamp).getTime()
        const tb = new Date(b.prediction_timestamp).getTime()
        if (tb !== ta) return tb - ta
        return new Date(b.target_timestamp).getTime() - new Date(a.target_timestamp).getTime()
      })
      setHistory(data)
    } catch (e) {
      setErrorState('history', e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoadingState('history', false)
    }
  }, [historyLimit])

  const loadAccuracy = useCallback(async () => {
    setLoadingState('accuracy', true)
    setErrorState('accuracy', null)
    try {
      const res = await apiService.getAccuracyStats()
      setAccuracyStats(res.data || null)
    } catch (e) {
      setErrorState('accuracy', e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoadingState('accuracy', false)
    }
  }, [])

  const loadModelComparison = useCallback(async () => {
    setLoadingState('models', true)
    setErrorState('models', null)
    try {
      const res = await apiService.compareModels(modelCompareHours)
      setModelComparison(res.data || {})
    } catch (e) {
      setErrorState('models', e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoadingState('models', false)
    }
  }, [modelCompareHours])

  const loadTrends = useCallback(async () => {
    setLoadingState('trends', true)
    setErrorState('trends', null)
    try {
      const res = await apiService.analyzeTemporalTrends(trendWindow, trendDays)
      const data = res.data as any
      setTrends(data?.trends || [])
    } catch (e) {
      setErrorState('trends', e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoadingState('trends', false)
    }
  }, [trendWindow, trendDays])

  const loadErrorDist = useCallback(async () => {
    setLoadingState('errors', true)
    setErrorState('errors', null)
    try {
      const res = await apiService.analyzeErrorDistribution(errorDays)
      setErrorDist(res.data || null)
    } catch (e) {
      setErrorState('errors', e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoadingState('errors', false)
    }
  }, [errorDays])

  const loadDrift = useCallback(async () => {
    setLoadingState('drift', true)
    setErrorState('drift', null)
    try {
      const res = await apiService.checkModelDrift()
      setDriftResult(res.data || null)
    } catch (e) {
      setErrorState('drift', e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoadingState('drift', false)
    }
  }, [])

  // 初始加载
  useEffect(() => {
    loadHistory()
    loadAccuracy()
  }, [loadHistory, loadAccuracy])

  // 光伏数据健康检测 — 依赖 history 数据
  useEffect(() => {
    if (history.length === 0) {
      setPvHealth(null)
      return
    }

    let nullCount = 0
    let negativeCount = 0
    let nightNonZeroCount = 0
    let dayZeroCount = 0
    let maxPv = 0
    let pvSum = 0
    let pvValidCount = 0
    const anomalies: string[] = []

    for (const r of history) {
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

      // 判断昼夜：根据 target_timestamp 的小时
      try {
        const ts = new Date(r.target_timestamp)
        const hour = ts.getHours()
        const isNighttime = hour < 6 || hour >= 20
        const isDaytime = hour >= 7 && hour <= 18

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

    if (nullCount > history.length * 0.5) {
      anomalies.push(`光伏数据缺失率过高: ${nullCount}/${history.length} 条记录无光伏值`)
    }
    if (negativeCount > 0) {
      anomalies.push(`发现 ${negativeCount} 条负值光伏数据（不合理）`)
    }
    if (nightNonZeroCount > history.length * 0.1) {
      anomalies.push(`夜间时段光伏非零: ${nightNonZeroCount} 条记录（应为0）`)
    }
    if (dayZeroCount > history.length * 0.3) {
      anomalies.push(`白天时段光伏为零: ${dayZeroCount} 条记录（应大于0）`)
    }
    if (maxPv > 5000) {
      anomalies.push(`光伏峰值偏高: ${maxPv.toFixed(1)} MW（请核实装机容量）`)
    }

    setPvHealth({
      totalRecords: history.length,
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

  // Tab 切换时按需加载
  useEffect(() => {
    if (activeTab === 'models' && Object.keys(modelComparison).length === 0) loadModelComparison()
    if (activeTab === 'trends' && trends.length === 0) loadTrends()
    if (activeTab === 'errors' && !errorDist) loadErrorDist()
    if (activeTab === 'drift' && !driftResult) loadDrift()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

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
      {/* 粒子背景 */}

      {/* 页面标题 — 居中 */}
      <div className="page-header-centered relative z-10">
        <h1>历史数据分析</h1>
        <p>模型性能历史记录、预测准确性追踪与综合分析报告</p>
        <div className="header-decoration" />
      </div>

      {/* Tab 导航 — 卡片式布局 */}
      <div className="tab-card-grid relative z-10" role="tablist">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`tab-card ${activeTab === tab.id ? 'tab-card-active' : ''}`}
          >
            <span className="tab-card-icon">{tab.icon}</span>
            <span className="tab-card-label">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <div className="relative z-10">
        {activeTab === 'overview' && <OverviewTab loading={loading} accuracyStats={accuracyStats} history={history} pvHealth={pvHealth} errors={errors} loadHistory={loadHistory} />}
        {activeTab === 'history' && <HistoryTab history={history} sortedHistory={sortedHistory} sortField={sortField} sortDir={sortDir} handleSort={handleSort} historyLimit={historyLimit} setHistoryLimit={setHistoryLimit} loading={loading} errors={errors} loadHistory={loadHistory} />}
        {activeTab === 'models' && <ModelsTab modelComparison={modelComparison} modelCompareHours={modelCompareHours} setModelCompareHours={setModelCompareHours} loading={loading} errors={errors} loadModelComparison={loadModelComparison} />}
        {activeTab === 'trends' && <TrendsTab trends={trends} trendWindow={trendWindow} setTrendWindow={setTrendWindow} trendDays={trendDays} setTrendDays={setTrendDays} loading={loading} errors={errors} loadTrends={loadTrends} />}
        {activeTab === 'errors' && <ErrorsTab errorDist={errorDist} errorDays={errorDays} setErrorDays={setErrorDays} loading={loading} errors={errors} loadErrorDist={loadErrorDist} />}
        {activeTab === 'drift' && <DriftTab driftResult={driftResult} loading={loading} errors={errors} loadDrift={loadDrift} />}
      </div>
    </div>
  )
}

export default HistoricalAnalysis
