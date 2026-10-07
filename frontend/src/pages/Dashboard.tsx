import React, { useMemo } from 'react'
import { useApi } from '../contexts/ApiContext'
import MetricCard from '../components/MetricCard'
import { useForecastClock } from '../hooks/useForecastClock'
import { predictionHealth } from '../utils/predictionHealth'
import LoadForecastChart from '../components/LoadForecastChart'
import { MetricCardSkeleton, ErrorBanner } from '../components/Skeleton'
import { formatEastern, formatEasternISO, parseEasternISO, ET_FULL, ET_TIME, ET_TIME_HM } from '../utils/time'
import {
  TrendingUp,
  Zap,
  Sun,
  Activity,
  Clock,
  Cpu,
  AlertTriangle,
  RefreshCw,
  Layers,
} from 'lucide-react'

// 显示数据获取时间；预测原生成时间另列展示。
const RefreshIndicator: React.FC<{ isRefreshing: boolean; lastUpdated: number | null }> = ({
  isRefreshing,
  lastUpdated,
}) => {
  const timeStr = lastUpdated
    ? formatEastern(new Date(lastUpdated), ET_TIME)
    : null

  return (
    <div className="overview-sync-state" role="status">
      <RefreshCw
        className={`w-3.5 h-3.5 text-primary-600 ${
          isRefreshing ? 'animate-spin' : ''
        }`}
        aria-hidden="true"
      />
      <span className="text-xs tabular-nums text-ink">
        {isRefreshing ? '同步数据中…' : timeStr ? `最近同步 ${timeStr} ET` : '等待数据就绪'}
      </span>
    </div>
  )
}

