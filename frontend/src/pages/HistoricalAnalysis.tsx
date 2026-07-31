import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Cell
} from 'recharts'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import MetricCard from '../components/MetricCard'
import { Spinner, EmptyState, ErrorBanner } from '../components/Skeleton'
import { RefreshButton } from '../components/ui/MicroInteractions'
import ParticleField from '../components/ui/ParticleField'
import apiService from '../services/api'
import {
  PredictionRecord,
  AccuracyStats,
  ModelComparisonItem,
  TrendDataPoint,
  ErrorDistribution,
  DriftDetection,
} from '../types'
import {
  TrendingUp, BarChart3, Database, Activity, Clock,
  AlertTriangle, CheckCircle,
  Target, Zap, Gauge, Wind,
  ChevronUp, ChevronDown, ChevronsUpDown,
  Check,
  AlertCircle, Sun,
} from 'lucide-react'

// ========================================
// Tab 定义
// ========================================
type AnalysisTab = 'overview' | 'history' | 'models' | 'trends' | 'errors' | 'drift'

const TABS: { id: AnalysisTab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: '概览', icon: <Gauge className="w-4 h-4" /> },
  { id: 'history', label: '历史记录', icon: <Database className="w-4 h-4" /> },
  { id: 'models', label: '模型对比', icon: <BarChart3 className="w-4 h-4" /> },
  { id: 'trends', label: '趋势分析', icon: <TrendingUp className="w-4 h-4" /> },
  { id: 'errors', label: '误差分布', icon: <Target className="w-4 h-4" /> },
  { id: 'drift', label: '模型漂移', icon: <Activity className="w-4 h-4" /> },
]

const MODEL_COLORS = ['#3B82F6', '#10B981', '#f59e0b', '#a855f7', '#ec4899', '#14b8a6']

// ── 排序类型 ──
type SortDirection = 'asc' | 'desc' | null
type SortField = string | null

// ── 耗时颜色映射 ──
const getInferenceColor = (ms: number): string => {
  if (ms < 100) return 'text-success-400'
  if (ms < 500) return 'text-warning-400'
  return 'text-danger-400'
}

// ── 模型标签 ──
const ModelTag: React.FC<{ model: string }> = ({ model }) => {
  const isEnsemble = model.toLowerCase().includes('ensemble')
  return (
    <span className={`model-tag ${isEnsemble ? 'model-tag-ensemble' : ''}`}>
      {model}
    </span>
  )
}

// ── 状态徽标 ──
const StatusBadge: React.FC<{ type: 'success' | 'warning' | 'danger'; label: string }> = ({ type, label }) => {
  const icons = {
    success: <Check className="w-3 h-3" />,
    warning: <AlertCircle className="w-3 h-3" />,
    danger: <AlertTriangle className="w-3 h-3" />,
  }
  return (
    <span className={`badge badge-${type}`}>
      {icons[type]}
      {label}
    </span>
  )
}

// ── 排序表头组件 ──
interface SortableThProps {
  field: string
  currentField: SortField
  currentDir: SortDirection
  onSort: (field: string) => void
  children: React.ReactNode
  align?: 'left' | 'right' | 'center'
}

