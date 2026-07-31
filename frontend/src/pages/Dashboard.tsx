import React, { useMemo } from 'react'
import { useApi } from '../contexts/ApiContext'
import MetricCard from '../components/MetricCard'
import LoadForecastChart from '../components/LoadForecastChart'
import WeatherCard from '../components/WeatherCard'
import { MetricCardSkeleton, CardSkeleton, ErrorBanner } from '../components/Skeleton'
import {
  TrendingUp,
  Zap,
  Sun,
  Wind,
  Activity,
  Clock,
  Cpu,
  Cloud,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react'

// ── 刷新指示器组件 ──
const RefreshIndicator: React.FC<{ isRefreshing: boolean; lastUpdated: number | null }> = ({
  isRefreshing,
  lastUpdated,
}) => {
  const timeStr = lastUpdated
    ? new Date(lastUpdated).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg" style={{ background: 'rgba(0, 240, 255, 0.03)', border: '1px solid rgba(0, 240, 255, 0.06)' }}>
      <RefreshCw
        className={`w-3.5 h-3.5 transition-all duration-300 ${
          isRefreshing ? 'animate-spin' : ''
        }`}
        style={{ color: isRefreshing ? '#00F0FF' : 'rgba(0, 240, 255, 0.3)' }}
        aria-hidden="true"
      />
      <span className="text-xs tabular-nums font-mono" style={{ color: 'rgba(0, 240, 255, 0.3)' }}>
        {isRefreshing ? '刷新中...' : timeStr ? `已更新 ${timeStr}` : '等待数据'}
      </span>
    </div>
  )
}

