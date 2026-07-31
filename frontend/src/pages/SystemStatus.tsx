import React, { useState, useEffect, useRef } from 'react'
import { useApi } from '../contexts/ApiContext'
import { Spinner } from '../components/Skeleton'
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
import ParticleField from '../components/ui/ParticleField'

// ── 迷你 Sparkline 组件 ──
const Sparkline: React.FC<{ data: number[]; color?: string }> = ({ data, color = '#3B82F6' }) => {
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
            background: `linear-gradient(180deg, ${color}, ${color}40)`,
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
  const pct = Math.min(value / max, 1)
  const offset = circumference * (1 - pct)
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(30, 41, 59, 0.8)" strokeWidth="4" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="url(#ringGradient)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 600ms cubic-bezier(0.4,0,0.2,1)' }}
        />
        <defs>
          <linearGradient id="ringGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#3B82F6" />
            <stop offset="100%" stopColor="#60A5FA" />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-sm font-bold text-white">{value}<span className="text-dark-400 text-xs">/{max}</span></span>
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
  const { systemStatus, isLoading, isInitialLoad } = useApi()
  const [latencyTesting, setLatencyTesting] = useState(false)
  const [latencyResult, setLatencyResult] = useState<number | null>(null)
  const [perfHistory, setPerfHistory] = useState<number[]>(Array(12).fill(0))

  const uptimeSeconds = useUptimeTimer(systemStatus?.uptime_seconds || 0)

  const getModelStatuses = () => {
    if (!systemStatus?.ensemble_weights) return []
    return Object.entries(systemStatus.ensemble_weights).map(([name, weight]) => ({
      name,
      weight: (weight * 100).toFixed(0),
      status: 'healthy',
    }))
  }

  const modelStatuses = getModelStatuses()
  const isHealthy = systemStatus?.status === 'healthy'
  const modelsLoaded = systemStatus?.models_loaded || 0

  // 更新性能历史（模拟 sparkline 数据）
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
      const baseUrl = (import.meta as any).env?.VITE_API_BASE_URL || '/api'
      await fetch(`${baseUrl}/health`, { method: 'GET' })
      const elapsed = Date.now() - start
      setLatencyResult(elapsed)
    } catch {
      setLatencyResult(-1)
    } finally {
      setLatencyTesting(false)
    }
  }

  // 内存使用百分比
  const memPct = systemStatus?.memory_usage_mb ? Math.min((systemStatus.memory_usage_mb / 2048) * 100, 100) : 0
  const memColorClass = memPct < 60 ? 'progress-green' : memPct < 80 ? 'progress-yellow' : 'progress-red'

  const formatUptime = (sec: number) => {
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    const s = sec % 60
    return `${h}h ${m}m ${s}s`
  }

  return (
    <div className="space-y-6 animate-fade-in relative">
      {/* 粒子背景 */}
      <ParticleField count={30} opacity={0.25} />

      {/* 页面标题 — 居中 */}
      <div className="page-header-centered relative z-10">
        <h1>系统监控</h1>
        <p>深度学习模型服务运行状态与性能指标监控</p>
        <div className="header-decoration" />
      </div>

      {/* 系统健康指标 */}
      {isInitialLoad.systemStatus && isLoading.systemStatus ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Spinner key={i} size="md" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* 系统状态 - 呼吸光效 */}
          <div
            className={`stagger-item stagger-1 metric-card hover-lift flex flex-col ${isHealthy ? 'border-l-4 border-l-success-500' : 'border-l-4 border-l-danger-500'}`}
            style={isHealthy ? { animation: 'breathing-glow 3s ease-in-out infinite' } : undefined}
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-dark-400 text-xs uppercase tracking-wider mb-1.5 truncate font-medium">系统状态</p>
                <span className="text-2xl font-bold text-white">
                  {isHealthy ? '正常' : systemStatus?.status === 'degraded' ? '降级' : '异常'}
                </span>
              </div>
              <div className="p-2 bg-success-500/15 rounded-lg flex-shrink-0">
                <Activity className={`w-5 h-5 ${isHealthy ? 'text-success-500' : 'text-danger-500'}`} />
              </div>
            </div>
            <div className="flex items-center gap-2 mt-auto pt-3 border-t border-dark-700/60">
              {isHealthy ? (
                <>
                  <span className="pulse-dot" />
                  <span className="text-xs font-medium text-success-400">运行正常</span>
                </>
              ) : (
                <AlertTriangle className="w-4 h-4 text-danger-500" />
              )}
            </div>
          </div>

          {/* 已加载模型 - 进度圆环 */}
          <div className="stagger-item stagger-2 metric-card hover-lift flex flex-col">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-dark-400 text-xs uppercase tracking-wider mb-1.5 truncate font-medium">已加载模型</p>
                <span className="text-2xl font-bold text-white">{modelsLoaded}<span className="text-dark-400 text-sm">/4</span></span>
              </div>
              <div className="flex-shrink-0">
                <ProgressRing value={modelsLoaded} max={4} />
              </div>
            </div>
            <div className="mt-auto pt-3 border-t border-dark-700/60">
              <span className="text-xs font-medium text-primary-400">模型就绪</span>
            </div>
          </div>

          {/* 推理设备 */}
          <div className="stagger-item stagger-3 metric-card hover-lift flex flex-col">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-dark-400 text-xs uppercase tracking-wider mb-1.5 truncate font-medium">推理设备</p>
                <span className="text-2xl font-bold text-white">{systemStatus?.device || '未知'}</span>
              </div>
              <div className="p-2 bg-load-500/15 rounded-lg flex-shrink-0">
                <Server className="w-5 h-5 text-load-500" />
              </div>
            </div>
            <div className="mt-auto pt-3 border-t border-dark-700/60">
              <span className="text-xs font-medium text-dark-400">硬件加速</span>
            </div>
          </div>

          {/* 运行时间 - 实时计时器 */}
          <div className="stagger-item stagger-4 metric-card hover-lift flex flex-col">
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-dark-400 text-xs uppercase tracking-wider mb-1.5 truncate font-medium">运行时间</p>
                <span className="text-xl font-bold text-white tabular-nums">{formatUptime(uptimeSeconds)}</span>
              </div>
              <div className="p-2 bg-load-500/15 rounded-lg flex-shrink-0">
                <Clock className="w-5 h-5 text-load-500" />
              </div>
            </div>
            <div className="mt-auto pt-3 border-t border-dark-700/60">
              <span className="text-xs font-medium text-dark-400">持续运行中</span>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 性能指标 */}
        {isInitialLoad.systemStatus && isLoading.systemStatus ? (
          <Spinner size="lg" />
        ) : (
          <div className="card stagger-item stagger-1 tech-grid-bg">
            <div className="card-header">
              <div className="card-header-icon bg-success-500/15">
                <TrendingUp className="w-5 h-5 text-success-400 icon-zoom" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">性能指标</h2>
                <p className="card-header-subtitle">系统响应时间与吞吐量</p>
              </div>
            </div>

            <div className="space-y-4">
              {/* 平均响应时间 + Sparkline */}
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-dark-300 text-sm">平均响应时间</span>
                  <span className="text-xl font-bold text-white tabular-nums">
                    {systemStatus?.average_inference_time_ms?.toFixed(1) || '0'}
                    <span className="text-sm text-dark-400 ml-1">ms</span>
                  </span>
                </div>
                <div className="progress-bar-enhanced mb-3">
                  <div
                    className="progress-bar-fill progress-blue"
                    style={{ width: `${Math.min((systemStatus?.average_inference_time_ms || 0) / 2, 100)}%` }}
                  />
                </div>
                <Sparkline data={perfHistory} color="#3B82F6" />
              </div>

              {/* 总推理次数 */}
              <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-dark-300 text-sm">总推理次数</span>
                  <span className="text-xl font-bold text-white tabular-nums">
                    {systemStatus?.total_inferences?.toLocaleString() || '0'}
                  </span>
                </div>
                <div className="progress-bar-enhanced">
                  <div className="progress-bar-fill progress-green" style={{ width: '60%' }} />
                </div>
              </div>

              {/* 内存使用 - 颜色阈值 */}
              {systemStatus?.memory_usage_mb && (
                <div className="bg-dark-700/50 rounded-lg p-4 border border-dark-600">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-dark-300 text-sm">内存使用</span>
                    <span className="text-xl font-bold text-white tabular-nums">
                      {systemStatus.memory_usage_mb.toFixed(1)}
                      <span className="text-sm text-dark-400 ml-1">MB</span>
                      <span className={`ml-2 text-xs ${memPct < 60 ? 'text-success-400' : memPct < 80 ? 'text-warning-400' : 'text-danger-400'}`}>
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
        <div className="card stagger-item stagger-2 tech-grid-bg">
          <div className="card-header">
            <div className="card-header-icon bg-primary-500/15">
              <Cpu className="w-5 h-5 text-primary-400 icon-zoom" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">模型状态</h2>
              <p className="card-header-subtitle">深度学习模型加载与运行</p>
            </div>
          </div>

          <div className="space-y-3">
            {modelStatuses.map((model, index) => (
              <div key={index} className="model-status-card">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <div className="relative">
                      <CheckCircle className="w-5 h-5 text-success-500" aria-hidden="true" />
                      <span className="pulse-dot absolute -top-0.5 -right-0.5 w-1.5 h-1.5" />
                    </div>
                    <div>
                      <div className="text-white font-medium text-sm">{model.name}</div>
                      <div className="text-dark-400 text-xs tabular-nums">权重: {model.weight}%</div>
                    </div>
                  </div>
                  <span className="badge badge-success">
                    <Check className="w-3 h-3" />
                    健康
                  </span>
                </div>
                {/* 权重进度条 */}
                <div className="progress-bar-enhanced mt-2" style={{ height: '4px' }}>
                  <div className="progress-bar-fill progress-blue" style={{ width: `${model.weight}%` }} />
                </div>
                <div className="flex items-center justify-between mt-2 text-xs text-dark-500">
                  <span>最后推理: {new Date().toLocaleTimeString('zh-CN')}</span>
                  <span className="text-success-500">就绪</span>
                </div>
              </div>
            ))}

            {modelStatuses.length === 0 && (
              <div className="text-center py-8">
                <AlertTriangle className="w-12 h-12 text-dark-400 mx-auto mb-4 opacity-50" aria-hidden="true" />
                <p className="text-dark-400">暂无模型状态信息</p>
              </div>
            )}
          </div>
        </div>

        {/* 系统信息 - 两列布局 + 脉冲点 + API延迟测试 */}
        <div className="card stagger-item stagger-3 tech-grid-bg">
          <div className="card-header">
            <div className="card-header-icon bg-load-500/15">
              <HardDrive className="w-5 h-5 text-load-400 icon-zoom" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">系统信息</h2>
              <p className="card-header-subtitle">运行环境与集成状态</p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex justify-between items-center py-2.5 px-3 bg-dark-700/30 rounded-lg border border-dark-700">
              <span className="text-dark-300 text-sm">前端版本</span>
              <span className="text-white font-mono text-sm">v1.0.0</span>
            </div>

            <div className="flex justify-between items-center py-2.5 px-3 bg-dark-700/30 rounded-lg border border-dark-700">
              <span className="text-dark-300 text-sm">后端服务</span>
              <span className="text-white font-mono text-sm">FastAPI</span>
            </div>

            <div className="flex justify-between items-center py-2.5 px-3 bg-dark-700/30 rounded-lg border border-dark-700">
              <span className="text-dark-300 text-sm">API状态</span>
              <div className="flex items-center gap-2">
                <span className="pulse-dot" />
                <span className="text-success-400 text-sm">在线</span>
              </div>
            </div>

            <div className="flex justify-between items-center py-2.5 px-3 bg-dark-700/30 rounded-lg border border-dark-700">
              <span className="text-dark-300 text-sm">更新频率</span>
              <span className="text-white font-mono text-sm tabular-nums">300s</span>
            </div>

            <div className="flex justify-between items-center py-2.5 px-3 bg-dark-700/30 rounded-lg border border-dark-700">
              <span className="text-dark-300 text-sm">最后更新</span>
              <span className="text-white font-mono text-xs tabular-nums">
                {new Date().toLocaleTimeString('zh-CN')}
              </span>
            </div>

            {/* API 延迟测试 */}
            <div className="pt-2">
              <button
                onClick={testLatency}
                disabled={latencyTesting}
                className="btn btn-ghost w-full !py-2 !text-sm hover-lift"
              >
                <Zap className={`w-4 h-4 text-warning-500 ${latencyTesting ? 'animate-spin' : ''}`} />
                {latencyTesting ? '测试中...' : '测试 API 延迟'}
              </button>
              {latencyResult !== null && (
                <div className="mt-2 text-center">
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