const SortableTh: React.FC<SortableThProps> = ({ field, currentField, currentDir, onSort, children, align = 'left' }) => {
  const isActive = currentField === field
  const alignClass = align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
  return (
    <th scope="col" className={`th-sortable py-2 px-3 font-medium ${alignClass} ${isActive ? 'text-blue-400' : 'text-dark-400'}`}>
      <span
        className="inline-flex items-center gap-1 cursor-pointer"
        onClick={() => onSort(field)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') onSort(field) }}
      >
        {children}
        {isActive ? (
          currentDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronsUpDown className="w-3 h-3 opacity-40" />
        )}
      </span>
    </th>
  )
}

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

  // ---- 工具函数 ----
  const toNum = (val: any): number => {
    if (val === null || val === undefined) return 0
    const n = Number(val)
    return isNaN(n) ? 0 : n
  }

  const formatNumber = (val: number | null | undefined, digits = 2): string => {
    if (val === null || val === undefined) return '--'
    const n = Number(val)
    if (isNaN(n)) return '--'
    return n.toFixed(digits)
  }

  const formatTime = (isoStr: string): string => {
    try {
      return format(new Date(isoStr), 'MM-dd HH:mm:ss', { locale: zhCN })
    } catch {
      return isoStr
    }
  }

  // ---- 派生计算 ----
  const totalPredictions = history.length
  const cacheHitRate = history.length > 0
    ? (history.filter(r => r.cache_hit).length / history.length) * 100
    : 0

  // 风电统计
  const windRecords = history.filter(r => r.wind_estimation_mw != null)
  const avgWindMw = windRecords.length > 0
    ? windRecords.reduce((sum, r) => sum + toNum(r.wind_estimation_mw), 0) / windRecords.length
    : 0
  const maxWindMw = windRecords.length > 0
    ? Math.max(...windRecords.map(r => toNum(r.wind_estimation_mw)))
    : 0

  // 光伏统计
  const pvRecords = history.filter(r => r.pv_estimation_mw != null)
  const avgPvMw = pvRecords.length > 0
    ? pvRecords.reduce((sum, r) => sum + toNum(r.pv_estimation_mw), 0) / pvRecords.length
    : 0
  const maxPvMw = pvRecords.length > 0
    ? Math.max(...pvRecords.map(r => toNum(r.pv_estimation_mw)))
    : 0

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

  // ---- 渲染：概览 Tab ----
  const renderOverview = () => (
    <div className="space-y-6 animate-fade-in">
      {/* 核心指标 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="stagger-item stagger-1 h-full hover-lift">
          <MetricCard
            title="预测总记录数"
            value={loading.accuracy ? '--' : (accuracyStats?.count ?? totalPredictions)}
            icon={<Database className="w-5 h-5 text-primary-500" />}
            className="bg-gradient-to-br from-primary-500/10 to-blue-500/10 border-primary-500/20"
          />
        </div>
        <div className="stagger-item stagger-2 h-full hover-lift">
          <MetricCard
            title="MAPE (平均百分比误差)"
            value={loading.accuracy ? '--' : formatNumber(accuracyStats?.mape, 2)}
            unit="%"
            icon={<Target className="w-5 h-5 text-warning-500" />}
            trend={accuracyStats?.mape != null ? 'stable' : undefined}
            trendValue={accuracyStats?.mape != null
              ? (toNum(accuracyStats.mape) < 5 ? '优秀' : toNum(accuracyStats.mape) < 10 ? '良好' : '需关注')
              : undefined}
            className="bg-gradient-to-br from-warning-500/10 to-orange-500/10 border-warning-500/20"
          />
        </div>
        <div className="stagger-item stagger-3 h-full hover-lift">
          <MetricCard
            title="RMSE (均方根误差)"
            value={loading.accuracy ? '--' : formatNumber(accuracyStats?.rmse, 1)}
            unit="MW"
            icon={<Activity className="w-5 h-5 text-load-500" />}
            className="bg-gradient-to-br from-load-500/10 to-load-600/10 border-load-500/20"
          />
        </div>
        <div className="stagger-item stagger-4 h-full hover-lift">
          <MetricCard
            title="缓存命中率"
            value={formatNumber(cacheHitRate, 1)}
            unit="%"
            icon={<Zap className="w-5 h-5 text-success-500" />}
            trend={cacheHitRate > 50 ? 'up' : 'stable'}
            trendValue={cacheHitRate > 50 ? '高效' : '可优化'}
            className="bg-gradient-to-br from-success-500/10 to-green-500/10 border-success-500/20"
          />
        </div>
        <div className="stagger-item stagger-5 h-full hover-lift">
          <MetricCard
            title="风电均值 / 峰值"
            value={formatNumber(avgWindMw, 1)}
            unit="MW"
            icon={<Wind className="w-5 h-5 text-cyan-500" />}
            trendValue={`峰值 ${formatNumber(maxWindMw, 1)} MW`}
            className="bg-gradient-to-br from-cyan-500/10 to-teal-500/10 border-cyan-500/20"
          />
        </div>
        <div className="stagger-item stagger-6 h-full hover-lift">
          <MetricCard
            title="光伏均值 / 峰值"
            value={formatNumber(avgPvMw, 1)}
            unit="MW"
            icon={<Sun className="w-5 h-5 text-amber-500" />}
            trendValue={`峰值 ${formatNumber(maxPvMw, 1)} MW`}
            className="bg-gradient-to-br from-amber-500/10 to-orange-500/10 border-amber-500/20"
          />
        </div>
      </div>

      {/* MAPE 评级徽标行 */}
      {accuracyStats?.mape != null && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm text-dark-400">MAPE 评级：</span>
          {toNum(accuracyStats.mape) < 5 ? (
            <StatusBadge type="success" label="优秀" />
          ) : toNum(accuracyStats.mape) < 10 ? (
            <StatusBadge type="warning" label="良好" />
          ) : (
            <StatusBadge type="danger" label="需关注" />
          )}
          <span className="w-px h-4 bg-dark-600" />
          <span className="text-sm text-dark-400">缓存状态：</span>
          {cacheHitRate > 50 ? (
            <StatusBadge type="success" label="高效" />
          ) : (
            <StatusBadge type="warning" label="可优化" />
          )}
        </div>
      )}

      {/* 光伏数据健康检测 */}
      {pvHealth && (
        <div className={`card tech-grid-bg border-l-4 ${pvHealth.isHealthy ? 'border-l-success-500' : 'border-l-warning-500'}`}>
          <div className="card-header">
            <div className={`card-header-icon ${pvHealth.isHealthy ? 'bg-success-500/15' : 'bg-warning-500/15'}`}>
              <Sun className={`w-5 h-5 ${pvHealth.isHealthy ? 'text-success-400' : 'text-warning-400'}`} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">光伏历史数据健康检测</h2>
              <p className="card-header-subtitle">自动检测光伏估算数据是否存在异常</p>
            </div>
            <div className="ml-auto">
              {pvHealth.isHealthy ? (
                <StatusBadge type="success" label="数据正常" />
              ) : (
                <StatusBadge type="warning" label={`发现 ${pvHealth.anomalies.length} 项异常`} />
              )}
            </div>
          </div>

          <div className="p-4 space-y-4">
            {/* 统计指标 */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {[
                { label: '总记录数', value: pvHealth.totalRecords, color: 'text-white' },
                { label: '缺失值', value: pvHealth.nullCount, color: pvHealth.nullCount > 0 ? 'text-warning-400' : 'text-success-400' },
                { label: '负值数', value: pvHealth.negativeCount, color: pvHealth.negativeCount > 0 ? 'text-danger-400' : 'text-success-400' },
                { label: '夜间非零', value: pvHealth.nightNonZeroCount, color: pvHealth.nightNonZeroCount > 0 ? 'text-warning-400' : 'text-success-400' },
                { label: '峰值 (MW)', value: pvHealth.maxPv.toFixed(1), color: 'text-primary-400' },
                { label: '均值 (MW)', value: pvHealth.avgPv.toFixed(1), color: 'text-primary-400' },
              ].map((stat, i) => (
                <div key={i} className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 hover-lift">
                  <p className="text-dark-400 text-xs mb-1">{stat.label}</p>
                  <p className={`text-lg font-bold ${stat.color}`}>{stat.value}</p>
                </div>
              ))}
            </div>

            {/* 异常列表 */}
            {pvHealth.anomalies.length > 0 ? (
              <div className="space-y-2">
                {pvHealth.anomalies.map((anomaly, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-warning-300 bg-warning-500/5 rounded-lg p-3 border border-warning-500/20">
                    <AlertTriangle className="w-4 h-4 text-warning-400 flex-shrink-0 mt-0.5" />
                    <span>{anomaly}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-success-300 bg-success-500/5 rounded-lg p-3 border border-success-500/20">
                <CheckCircle className="w-4 h-4 text-success-400 flex-shrink-0" />
                <span>光伏历史数据检测通过，未发现异常。数据符合昼夜规律，无负值或缺失。</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 最近预测记录 */}
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <Clock className="w-5 h-5 text-primary-400" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">最近预测记录</h2>
            <p className="card-header-subtitle">最新 {Math.min(history.length, 10)} 条预测数据</p>
          </div>
          <RefreshButton onClick={loadHistory} isLoading={loading.history} className="ml-auto" />
        </div>

        {errors.history ? (
          <ErrorBanner message={errors.history} onRetry={loadHistory} />
        ) : loading.history ? (
          <Spinner size="lg" />
        ) : history.length === 0 ? (
          <EmptyState
            icon={<Database className="w-12 h-12" />}
            title="暂无历史预测数据"
            description="请先执行预测操作以生成历史记录"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm table-zebra">
              <thead>
                <tr className="text-dark-400 border-b border-dark-600">
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">预测时间</th>
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">目标时间</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">预测负荷 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">光伏 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">风电 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">净负荷 (MW)</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium">模型</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">耗时 (ms)</th>
                </tr>
              </thead>
              <tbody>
                {history.slice(0, 10).map((record) => (
                  <tr key={record.id} className="border-b border-dark-700">
                    <td className="py-2.5 px-3 text-dark-300 whitespace-nowrap">{formatTime(record.prediction_timestamp)}</td>
                    <td className="py-2.5 px-3 text-dark-300 whitespace-nowrap">{formatTime(record.target_timestamp)}</td>
                    <td className="py-2.5 px-3 text-right text-white font-medium">{toNum(record.load_forecast_mw).toFixed(1)}</td>
                    <td className="py-2.5 px-3 text-right text-success-400">{record.pv_estimation_mw != null ? toNum(record.pv_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2.5 px-3 text-right text-cyan-400">{record.wind_estimation_mw != null ? toNum(record.wind_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2.5 px-3 text-right text-warning-400">{record.net_load_mw != null ? toNum(record.net_load_mw).toFixed(1) : '--'}</td>
                    <td className="py-2.5 px-3 text-center">
                      <ModelTag model={record.model_type} />
                    </td>
                    <td className={`py-2.5 px-3 text-right font-mono ${getInferenceColor(toNum(record.inference_time_ms))}`}>
                      {record.inference_time_ms != null ? toNum(record.inference_time_ms).toFixed(0) : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )

  // ---- 渲染：历史记录 Tab ----
  const renderHistory = () => (
    <div className="space-y-4">
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <Database className="w-5 h-5 text-primary-400" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">历史预测记录</h2>
            <p className="card-header-subtitle">浏览全部历史预测数据</p>
          </div>
          <div className="flex items-center gap-3 ml-auto">
            <select
              value={historyLimit}
              onChange={(e) => setHistoryLimit(Number(e.target.value))}
              className="select-dark !py-1.5"
            >
              <option value={20}>最近 20 条</option>
              <option value={50}>最近 50 条</option>
              <option value={100}>最近 100 条</option>
              <option value={200}>最近 200 条</option>
            </select>
            <RefreshButton onClick={loadHistory} isLoading={loading.history} />
          </div>
        </div>

        {errors.history ? (
          <ErrorBanner message={errors.history} onRetry={loadHistory} />
        ) : loading.history ? (
          <Spinner size="lg" />
        ) : history.length === 0 ? (
          <EmptyState icon={<Database className="w-12 h-12" />} title="暂无历史预测数据" />
        ) : (
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto rounded-lg">
            <table className="w-full text-sm table-zebra">
              <thead className="sticky top-0 z-10 bg-dark-800/95">
                <tr className="text-dark-400 border-b border-dark-600">
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">ID</th>
                  <SortableTh field="prediction_timestamp" currentField={sortField} currentDir={sortDir} onSort={handleSort}>预测时间</SortableTh>
                  <SortableTh field="target_timestamp" currentField={sortField} currentDir={sortDir} onSort={handleSort}>目标时间</SortableTh>
                  <SortableTh field="load_forecast_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">预测负荷</SortableTh>
                  <SortableTh field="pv_estimation_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">光伏</SortableTh>
                  <SortableTh field="wind_estimation_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">风电</SortableTh>
                  <SortableTh field="net_load_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">净负荷</SortableTh>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">置信下限</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">置信上限</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium">模型</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium">缓存</th>
                  <SortableTh field="inference_time_ms" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">耗时</SortableTh>
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">数据源</th>
                </tr>
              </thead>
              <tbody>
                {sortedHistory.map((r) => (
                  <tr key={r.id} className="border-b border-dark-700">
                    <td className="py-2 px-3 text-dark-400">{r.id}</td>
                    <td className="py-2 px-3 text-dark-300 whitespace-nowrap">{formatTime(r.prediction_timestamp)}</td>
                    <td className="py-2 px-3 text-dark-300 whitespace-nowrap">{formatTime(r.target_timestamp)}</td>
                    <td className="py-2 px-3 text-right text-white font-medium">{toNum(r.load_forecast_mw).toFixed(1)}</td>
                    <td className="py-2 px-3 text-right text-success-400">{r.pv_estimation_mw != null ? toNum(r.pv_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-cyan-400">{r.wind_estimation_mw != null ? toNum(r.wind_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-warning-400">{r.net_load_mw != null ? toNum(r.net_load_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-dark-400">{r.confidence_lower_mw != null ? toNum(r.confidence_lower_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-dark-400">{r.confidence_upper_mw != null ? toNum(r.confidence_upper_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-center">
                      <ModelTag model={r.model_type} />
                    </td>
                    <td className="py-2 px-3 text-center">
                      {r.cache_hit ? (
                        <CheckCircle className="w-4 h-4 text-success-500 mx-auto" />
                      ) : (
                        <span className="text-dark-500 text-xs">--</span>
                      )}
                    </td>
                    <td className={`py-2 px-3 text-right font-mono ${getInferenceColor(toNum(r.inference_time_ms))}`}>
                      {r.inference_time_ms != null ? toNum(r.inference_time_ms).toFixed(0) : '--'}
                    </td>
                    <td className="py-2 px-3 text-dark-400 text-xs">{r.data_source ?? '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )

  // ---- 渲染：模型对比 Tab ----
  const renderModels = () => {
    const models = Object.entries(modelComparison).filter(([, item]) => item != null)
    const chartData = models.map(([name, item]) => ({
      name,
      mape: toNum(item?.mape),
      rmse: toNum(item?.rmse),
      mae: toNum(item?.mae),
      count: item?.count ?? 0,
      inferenceTime: toNum(item?.avg_inference_time_ms),
    }))

    return (
      <div className="space-y-4 animate-fade-in">
        <div className="card tech-grid-bg">
          <div className="card-header">
            <div className="card-header-icon bg-primary-500/15">
              <BarChart3 className="w-5 h-5 text-primary-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">多模型预测对比</h2>
              <p className="card-header-subtitle">对比不同模型在最近 {modelCompareHours} 小时的预测表现</p>
            </div>
            <div className="flex items-center gap-3 ml-auto">
              <select
                value={modelCompareHours}
                onChange={(e) => setModelCompareHours(Number(e.target.value))}
                className="select-dark !py-1.5"
              >
                <option value={6}>最近 6 小时</option>
                <option value={24}>最近 24 小时</option>
                <option value={72}>最近 3 天</option>
                <option value={168}>最近 7 天</option>
              </select>
              <RefreshButton onClick={loadModelComparison} isLoading={loading.models} />
            </div>
          </div>

          {errors.models ? (
            <ErrorBanner message={errors.models} onRetry={loadModelComparison} />
          ) : loading.models ? (
            <Spinner size="lg" />
          ) : chartData.length === 0 ? (
            <EmptyState icon={<BarChart3 className="w-12 h-12" />} title="暂无模型对比数据" />
          ) : (
            <>
              <div className="mb-6">
                <h3 className="text-sm font-medium text-dark-300 mb-3">MAPE 对比 (越低越好)</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
                    <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }} labelStyle={{ color: '#cbd5e1' }} />
                    <Bar dataKey="mape" name="MAPE (%)" radius={[4, 4, 0, 0]}>
                      {chartData.map((_, index) => (
                        <Cell key={`cell-mape-${index}`} fill={MODEL_COLORS[index % MODEL_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="mb-6">
                <h3 className="text-sm font-medium text-dark-300 mb-3">RMSE & MAE 对比 (MW)</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
                    <YAxis stroke="#64748b" fontSize={12} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }} labelStyle={{ color: '#cbd5e1' }} />
                    <Legend wrapperStyle={{ paddingTop: '10px' }} />
                    <Bar dataKey="rmse" name="RMSE (MW)" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="mae" name="MAE (MW)" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="overflow-x-auto rounded-lg">
                <table className="w-full text-sm table-zebra">
                  <thead>
                    <tr className="text-dark-400 border-b border-dark-600">
                      <th scope="col" className="text-left py-2.5 px-3 font-medium">模型名称</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">预测次数</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">MAPE (%)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">RMSE (MW)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">MAE (MW)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">平均推理时间 (ms)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map(([name, item]) => (
                      <tr key={name} className="border-b border-dark-700">
                        <td className="py-2.5 px-3 text-white font-medium">
                          <ModelTag model={name} />
                        </td>
                        <td className="py-2.5 px-3 text-right text-dark-300">{item?.count ?? 0}</td>
                        <td className="py-2.5 px-3 text-right text-warning-400">{formatNumber(item?.mape, 2)}</td>
                        <td className="py-2.5 px-3 text-right text-primary-400">{formatNumber(item?.rmse, 1)}</td>
                        <td className="py-2.5 px-3 text-right text-success-400">{formatNumber(item?.mae, 1)}</td>
                        <td className={`py-2.5 px-3 text-right font-mono ${getInferenceColor(toNum(item?.avg_inference_time_ms))}`}>
                          {formatNumber(item?.avg_inference_time_ms, 1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    )
  }

  // ---- 渲染：趋势分析 Tab ----
  const renderTrends = () => (
    <div className="space-y-4 animate-fade-in">
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <TrendingUp className="w-5 h-5 text-primary-400" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">时间维度趋势分析</h2>
            <p className="card-header-subtitle">预测负荷与实际负荷的时间趋势对比</p>
          </div>
          <div className="flex items-center gap-3 ml-auto">
            <select value={trendWindow} onChange={(e) => setTrendWindow(e.target.value as any)} className="select-dark !py-1.5">
              <option value="hourly">按小时</option>
              <option value="daily">按天</option>
              <option value="weekly">按周</option>
            </select>
            <select value={trendDays} onChange={(e) => setTrendDays(Number(e.target.value))} className="select-dark !py-1.5">
              <option value={1}>最近 1 天</option>
              <option value={7}>最近 7 天</option>
              <option value={14}>最近 14 天</option>
              <option value={30}>最近 30 天</option>
            </select>
            <RefreshButton onClick={loadTrends} isLoading={loading.trends} />
          </div>
        </div>

        {errors.trends ? (
          <ErrorBanner message={errors.trends} onRetry={loadTrends} />
        ) : loading.trends ? (
          <Spinner size="lg" />
        ) : trends.length === 0 ? (
          <EmptyState icon={<TrendingUp className="w-12 h-12" />} title="暂无趋势分析数据" />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={380}>
              <AreaChart data={trends} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="predGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10B981" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="time_label" stroke="#64748b" fontSize={11} angle={-15} textAnchor="end" height={60} />
                <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v) => `${(v / 1000).toFixed(1)}k`} />
                <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }} labelStyle={{ color: '#cbd5e1' }} formatter={(value: any) => [`${Number(value).toFixed(1)} MW`, '']} />
                <Legend wrapperStyle={{ paddingTop: '10px' }} />
                <Area type="monotone" dataKey="predicted_load" name="预测负荷" stroke="#3B82F6" strokeWidth={2} fill="url(#predGrad)" />
                {trends.some(t => t.actual_load !== undefined) && (
                  <Area type="monotone" dataKey="actual_load" name="实际负荷" stroke="#10B981" strokeWidth={2} fill="url(#actualGrad)" />
                )}
              </AreaChart>
            </ResponsiveContainer>

            {trends.some(t => t.mape !== undefined) && (
              <div className="mt-6">
                <h3 className="text-sm font-medium text-dark-300 mb-3">MAPE 趋势变化</h3>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={trends} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="time_label" stroke="#64748b" fontSize={11} angle={-15} textAnchor="end" height={60} />
                    <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }} labelStyle={{ color: '#cbd5e1' }} formatter={(value: any) => [`${Number(value).toFixed(2)}%`, 'MAPE']} />
                    <Line type="monotone" dataKey="mape" name="MAPE" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )

  // ---- 渲染：误差分布 Tab ----
  const renderErrors = () => (
    <div className="space-y-4 animate-fade-in">
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <Target className="w-5 h-5 text-primary-400" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">预测误差分布分析</h2>
            <p className="card-header-subtitle">分析最近 {errorDays} 天的预测误差特征</p>
          </div>
          <div className="flex items-center gap-3 ml-auto">
            <select value={errorDays} onChange={(e) => setErrorDays(Number(e.target.value))} className="select-dark !py-1.5">
              <option value={1}>最近 1 天</option>
              <option value={7}>最近 7 天</option>
              <option value={14}>最近 14 天</option>
              <option value={30}>最近 30 天</option>
            </select>
            <RefreshButton onClick={loadErrorDist} isLoading={loading.errors} />
          </div>
        </div>

        {errors.errors ? (
          <ErrorBanner message={errors.errors} onRetry={loadErrorDist} />
        ) : loading.errors ? (
          <Spinner size="lg" />
        ) : !errorDist ? (
          <EmptyState icon={<Target className="w-12 h-12" />} title="暂无误差分布数据" description="需要包含实际值对比的预测记录" />
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              {[
                { label: '平均误差', value: formatNumber(errorDist.mean_error, 1), unit: 'MW', color: 'text-white' },
                { label: '标准差', value: formatNumber(errorDist.std_error, 1), unit: 'MW', color: 'text-white' },
                { label: '最大误差', value: formatNumber(errorDist.max_error, 1), unit: 'MW', color: 'text-danger-400' },
                { label: '偏差方向', value: errorDist.bias === 'over_predict' ? '高估' : errorDist.bias === 'under_predict' ? '低估' : '均衡', unit: '', color: errorDist.bias === 'over_predict' ? 'text-danger-400' : errorDist.bias === 'under_predict' ? 'text-warning-400' : 'text-success-400' },
              ].map((stat, i) => (
                <div key={i} className="bg-dark-700/50 rounded-lg p-4 hover-lift border border-dark-600">
                  <p className="text-dark-400 text-xs mb-1">{stat.label}</p>
                  <p className={`text-xl font-bold ${stat.color}`}>{stat.value} {stat.unit && <span className="text-sm text-dark-400">{stat.unit}</span>}</p>
                </div>
              ))}
            </div>

            <div className="mb-6">
              <h3 className="text-sm font-medium text-dark-300 mb-3">误差百分位数</h3>
              <div className="grid grid-cols-4 gap-3">
                {[
                  { label: 'P25', value: errorDist.percentiles?.p25, color: 'text-success-400' },
                  { label: 'P50 (中位数)', value: errorDist.percentiles?.p50, color: 'text-primary-400' },
                  { label: 'P75', value: errorDist.percentiles?.p75, color: 'text-warning-400' },
                  { label: 'P95', value: errorDist.percentiles?.p95, color: 'text-danger-400' },
                ].map((p, i) => (
                  <div key={i} className="bg-dark-700/50 rounded-lg p-3 text-center hover-lift border border-dark-600">
                    <p className="text-dark-400 text-xs mb-1">{p.label}</p>
                    <p className={`text-lg font-bold ${p.color}`}>{formatNumber(p.value, 1)}</p>
                    <p className="text-dark-500 text-xs">MW</p>
                  </div>
                ))}
              </div>
            </div>

            {errorDist.histogram && errorDist.histogram.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-dark-300 mb-3">误差分布直方图</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={errorDist.histogram} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="bin" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={12} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }} labelStyle={{ color: '#cbd5e1' }} />
                    <Bar dataKey="count" name="频次" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )

  // ---- 渲染：模型漂移 Tab ----
  const renderDrift = () => (
    <div className="space-y-4 animate-fade-in">
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <Activity className="w-5 h-5 text-primary-400" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">模型漂移检测</h2>
            <p className="card-header-subtitle">检测模型预测准确性是否随时间发生显著变化</p>
          </div>
          <RefreshButton onClick={loadDrift} isLoading={loading.drift} className="ml-auto" />
        </div>

        {errors.drift ? (
          <ErrorBanner message={errors.drift} onRetry={loadDrift} />
        ) : loading.drift ? (
          <Spinner size="lg" />
        ) : !driftResult ? (
          <EmptyState icon={<Activity className="w-12 h-12" />} title="暂无漂移检测数据" />
        ) : (
          <>
            <div className={`rounded-xl p-6 mb-6 border hover-lift ${
              driftResult.drift_detected ? 'bg-danger-500/10 border-danger-500/30' : 'bg-success-500/10 border-success-500/30'
            }`}>
              <div className="flex items-center gap-4">
                {driftResult.drift_detected ? (
                  <AlertTriangle className="w-12 h-12 text-danger-400" />
                ) : (
                  <CheckCircle className="w-12 h-12 text-success-400" />
                )}
                <div>
                  <h3 className={`text-xl font-bold ${driftResult.drift_detected ? 'text-danger-300' : 'text-success-300'}`}>
                    {driftResult.drift_detected ? '检测到模型漂移' : '模型运行稳定'}
                  </h3>
                  <p className="text-dark-300 text-sm mt-1">
                    {driftResult.recommendation || (driftResult.drift_detected ? '建议重新训练模型或检查数据质量' : '模型预测准确性保持在正常范围内')}
                  </p>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {[
                { label: '漂移评分', value: formatNumber(driftResult.drift_score, 3), sub: `阈值: ${formatNumber(driftResult.threshold, 3)}`, color: driftResult.drift_detected ? 'text-danger-400' : 'text-success-400' },
                { label: '最近 MAPE', value: `${formatNumber(driftResult.recent_mape, 2)}%`, sub: '', color: 'text-warning-400' },
                { label: '基准 MAPE', value: `${formatNumber(driftResult.baseline_mape, 2)}%`, sub: '', color: 'text-primary-400' },
              ].map((m, i) => (
                <div key={i} className="bg-dark-700/50 rounded-lg p-4 hover-lift border border-dark-600">
                  <p className="text-dark-400 text-xs mb-1">{m.label}</p>
                  <p className={`text-2xl font-bold ${m.color}`}>{m.value}</p>
                  {m.sub && <p className="text-dark-500 text-xs mt-1">{m.sub}</p>}
                </div>
              ))}
            </div>

            <div className="mt-6">
              <h3 className="text-sm font-medium text-dark-300 mb-3">漂移评分 vs 阈值</h3>
              <div className="relative h-8 bg-dark-700 rounded-full overflow-hidden">
                <div className="absolute inset-y-0 left-0 flex items-center justify-end rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min((toNum(driftResult.drift_score) / (toNum(driftResult.threshold) * 2)) * 100, 100)}%`,
                    background: driftResult.drift_detected ? 'linear-gradient(90deg, #f59e0b, #ef4444)' : 'linear-gradient(90deg, #10B981, #3B82F6)'
                  }}
                />
                <div className="absolute inset-y-0 flex items-center" style={{ left: `${(toNum(driftResult.threshold) / (toNum(driftResult.threshold) * 2)) * 100}%` }}>
                  <div className="w-0.5 h-full bg-white/50" />
                </div>
              </div>
              <div className="flex justify-between mt-2 text-xs text-dark-400">
                <span>0</span>
                <span className="text-white font-medium">阈值: {formatNumber(driftResult.threshold, 3)}</span>
                <span>{formatNumber(toNum(driftResult.threshold) * 2, 3)}</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )

  // ---- 主渲染 ----
  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* 粒子背景 */}
      <ParticleField count={35} opacity={0.3} />

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
        {activeTab === 'overview' && renderOverview()}
        {activeTab === 'history' && renderHistory()}
        {activeTab === 'models' && renderModels()}
        {activeTab === 'trends' && renderTrends()}
        {activeTab === 'errors' && renderErrors()}
        {activeTab === 'drift' && renderDrift()}
      </div>
    </div>
  )
}

export default HistoricalAnalysis
