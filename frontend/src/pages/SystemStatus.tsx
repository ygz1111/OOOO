import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useApi } from '../contexts/ApiContext'
import apiService from '../services/api'
import { CardSkeleton, ErrorBanner, MetricCardSkeleton } from '../components/Skeleton'
import { RefreshButton } from '../components/ui/MicroInteractions'
import { formatEasternISO, ET_TIME } from '../utils/time'
import {
  Activity,
  Cpu,
  Clock,
  HardDrive,
  TrendingUp,
  Server,
  CheckCircle,
  AlertTriangle,
  Zap,
  Check,
} from 'lucide-react'

// ── 迷你 Sparkline 组件 ──
const Sparkline: React.FC<{ data: number[]; color?: string }> = ({ data, color = 'var(--chart-forecast)' }) => {
  if (data.length === 0) return null
  const max = Math.max(...data, 1)
  const min = Math.min(...data, 0)
  const range = max - min || 1
  return (
    <div className="sparkline-container">
      {data.map((v, i) => (
        <div
          key={i}
          className="sparkline-bar"
          style={{
            height: `${Math.max(((v - min) / range) * 100, 10)}%`,
            background: color,
          }}
        />
      ))}
    </div>
  )
}

// ── 进度圆环组件 ──
const ProgressRing: React.FC<{ value: number; max: number; size?: number }> = ({ value, max, size = 56 }) => {
  const radius = (size - 8) / 2
  const circumference = 2 * Math.PI * radius
  const hasScale = Number.isFinite(max) && max > 0
  const safeValue = Number.isFinite(value) ? Math.max(value, 0) : 0
  const pct = hasScale ? Math.min(safeValue / max, 1) : 0
  const offset = circumference * (1 - pct)
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--border)" strokeWidth="4" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--chart-forecast)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 600ms cubic-bezier(0.4,0,0.2,1)' }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-sm font-bold text-ink">
          {hasScale ? <>{safeValue}<span className="text-ink-muted text-xs">/{max}</span></> : '--'}
        </span>
      </div>
    </div>
  )
}

// ── 实时计时器 Hook ──
const useUptimeTimer = (startSeconds: number) => {
  const [elapsed, setElapsed] = useState(startSeconds)
  const startTimeRef = useRef(Date.now())
  const baseRef = useRef(startSeconds)

  useEffect(() => {
    baseRef.current = startSeconds
    startTimeRef.current = Date.now()
  }, [startSeconds])

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed(baseRef.current + Math.floor((Date.now() - startTimeRef.current) / 1000))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  return elapsed
}