const Dashboard: React.FC = () => {
  const { prediction, weather, systemStatus, isLoading, isInitialLoad, lastUpdated, errors } = useApi()

  // 计算关键指标 — useMemo 避免每次渲染都重新计算
  const metrics = useMemo(() => {
    if (!prediction?.predictions?.length) {
      return {
        currentLoad: 0,
        pvGeneration: 0,
        windGeneration: 0,
        netLoad: 0,
        avgLoad24h: 0,
      }
    }

    const current = prediction.predictions[0]
    const avg24h =
      prediction.predictions.reduce((sum, p) => sum + p.load_forecast_mw, 0) /
      prediction.predictions.length

    return {
      currentLoad: current.load_forecast_mw,
      pvGeneration: current.pv_estimation_mw,
      windGeneration: current.wind_estimation_mw ?? 0,
      netLoad: current.net_load_mw,
      avgLoad24h: avg24h,
    }
  }, [prediction])

  // 是否有任意数据正在刷新 — useMemo 稳定引用
  const isAnyRefreshing = useMemo(
    () => isLoading.prediction || isLoading.weather || isLoading.systemStatus,
    [isLoading.prediction, isLoading.weather, isLoading.systemStatus]
  )

  // 错误状态显示 — useMemo 稳定引用
  const hasErrors = useMemo(
    () => Object.values(errors).some((error) => error !== null),
    [errors]
  )

  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* 页面标题和状态 — 居中 */}
      <div className="page-header-centered relative z-10">
        <h1 data-text="系统总览">系统总览</h1>
        <p>实时监控智能电网负荷预测系统运行状态</p>
        <div className="header-decoration" />
      </div>

      <div className="flex items-center justify-center gap-3 relative z-10 flex-wrap">
          {/* 刷新指示器 */}
          <RefreshIndicator
            isRefreshing={isAnyRefreshing}
            lastUpdated={
              lastUpdated.prediction || lastUpdated.weather || lastUpdated.systemStatus
            }
          />

          {hasErrors && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg animate-slide-up" style={{ background: 'rgba(255, 45, 149, 0.1)', border: '1px solid rgba(255, 45, 149, 0.2)' }}>
              <AlertTriangle className="w-4 h-4" style={{ color: '#FF2D95' }} aria-hidden="true" />
              <span className="text-sm" style={{ color: '#FF2D95' }}>数据加载异常</span>
            </div>
          )}
      </div>

      {/* 核心指标卡片 — 仅首次加载显示骨架屏，刷新时保留旧数据 */}
      <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 transition-opacity duration-300 ${isLoading.prediction && prediction ? 'opacity-80' : 'opacity-100'} relative z-10`}>
        {isInitialLoad.prediction && isLoading.prediction ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            <div className="stagger-item stagger-1">
            <MetricCard
              title="当前负荷预测"
              value={metrics.currentLoad.toFixed(0)}
              unit="MW"
              icon={<Zap className="w-6 h-6" style={{ color: '#00F0FF' }} />}
              trend="up"
              trendValue={`比24h平均${metrics.currentLoad > metrics.avgLoad24h ? '高' : '低'} ${Math.abs(((metrics.currentLoad - metrics.avgLoad24h) / metrics.avgLoad24h) * 100).toFixed(1)}%`}
            />
            </div>

            <div className="stagger-item stagger-2">
            <MetricCard
              title="光伏发电估算"
              value={metrics.pvGeneration.toFixed(1)}
              unit="MW"
              icon={<Sun className="w-6 h-6" style={{ color: '#00FF88' }} />}
              trend="stable"
              trendValue="实时估算"
            />
            </div>

            <div className="stagger-item stagger-3">
            <MetricCard
              title="风电发电估算"
              value={metrics.windGeneration.toFixed(1)}
              unit="MW"
              icon={<Wind className="w-6 h-6" style={{ color: '#00D4FF' }} />}
              trend="stable"
              trendValue="物理模型估算"
            />
            </div>

            <div className="stagger-item stagger-4">
            <MetricCard
              title="净负荷"
              value={metrics.netLoad.toFixed(0)}
              unit="MW"
              icon={<TrendingUp className="w-6 h-6" style={{ color: '#FFE600' }} />}
              trend="down"
              trendValue="含光伏+风电"
            />
            </div>

            <div className="stagger-item stagger-5">
            <MetricCard
              title="系统响应时间"
              value={prediction?.inference_time_ms?.toFixed(0) || '0'}
              unit="ms"
              icon={<Activity className="w-6 h-6" style={{ color: '#B026FF' }} />}
              trend="stable"
              trendValue="实时预测"
            />
            </div>
          </>
        )}
      </div>

      {/* 主要内容区域 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 负荷预测图表 - 主要区域 */}
        <div className="lg:col-span-2">
          <div className="card h-full">
            <div className="card-header">
              <div className="card-header-icon" style={{ background: 'rgba(0, 240, 255, 0.06)' }}>
                <TrendingUp className="w-5 h-5" style={{ color: '#00F0FF' }} aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">24小时负荷预测</h2>
                <p className="card-header-subtitle">总负荷、光伏发电、风电发电和净负荷趋势</p>
              </div>
              <div className="flex items-center gap-2 text-sm ml-auto" style={{ color: 'rgba(0, 240, 255, 0.3)' }}>
                <Clock className="w-4 h-4" aria-hidden="true" />
                <span className="font-mono">实时更新</span>
              </div>
            </div>

            {/* 传递 isInitialLoad 而非 isLoading，避免刷新时图表被骨架屏替换 */}
            <LoadForecastChart
              data={prediction}
              isLoading={isInitialLoad.prediction && isLoading.prediction}
              isRefreshing={isLoading.prediction && !isInitialLoad.prediction}
              height={380}
            />

            {errors.prediction && (
              <div className="mt-4">
                <ErrorBanner message={errors.prediction} />
              </div>
            )}
          </div>
        </div>

        {/* 气象数据面板 */}
        <div className={`space-y-4 transition-opacity duration-300 ${isLoading.weather && weather ? 'opacity-80' : 'opacity-100'}`}>
          <div className="flex items-center gap-3 mb-2">
            <Cloud className="w-6 h-6" style={{ color: '#00F0FF' }} aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold text-white font-cyber">气象监控</h2>
              <p className="text-sm font-mono" style={{ color: 'rgba(0, 240, 255, 0.3)' }}>新英格兰地区实时数据</p>
            </div>
          </div>

          {/* 区域平均 — 仅首次加载显示骨架屏 */}
          {weather?.regional_average ? (
            <WeatherCard
              station={
                {
                  name: '区域平均',
                  latitude: 0,
                  longitude: 0,
                  ...weather.regional_average,
                } as any
              }
              isRegional={true}
            />
          ) : isInitialLoad.weather && isLoading.weather ? (
            <CardSkeleton lines={4} />
          ) : null}

          {/* 各站点数据 — 刷新时保留旧数据 */}
          <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1 -mr-1">
            {weather?.stations?.map((station, index) => (
              <WeatherCard key={index} station={station} />
            ))}
          </div>

          {errors.weather && <ErrorBanner message={errors.weather} />}
        </div>
      </div>

      {/* 底部状态栏 — 刷新时保留旧数据 */}
      <div className={`grid grid-cols-1 md:grid-cols-3 gap-4 transition-opacity duration-300 ${isLoading.systemStatus && systemStatus ? 'opacity-80' : 'opacity-100'}`}>
        {/* 模型状态 */}
        <div className="card stagger-item stagger-1 hud-corners">
          <div className="card-header">
            <div className="card-header-icon" style={{ background: 'rgba(0, 240, 255, 0.06)' }}>
              <Cpu className="w-5 h-5" style={{ color: '#00F0FF' }} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h3 className="card-header-title">模型状态</h3>
              <p className="card-header-subtitle">深度学习模型运行状态</p>
            </div>
          </div>

          {systemStatus ? (
            <div className="space-y-2.5">
              <div className="flex justify-between text-sm">
                <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>已加载模型</span>
                <span className="text-white tabular-nums font-mono">{systemStatus.models_loaded}/4</span>
              </div>
              <div className="flex justify-between text-sm">
                <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>推理设备</span>
                <span className="text-white font-mono">{systemStatus.device}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>平均响应时间</span>
                <span className="text-white tabular-nums font-mono">
                  {systemStatus.average_inference_time_ms?.toFixed(1)}ms
                </span>
              </div>
            </div>
          ) : (
            <div className="space-y-2.5">
              <div className="skeleton h-4 w-full"></div>
              <div className="skeleton h-4 w-3/4"></div>
              <div className="skeleton h-4 w-5/6"></div>
            </div>
          )}
        </div>

        {/* 数据源状态 */}
        <div className="card stagger-item stagger-2 hud-corners">
          <div className="card-header">
            <div className="card-header-icon" style={{ background: 'rgba(0, 255, 136, 0.06)' }}>
              <Activity className="w-5 h-5" style={{ color: '#00FF88' }} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h3 className="card-header-title">数据源状态</h3>
              <p className="card-header-subtitle">API和数据更新状态</p>
            </div>
          </div>

          <div className="space-y-2.5 text-sm">
            <div className="flex justify-between">
              <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>预测数据</span>
              <span
                className={`font-medium flex items-center gap-1.5 ${
                  prediction ? 'text-green-400' : 'text-red-400'
                }`}
              >
                <span
                  className={`status-indicator ${prediction ? 'status-online' : 'status-offline'}`}
                ></span>
                {prediction ? '正常' : '异常'}
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>气象数据</span>
              <span
                className={`font-medium flex items-center gap-1.5 ${
                  weather ? 'text-green-400' : 'text-red-400'
                }`}
              >
                <span
                  className={`status-indicator ${weather ? 'status-online' : 'status-offline'}`}
                ></span>
                {weather ? '正常' : '异常'}
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>最后更新</span>
              <span className="text-white text-xs tabular-nums font-mono">
                {lastUpdated.prediction
                  ? new Date(lastUpdated.prediction).toLocaleTimeString('zh-CN')
                  : '--'}
              </span>
            </div>
          </div>
        </div>

        {/* 系统集成信息 */}
        <div className="card stagger-item stagger-3 hud-corners">
          <div className="card-header">
            <div className="card-header-icon" style={{ background: 'rgba(255, 45, 149, 0.06)' }}>
              <Zap className="w-5 h-5" style={{ color: '#FF2D95' }} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h3 className="card-header-title">系统集成</h3>
              <p className="card-header-subtitle">前后端集成状态</p>
            </div>
          </div>

          <div className="space-y-2.5 text-sm">
            <div className="flex justify-between">
              <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>FastAPI服务</span>
              <span
                className={`font-medium ${
                  systemStatus ? 'text-green-400' : 'text-yellow-400'
                }`}
              >
                {systemStatus ? '运行中' : '连接中'}
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>WebSocket</span>
              <span className="text-yellow-400 font-medium">待实现</span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'rgba(148, 163, 184, 0.6)' }}>Docker部署</span>
              <span style={{ color: 'rgba(148, 163, 184, 0.5)' }} className="font-medium">准备就绪</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