const Dashboard: React.FC = () => {
  const { prediction, weather, systemStatus, overview, loadOverview, isLoading, isInitialLoad, lastUpdated, errors, isConnecting } = useApi()
  const overviewError = errors.overview
  const overviewLoading = isLoading.overview
  const nowMs = useForecastClock()
  const health = predictionHealth(errors.systemStatus ? null : systemStatus, prediction, errors.prediction, nowMs)

  // 计算关键指标 — useMemo 避免每次渲染都重新计算
  const metrics = useMemo(() => {
    const actualCurrent = overview?.current?.actual_load_mw ?? null
    const forecastRows = prediction?.predictions ?? []
    // 预测数组是完整的日前窗口（通常为 01:00 ET → 次日 00:00 ET），
    // 第 0 项并不代表打开页面时的当前小时。选择离当前真实时刻最近的目标小时。
    const forecastCurrent = forecastRows.find(row => {
      const end = parseEasternISO(row.timestamp).getTime()
      return end > nowMs && end - nowMs <= 3_600_000
    })
    const actualTimeMs = overview?.current?.time
      ? parseEasternISO(overview.current.time).getTime()
      : Number.NaN
    const forecastTimeMs = forecastCurrent?.timestamp
      ? parseEasternISO(forecastCurrent.timestamp).getTime()
      : Number.NaN
    // ISO-NE 实况可能因日前完整窗口的锚点而回退。超过两小时便不能称为“当前实况”。
    const actualIsFresh = actualCurrent != null
      && Number.isFinite(actualTimeMs)
      && Math.abs(actualTimeMs - nowMs) <= 2 * 60 * 60 * 1000
    // 日前窗口不一定覆盖打开页面的当前小时。超过 90 分钟的最近点不可冒充“当前预测”。
    const forecastIsCurrent = Number.isFinite(forecastTimeMs)
      && Math.abs(forecastTimeMs - nowMs) <= 90 * 60 * 1000

    const fallback = {
      currentLoad: null as number | null,
      pvGeneration: null as number | null,
      netLoad: null as number | null,
      avgLoad24h: null as number | null,
      currentIsActual: false,
      currentTime: null as string | null,
      pvTime: null as string | null,
    }
    if (!forecastCurrent && actualCurrent == null) return fallback

    const avg24h = prediction?.predictions?.length
      ? prediction.predictions.reduce((sum, p) => sum + p.load_forecast_mw, 0) /
        prediction.predictions.length
      : null

    const currentLoad = actualIsFresh
      ? actualCurrent
      : forecastIsCurrent ? forecastCurrent?.load_forecast_mw ?? null : null
    const currentTime = actualIsFresh
      ? overview?.current?.time ?? null
      : forecastIsCurrent ? forecastCurrent?.timestamp ?? null : null
    const pvGeneration = forecastIsCurrent ? forecastCurrent?.pv_estimation_mw ?? null : null
    // 净负荷采用同一条预测记录，不能用上一小时实况减去下一小时光伏。
    const netLoad = forecastIsCurrent ? forecastCurrent?.net_load_mw ?? null : null

    return {
      currentLoad,
      pvGeneration,
      netLoad,
      avgLoad24h: avg24h,
      currentIsActual: actualIsFresh,
      currentTime,
      pvTime: forecastIsCurrent ? forecastCurrent?.timestamp ?? null : null,
    }
  }, [prediction, overview, nowMs])

  // 是否有任意数据正在刷新
  const isAnyRefreshing = useMemo(
    () => Object.values(isLoading).some(Boolean),
    [isLoading]
  )

  // 错误状态显示
  const hasErrors = useMemo(
    () => Object.values(errors).some((error) => error !== null),
    [errors]
  )

  return (
    <div className="dashboard-page space-y-4 relative">
      <section className="overview-hero" aria-labelledby="overview-heading">
        <div className="overview-hero-main">
          <div className="min-w-0">
            <p className="overview-eyebrow">ISO-NE · 新英格兰区域</p>
            <h1 id="overview-heading">运行概览</h1>
            <p className="overview-description">负荷、光伏预测及数据服务状态</p>
          </div>
          <div className="overview-data-status">
            <span className="overview-status-label">预测数据状态</span>
            <strong className={health.color}>
              <span className={`status-indicator ${health.indicator}`} aria-hidden="true" />
              {health.text}
            </strong>
          </div>
        </div>
        <div className="overview-runtime-strip">
          <RefreshIndicator
            isRefreshing={isAnyRefreshing}
            lastUpdated={lastUpdated.prediction || lastUpdated.weather || lastUpdated.systemStatus}
          />
          <div className="overview-runtime-item">
            <Cpu className="w-3.5 h-3.5" aria-hidden="true" />
            <span>计算设备</span>
            <strong>{systemStatus?.device ? systemStatus.device.toUpperCase() : '连接中'}</strong>
          </div>
          <div className="overview-runtime-item">
            <Clock className="w-3.5 h-3.5" aria-hidden="true" />
            <span>美国东部时间（ET）</span>
          </div>
          {isConnecting ? (
            <div className="overview-sync-notice text-primary-600" role="status">
              <RefreshCw className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
              <span>正在连接数据服务…</span>
            </div>
          ) : hasErrors && (
            <div className="overview-sync-notice text-rose-700" role="status">
              <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />
              <span>部分数据源正在重试同步</span>
            </div>
          )}
        </div>
      </section>

      {/* 当前小时数据与本次计算耗时 */}
      <div className={`metrics-grid overview-metrics grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 ${isLoading.prediction && prediction ? 'opacity-85' : 'opacity-100'}`}>
        {isInitialLoad.prediction && isLoading.prediction ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            <div>
              <MetricCard
                title={metrics.currentIsActual ? '最近实测负荷 (ISO-NE)' : '当前小时负荷预测'}
                value={metrics.currentLoad == null ? '--' : metrics.currentLoad.toFixed(0)}
                unit={metrics.currentLoad == null ? '' : 'MW'}
                icon={<Zap className="w-5 h-5 text-primary-600" />}
                trend="up"
                trendValue={metrics.currentIsActual
                  ? `ISO-NE · ${metrics.currentTime ? formatEasternISO(metrics.currentTime, ET_TIME_HM) : ''} ET`
                  : metrics.currentLoad != null && metrics.avgLoad24h != null && metrics.avgLoad24h > 0
                    ? `比24h均值${metrics.currentLoad > metrics.avgLoad24h ? '高' : '低'} ${Math.abs(((metrics.currentLoad - metrics.avgLoad24h) / metrics.avgLoad24h) * 100).toFixed(1)}%`
                    : '等待当前小时数据'}
              />
            </div>

            <div>
              <MetricCard
                title="当前小时光伏预测"
                value={metrics.pvGeneration == null ? '--' : metrics.pvGeneration.toFixed(1)}
                unit={metrics.pvGeneration == null ? '' : 'MW'}
                icon={<Sun className="w-5 h-5 text-primary-600" />}
                trend="stable"
                trendValue={metrics.pvTime ? `${formatEasternISO(metrics.pvTime, ET_TIME_HM)} ET` : '等待当前小时数据'}
              />
            </div>

            <div>
              <MetricCard
                title="预测净负荷"
                value={metrics.netLoad == null ? '--' : metrics.netLoad.toFixed(0)}
                unit={metrics.netLoad == null ? '' : 'MW'}
                icon={<TrendingUp className="w-5 h-5 text-primary-600" />}
                trend="down"
                trendValue={metrics.netLoad == null ? '等待同一时点负荷与光伏预测' : `负荷预测 − 光伏预测 · ${metrics.pvTime ? formatEasternISO(metrics.pvTime, ET_TIME_HM) : ''} ET`}
              />
            </div>

            <div>
              <MetricCard
                title="模型计算耗时"
                value={prediction?.inference_time_ms == null ? '--' : prediction.inference_time_ms.toFixed(0)}
                unit={prediction?.inference_time_ms == null ? '' : 'ms'}
                icon={<Activity className="w-5 h-5 text-primary-600" />}
                trend="stable"
                trendValue="本次模型推理耗时"
              />
            </div>
          </>
        )}
      </div>

      {/* 主要内容区域：24小时负荷预测图表 */}
      <div>
        <div className="card forecast-chart-card">
          <div className="card-header flex-wrap">
            <div className="card-header-icon bg-surface-muted border border-edge">
              <TrendingUp className="w-5 h-5 text-primary-600" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="card-header-title text-lg font-bold text-ink">24小时负荷与新能源预测曲线</h2>
              <p className="card-header-subtitle text-xs text-ink-muted">
                历史 24 小时实际值与回测结果，未来 24 小时预测值
              </p>
            </div>
            <div className="flex w-full items-center gap-2 text-xs text-ink-muted sm:ml-auto sm:w-auto tabular-nums">
              <Clock className="w-4 h-4 text-primary-600" aria-hidden="true" />
              <span>美国东部时间（ET）</span>
            </div>
          </div>

          <LoadForecastChart
            data={overview}
            isLoading={overviewLoading && !overview}
            isRefreshing={overviewLoading && !!overview}
            height={460}
          />

          {overviewError && (
            <div className="mt-4">
              <ErrorBanner message={overviewError} onRetry={loadOverview} />
            </div>
          )}

          {errors.prediction && (
            <div className="mt-4">
              <ErrorBanner message={errors.prediction} />
            </div>
          )}
        </div>
      </div>

      {/* 服务信息集中展示，避免重复占用预测曲线区域。 */}
      <section className="overview-service-panel" aria-label="数据与运行信息">
        <div className="overview-service-group">
          <h2><Cpu className="w-4 h-4" aria-hidden="true" />模型计算</h2>
          <dl className="overview-service-list">
            <div>
              <dt>已加载模型</dt>
              <dd className="tabular-nums">{systemStatus ? `${systemStatus.models_loaded} / ${systemStatus.models_total ?? 3}` : '--'}</dd>
            </div>
            <div>
              <dt>平均推理耗时</dt>
              <dd className="tabular-nums">{systemStatus?.average_inference_time_ms == null ? '--' : `${systemStatus.average_inference_time_ms.toFixed(1)} ms`}</dd>
            </div>
          </dl>
        </div>
        <div className="overview-service-group">
          <h2><Activity className="w-4 h-4" aria-hidden="true" />数据获取</h2>
          <dl className="overview-service-list">
            <div>
              <dt>区域气象</dt>
              <dd className={weather ? 'text-emerald-700' : isConnecting ? 'text-primary-600' : 'text-rose-700'}>
                <span className={`status-indicator ${weather ? 'status-online' : isConnecting ? 'status-pending' : 'status-offline'}`} aria-hidden="true" />
                {weather ? '数据可用' : isConnecting ? '建立连接' : '通讯受限'}
              </dd>
            </div>
            <div>
              <dt>预测原生成时间（ET）</dt>
              <dd className="tabular-nums">{prediction?.timestamp ? formatEasternISO(prediction.timestamp, ET_FULL) : '--'}</dd>
            </div>
            <div>
              <dt>最近获取预测（ET）</dt>
              <dd className="tabular-nums">{lastUpdated.prediction ? formatEastern(new Date(lastUpdated.prediction), ET_TIME) : '--'}</dd>
            </div>
          </dl>
        </div>
        <div className="overview-service-group">
          <h2><Layers className="w-4 h-4" aria-hidden="true" />本地服务</h2>
          <dl className="overview-service-list">
            <div>
              <dt>后端连接</dt>
              <dd className={systemStatus ? 'text-emerald-700' : 'text-ink-muted'}>{systemStatus ? '已连接' : '未连接'}</dd>
            </div>
            <div><dt>同步策略</dt><dd>定时更新，异常自动重试</dd></div>
            <div><dt>运行环境</dt><dd>Windows 本地运行</dd></div>
          </dl>
        </div>
      </section>
      {(errors.weather || errors.systemStatus) && <div className="space-y-2">
        {errors.weather && <ErrorBanner message={errors.weather} />}
        {errors.systemStatus && <ErrorBanner message={errors.systemStatus} />}
      </div>}
    </div>
  )
}

export default Dashboard