const SystemStatus: React.FC = () => {
  const { systemStatus, isLoading, isInitialLoad, errors, loadSystemStatus } = useApi()
  const [latencyTesting, setLatencyTesting] = useState(false)
  const [latencyResult, setLatencyResult] = useState<number | null>(null)
  const [perfHistory, setPerfHistory] = useState<number[]>(Array(12).fill(0))

  const uptimeSeconds = useUptimeTimer(systemStatus?.uptime_seconds || 0)

  const getTensorFlowModelStatuses = () => {
    if (systemStatus?.model_details?.length) {
      return systemStatus.model_details.map((model) => ({
        ...model,
        enabledPercent: model.loaded ? '100' : '0',
        status: model.loaded ? 'healthy' : 'error',
      }))
    }
    if (!systemStatus?.ensemble_weights) return []
    return Object.entries(systemStatus.ensemble_weights).map(([id, weight]) => ({
      id,
      name: id,
      task: '预测',
      architecture: '',
      framework: 'TensorFlow',
      loaded: true,
      enabledPercent: (weight * 100).toFixed(0),
      status: 'healthy',
    }))
  }

  const modelStatuses = getTensorFlowModelStatuses()
  const hasSystemStatus = systemStatus !== null
  const isHealthy = systemStatus?.status === 'healthy'
  const modelsLoaded = systemStatus?.models_loaded ?? 0
  const modelsTotal = systemStatus?.models_total ?? modelStatuses.length

  // 更新性能历史（sparkline 数据：真实 average_inference_time_ms 滑动窗口）
  useEffect(() => {
    if (systemStatus?.average_inference_time_ms != null) {
      setPerfHistory(prev => [...prev.slice(1), systemStatus.average_inference_time_ms])
    }
  }, [systemStatus?.average_inference_time_ms])

  // API 延迟测试
  const testLatency = async () => {
    setLatencyTesting(true)
    setLatencyResult(null)
    try {
      const start = Date.now()
      // 延迟按钮测量轻量状态接口；综合 /health 还会主动探测 Redis、GPU，
      // 在未启动可选缓存时会等待超时，不代表前后端 API 本身延迟高。
      await apiService.getSystemStatus()
      const elapsed = Date.now() - start
      setLatencyResult(elapsed)
    } catch {
      setLatencyResult(-1)
    } finally {
      setLatencyTesting(false)
    }
  }

  // 内存使用百分比（2026-08 优化：以 2048MB 为估算基线，标注来源）
  // 后端未返回内存总量，2048MB 与 docker-compose 中 API 容器 memory limit 对齐
  const MEM_BASE_MB = 2048
  const memPct = systemStatus?.memory_usage_mb ? Math.min((systemStatus.memory_usage_mb / MEM_BASE_MB) * 100, 100) : 0
  const memColorClass = memPct < 60 ? 'progress-green' : memPct < 80 ? 'progress-yellow' : 'progress-red'

  // 推理速率（次/分钟）——用总推理次数 / 运行时长计算，替代原装饰性 60% 假进度
  const inferenceRate = useMemo(() => {
    const n = systemStatus?.total_inferences || 0
    const mins = Math.max(uptimeSeconds, 1) / 60
    return n / mins
  }, [systemStatus?.total_inferences, uptimeSeconds])
  // 速率条宽度：2 次/分钟对应满条（经验刻度），上限 100%
  const inferenceRatePct = Math.min((inferenceRate / 2) * 100, 100)

  const formatUptime = (sec: number) => {
    const wholeSeconds = Math.max(0, Math.floor(sec))
    const h = Math.floor(wholeSeconds / 3600)
    const m = Math.floor((wholeSeconds % 3600) / 60)
    const s = wholeSeconds % 60
    return `${h}h ${m}m ${s}s`
  }

  return (
    <div className="space-y-6 animate-fade-in relative">
      <div className="page-header flex flex-wrap items-start justify-between gap-4 relative z-10">
        <div className="min-w-0">
          <h1>系统监控</h1>
          <p>后端连接、模型加载、推理性能及运行环境信息。</p>
        </div>
        <div className="page-actions">
          <RefreshButton onClick={() => loadSystemStatus()} isLoading={isLoading.systemStatus} className="btn-primary" />
        </div>
      </div>

      {errors.systemStatus && (
        <ErrorBanner message={errors.systemStatus} onRetry={() => loadSystemStatus()} />
      )}

      {/* 系统健康指标 */}
      {isInitialLoad.systemStatus && isLoading.systemStatus ? (
        <div className="metrics-grid grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <MetricCardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <div className="metrics-grid grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {/* 模型服务状态 */}
          <div
            className={`stagger-item stagger-1 metric-card  flex flex-col ${isHealthy ? 'border-l-4 border-l-success-500' : hasSystemStatus ? 'border-l-4 border-l-danger-500' : 'border-l-4 border-l-warning-500'}`}
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-ink-muted text-xs uppercase tracking-wider mb-1.5 truncate font-medium">模型服务状态</p>
                <span className="text-2xl font-bold text-ink">
                  {!hasSystemStatus ? '等待数据' : isHealthy ? '正常' : systemStatus?.status === 'degraded' ? '降级' : '异常'}
                </span>
              </div>
              <div className="p-2 bg-surface-muted rounded flex-shrink-0">
                <Activity className={`w-5 h-5 ${isHealthy ? 'text-success-500' : hasSystemStatus ? 'text-danger-500' : 'text-warning-500'}`} />
              </div>
            </div>
            <div className="flex items-center gap-2 mt-auto pt-3 border-t border-edge">
              {isHealthy ? (
                <>
                  <span className="status-indicator status-online" aria-hidden="true" />
                  <span className="text-xs font-medium text-success-700">模型已加载；预测数据状态见顶部</span>
                </>
              ) : hasSystemStatus ? (
                <AlertTriangle className="w-4 h-4 text-danger-500" />
              ) : (
                <span className="text-xs font-medium text-warning-700">正在连接后端服务</span>
              )}
            </div>
          </div>

          {/* 已加载模型 - 进度圆环 */}
          <div className="stagger-item stagger-2 metric-card  flex flex-col">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-ink-muted text-xs uppercase tracking-wider mb-1.5 truncate font-medium">已加载模型</p>
                <span className="text-2xl font-bold text-ink">{hasSystemStatus ? <>{modelsLoaded}<span className="text-ink-muted text-sm">/{modelsTotal}</span></> : '--'}</span>
              </div>
              <div className="flex-shrink-0">
                <ProgressRing value={modelsLoaded} max={modelsTotal} />
              </div>
            </div>
            <div className="mt-auto pt-3 border-t border-edge">
              <span className="text-xs font-medium text-ink-muted">{hasSystemStatus ? '模型状态已同步' : '等待模型状态'}</span>
            </div>
          </div>

          {/* 推理设备 */}
          <div className="stagger-item stagger-3 metric-card  flex flex-col">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-ink-muted text-xs uppercase tracking-wider mb-1.5 truncate font-medium">推理设备</p>
                <span className="break-words text-xl font-bold text-ink">{systemStatus?.device || '--'}</span>
              </div>
              <div className="p-2 bg-surface-muted rounded flex-shrink-0">
                <Server className="w-5 h-5 text-primary-600" />
              </div>
            </div>
            <div className="mt-auto pt-3 border-t border-edge">
              <span className="text-xs font-medium text-ink-muted">当前模型计算设备</span>
            </div>
          </div>

          {/* 运行时间 - 实时计时器 */}
          <div className="stagger-item stagger-4 metric-card  flex flex-col">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-ink-muted text-xs uppercase tracking-wider mb-1.5 truncate font-medium">运行时间</p>
                <span className="break-words text-lg font-bold text-ink tabular-nums">{hasSystemStatus ? formatUptime(uptimeSeconds) : '--'}</span>
              </div>
              <div className="p-2 bg-surface-muted rounded flex-shrink-0">
                <Clock className="w-5 h-5 text-primary-600" />
              </div>
            </div>
            <div className="mt-auto pt-3 border-t border-edge">
              <span className="text-xs font-medium text-ink-muted">持续运行中</span>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 2xl:grid-cols-3 items-start">
        {/* 性能指标 */}
        {isInitialLoad.systemStatus && isLoading.systemStatus ? (
          <CardSkeleton lines={8} />
        ) : (
          <div className="card min-w-0 stagger-item stagger-1">
            <div className="card-header">
              <div className="card-header-icon bg-surface-muted border border-edge">
                <TrendingUp className="w-5 h-5 text-primary-600 " aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">性能指标</h2>
                <p className="card-header-subtitle">模型推理耗时与累计推理次数</p>
              </div>
            </div>

            <div className="space-y-4">
              {/* 平均响应时间 + Sparkline */}
              <div className="bg-surface-muted rounded p-4 border border-edge">
                <div className="flex flex-wrap justify-between items-baseline gap-2 mb-2">
                  <span className="text-ink text-sm">平均模型推理耗时</span>
                  <span className="text-xl font-bold text-ink tabular-nums">
                    {systemStatus?.average_inference_time_ms == null ? '--' : systemStatus.average_inference_time_ms.toFixed(1)}
                    {systemStatus?.average_inference_time_ms != null && <span className="text-sm text-ink-muted ml-1">ms</span>}
                  </span>
                </div>
                <div className="progress-bar-enhanced mb-3">
                  <div
                    className="progress-bar-fill progress-blue"
                    style={{ width: `${Math.min((systemStatus?.average_inference_time_ms || 0) / 2, 100)}%` }}
                  />
                </div>
                <Sparkline data={perfHistory} color="var(--chart-forecast)" />
              </div>

              {/* 总推理次数 */}
              <div className="bg-surface-muted rounded p-4 border border-edge">
                <div className="flex flex-wrap justify-between items-baseline gap-2 mb-2">
                  <span className="text-ink text-sm">总推理次数</span>
                  <span className="text-xl font-bold text-ink tabular-nums">
                    {systemStatus?.total_inferences == null ? '--' : systemStatus.total_inferences.toLocaleString()}
                  </span>
                </div>
                {/* 推理速率条：次数 / 运行时长（每分钟推理数），真实数据非装饰 */}
                <div className="progress-bar-enhanced">
                  <div className="progress-bar-fill progress-blue" style={{ width: `${inferenceRatePct}%` }} />
                </div>
                <div className="text-[11px] text-ink-muted mt-1.5">
                  {!hasSystemStatus ? '等待推理统计' : inferenceRate >= 1 ? `${inferenceRate.toFixed(1)} 次/分钟` : '启动时间较短，速率累计中'}
                </div>
              </div>

              {/* 内存使用 - 颜色阈值 */}
              {systemStatus?.memory_usage_mb && (
                <div className="bg-surface-muted rounded p-4 border border-edge">
                  <div className="flex flex-wrap justify-between items-baseline gap-2 mb-2">
                    <span className="text-ink text-sm">内存使用</span>
                    <span className="text-xl font-bold text-ink tabular-nums">
                      {systemStatus.memory_usage_mb.toFixed(1)}
                      <span className="text-sm text-ink-muted ml-1">MB</span>
                      <span className={`ml-2 text-xs ${memPct < 60 ? 'text-success-700' : memPct < 80 ? 'text-warning-700' : 'text-danger-700'}`}>
                        ({memPct.toFixed(0)}%)
                      </span>
                    </span>
                  </div>
                  <div className="progress-bar-enhanced">
                    <div className={`progress-bar-fill ${memColorClass}`} style={{ width: `${memPct}%` }} />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 模型详细状态 - 卡片式 */}
        <div className="card min-w-0 stagger-item stagger-2">
          <div className="card-header">
            <div className="card-header-icon bg-surface-muted border border-edge">
              <Cpu className="w-5 h-5 text-primary-600 " aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">模型状态</h2>
              <p className="card-header-subtitle">各预测模型的加载与运行状态</p>
            </div>
          </div>

          <div className="space-y-3">
            {modelStatuses.map((model) => (
              <div key={model.id} className="model-status-card">
                <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <div className="relative shrink-0 mt-0.5">
                      {model.loaded
                        ? <CheckCircle className="w-5 h-5 text-success-500" aria-hidden="true" />
                        : <AlertTriangle className="w-5 h-5 text-danger-500" aria-hidden="true" />}
                    </div>
                    <div className="min-w-0 break-words">
                      <div className="text-ink font-semibold text-sm">{model.name}</div>
                      <div className="text-ink text-xs mt-0.5">{model.task}</div>
                      <div className="text-ink-muted text-xs tabular-nums mt-0.5">{model.framework} · {model.architecture || '模型服务'}</div>
                    </div>
                  </div>
                  <span className={`badge shrink-0 ${model.loaded ? 'badge-success' : 'badge-danger'}`}>
                    {model.loaded ? <Check className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                    {model.loaded ? '已加载' : '未加载'}
                  </span>
                </div>
                {/* 模块启用状态 */}
                <div className="progress-bar-enhanced mt-2" style={{ height: '4px' }}>
                  <div className="progress-bar-fill progress-blue" style={{ width: `${model.enabledPercent}%` }} />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 mt-2 text-xs text-ink-muted">
                  <span>服务累计推理：{systemStatus?.total_inferences ? `${systemStatus.total_inferences} 次` : '--'}</span>
                  <span className={model.loaded ? 'text-success-700' : 'text-danger-700'}>{model.loaded ? '就绪' : '异常'}</span>
                </div>
              </div>
            ))}

            {modelStatuses.length === 0 && (
              <div className="text-center py-8" role="status">
                {isInitialLoad.systemStatus && isLoading.systemStatus ? (
                  <p className="text-ink-muted">正在获取模型状态</p>
                ) : (
                  <>
                    <AlertTriangle className="w-12 h-12 text-ink-muted mx-auto mb-4 opacity-50" aria-hidden="true" />
                    <p className="text-ink-muted">暂无模型状态信息</p>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {/* 系统信息 - 两列布局 + 脉冲点 + API延迟测试 */}
        <div className="card min-w-0 md:col-span-2 2xl:col-span-1 stagger-item stagger-3">
          <div className="card-header">
            <div className="card-header-icon bg-surface-muted border border-edge">
              <HardDrive className="w-5 h-5 text-primary-600 " aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">系统信息</h2>
              <p className="card-header-subtitle">TensorFlow / Keras 推理环境与服务状态</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-1">
            <div className="flex flex-wrap justify-between items-center gap-2 py-2.5 px-3 bg-surface-muted rounded border border-edge">
              <span className="text-ink text-sm">前端版本</span>
              <span className="text-ink tabular-nums text-sm">v1.0.0</span>
            </div>

            <div className="flex flex-wrap justify-between items-center gap-2 py-2.5 px-3 bg-surface-muted rounded border border-edge">
              <span className="text-ink text-sm">后端服务</span>
              <span className="text-ink tabular-nums text-sm">FastAPI</span>
            </div>

            <div className="flex flex-wrap justify-between items-center gap-2 py-2.5 px-3 bg-surface-muted rounded border border-edge">
              <span className="text-ink text-sm">API状态</span>
              <div className="flex items-center gap-2">
                <span className={hasSystemStatus ? 'status-indicator status-online' : 'h-2 w-2 rounded-full bg-slate-500'} aria-hidden="true" />
                <span className={hasSystemStatus ? 'text-success-700 text-sm' : 'text-ink-muted text-sm'}>{hasSystemStatus ? '在线' : '未连接'}</span>
              </div>
            </div>

            <div className="flex flex-wrap justify-between items-center gap-2 py-2.5 px-3 bg-surface-muted rounded border border-edge">
              <span className="text-ink text-sm">更新频率</span>
              <span className="text-ink tabular-nums text-sm tabular-nums">5 分钟</span>
            </div>

            <div className="flex flex-wrap justify-between items-center gap-2 py-2.5 px-3 bg-surface-muted rounded border border-edge">
              <span className="text-ink text-sm">最后更新</span>
              <span className="text-ink tabular-nums text-xs tabular-nums">
                {systemStatus?.timestamp
                  ? formatEasternISO(systemStatus.timestamp, ET_TIME)
                  : '--'}
              </span>
            </div>

            {/* API 延迟测试 */}
            <div className="data-toolbar pt-2 sm:col-span-2 2xl:col-span-1">
              <button
                onClick={testLatency}
                disabled={latencyTesting}
                className="btn btn-ghost !py-2 !text-sm"
              >
                <Zap className={`w-4 h-4 text-primary-600 ${latencyTesting ? 'animate-spin' : ''}`} />
                {latencyTesting ? '测试中...' : '测试 API 延迟'}
              </button>
              {latencyResult !== null && (
                <div className="min-w-0" role="status">
                  {latencyResult >= 0 ? (
                    <span className={`badge ${latencyResult < 100 ? 'badge-success' : latencyResult < 300 ? 'badge-warning' : 'badge-danger'}`}>
                      延迟: {latencyResult}ms
                    </span>
                  ) : (
                    <span className="badge badge-danger">连接失败</span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SystemStatus
