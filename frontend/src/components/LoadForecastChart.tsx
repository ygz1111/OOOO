import React from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import { LoadOverviewData } from '../types'
import { ChartSkeleton, EmptyState } from './Skeleton'
import { TrendingUp, Clock, Gauge } from 'lucide-react'

interface LoadForecastChartProps {
  /** 24h 负荷预测总览（历史回测验证 + 未来预测 + 当前实际） */
  data: LoadOverviewData | null
  /** 仅在首次加载（无数据）时为 true，触发骨架屏 */
  isLoading?: boolean
  /** 刷新中（已有旧数据），触发轻量遮罩 */
  isRefreshing?: boolean
  height?: number
}

// 时间 → 相对当前的小时偏移（负=过去，0=现在，正=未来）
const hourOffset = (iso: string, nowMs: number): number =>
  Math.round((new Date(iso).getTime() - nowMs) / 3600000)

const ChartTooltip: React.FC<any> = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null

  const p = payload[0]?.payload
  const timeStr = p?.timeLabel ?? `${label}h`

  return (
    <div className="chart-tooltip-glass p-4 shadow-2xl">
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-white/10">
        <Clock className="w-3.5 h-3.5 text-primary-400" aria-hidden="true" />
        <p className="text-white text-sm font-semibold tracking-wide">{timeStr}</p>
      </div>
      <div className="space-y-2">
        {payload.map((entry: any, index: number) => (
          <div key={index} className="flex items-center justify-between gap-6">
            <span className="flex items-center gap-2 text-xs" style={{ color: entry.color }}>
              <span className="w-2 h-2 rounded-full" style={{ background: entry.color }} />
              {entry.name}
            </span>
            <span className="text-sm font-mono text-white">
              {entry.value != null ? `${Number(entry.value).toFixed(1)} MW` : '--'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

const LoadForecastChart: React.FC<LoadForecastChartProps> = ({
  data,
  isLoading = false,
  isRefreshing = false,
  height = 380,
}) => {
  // ── 骨架屏/空态 ──
  if (isLoading && !data) {
    return <ChartSkeleton />
  }
  if (!data) {
    return (
      <div className="flex items-center justify-center py-16">
        <EmptyState icon={<TrendingUp className="w-12 h-12" />} title="暂无预测数据" />
      </div>
    )
  }

  const nowMs = Date.now()
  const hist = data.historical?.pairs ?? []
  const future = data.future?.predictions ?? []
  const metrics = data.historical?.metrics

  // ── 合并数据：过去24h（实际 + 历史回测预测） | 现在 | 未来24h（未来预测）──
  const chartData = [
    ...hist.map((p) => ({
      hour: hourOffset(p.target_time, nowMs),
      timeLabel: format(new Date(p.target_time), 'MM-dd HH:mm', { locale: zhCN }),
      实际负荷: p.historical_actual,
      历史预测: p.historical_forecast,
      未来预测: null,
    })),
    ...future.map((f) => ({
      hour: hourOffset(f.target_time, nowMs),
      timeLabel: format(new Date(f.target_time), 'MM-dd HH:mm', { locale: zhCN }),
      实际负荷: null,
      历史预测: null,
      未来预测: f.future_forecast,
    })),
  ].sort((a, b) => a.hour - b.hour)

  // ── KPI：当前实际、未来峰谷、历史指标 ──
  const currentActual = data.current?.actual_load_mw
  const futureValues = future.map((f) => f.future_forecast)
  const futurePeak = futureValues.length ? Math.max(...futureValues) : null
  const futureTrough = futureValues.length ? Math.min(...futureValues) : null
  const nowLabel = format(new Date(data.generated_at), 'MM-dd HH:mm', { locale: zhCN })

  return (
    <div className="relative w-full animate-fade-in" style={{ height }} role="img"
      aria-label="24小时负荷预测与历史验证：过去24h实际负荷与历史回测预测对比，未来24h预测">
      {isRefreshing && (
        <div className="absolute inset-0 z-10 flex items-start justify-end pointer-events-none">
          <div className="flex items-center gap-1.5 mt-1 mr-2 px-2.5 py-1 rounded-lg bg-dark-900/70 border border-dark-600 backdrop-blur-sm">
            <TrendingUp className="w-3 h-3 text-load-400 animate-spin" aria-hidden="true" />
            <span className="text-xs text-dark-300">刷新中</span>
          </div>
        </div>
      )}

      {/* ── KPI 行 ── */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2 mb-3">
        <div className="bg-dark-700/40 rounded-lg p-2.5 border border-dark-600">
          <p className="text-[10px] text-dark-400 mb-0.5">当前实际负荷</p>
          <p className="text-base font-bold text-emerald-400">
            {currentActual != null ? `${currentActual.toFixed(0)} MW` : '--'}
          </p>
        </div>
        <div className="bg-dark-700/40 rounded-lg p-2.5 border border-dark-600">
          <p className="text-[10px] text-dark-400 mb-0.5">未来峰值</p>
          <p className="text-base font-bold text-warning-400">{futurePeak != null ? `${futurePeak.toFixed(0)} MW` : '--'}</p>
        </div>
        <div className="bg-dark-700/40 rounded-lg p-2.5 border border-dark-600">
          <p className="text-[10px] text-dark-400 mb-0.5">未来最低</p>
          <p className="text-base font-bold text-primary-400">{futureTrough != null ? `${futureTrough.toFixed(0)} MW` : '--'}</p>
        </div>
        <div className="bg-dark-700/40 rounded-lg p-2.5 border border-dark-600">
          <p className="text-[10px] text-dark-400 mb-0.5">历史 24h MAE</p>
          <p className="text-base font-bold text-white">{metrics?.mae_mw != null ? `${metrics.mae_mw.toFixed(0)} MW` : '--'}</p>
        </div>
        <div className="bg-dark-700/40 rounded-lg p-2.5 border border-dark-600">
          <p className="text-[10px] text-dark-400 mb-0.5">历史 24h RMSE</p>
          <p className="text-base font-bold text-white">{metrics?.rmse_mw != null ? `${metrics.rmse_mw.toFixed(0)} MW` : '--'}</p>
        </div>
        <div className="bg-dark-700/40 rounded-lg p-2.5 border border-dark-600">
          <p className="text-[10px] text-dark-400 mb-0.5">历史 24h MAPE</p>
          <p className="text-base font-bold text-danger-400">{metrics?.mape != null ? `${metrics.mape}%` : '--'}</p>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={height - 100}>
        <LineChart data={chartData} margin={{ top: 5, right: 25, left: 15, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" opacity={0.4} />

          <XAxis
            dataKey="hour"
            stroke="#64748b"
            fontSize={11}
            tickFormatter={(value: number) => (value < 0 ? `${-value}h前` : value === 0 ? '现在' : `${value}h`)}
            angle={-30}
            textAnchor="end"
            height={50}
            interval="preserveStartEnd"
          />
          <YAxis
            stroke="#64748b"
            fontSize={11}
            tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<ChartTooltip />} />
          <Legend
            wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }}
            formatter={(value: string) => (
              <span style={{ color: '#cbd5e1' }}>{value}</span>
            )}
          />

          {/* 当前时刻分界线 */}
          <ReferenceLine x={0} stroke="#f43f5e" strokeWidth={2} strokeDasharray="6 3"
            label={{ value: '当前', position: 'top', fill: '#f43f5e', fontSize: 11 }} />

          {/* 实际负荷（ISO-NE 真实，历史部分）- 绿色粗实线 */}
          <Line type="monotone" dataKey="实际负荷" stroke="#10B981" strokeWidth={3}
            connectNulls={false} dot={{ r: 3, fill: '#10B981' }}
            activeDot={{ r: 5, fill: '#10B981', stroke: 'white', strokeWidth: 2 }}
            isAnimationActive={true} animationDuration={600} />

          {/* 历史回测预测 - 橙色虚线（模型用过去气象回测） */}
          <Line type="monotone" dataKey="历史预测" stroke="#f59e0b" strokeWidth={2.5}
            strokeDasharray="8 4" connectNulls={false} dot={{ r: 3, fill: '#f59e0b' }}
            activeDot={{ r: 5, fill: '#f59e0b', stroke: 'white', strokeWidth: 2 }}
            isAnimationActive={true} animationDuration={600} />

          {/* 未来预测 - 蓝色实线 */}
          <Line type="monotone" dataKey="未来预测" stroke="#3B82F6" strokeWidth={3}
            connectNulls={false} dot={{ r: 3, fill: '#3B82F6' }}
            activeDot={{ r: 5, fill: '#3B82F6', stroke: 'white', strokeWidth: 2 }}
            isAnimationActive={true} animationDuration={600} />
        </LineChart>
      </ResponsiveContainer>

      {/* 图例说明 */}
      <div className="mt-2 flex items-center justify-between text-[11px] text-dark-400 px-1">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> 实际负荷（ISO-NE）
          <span className="w-4 h-0.5 bg-amber-500 inline-block mx-1" style={{ borderTop: '2px dashed #f59e0b' }} /> 历史回测预测
          <span className="w-3 h-0.5 bg-blue-500 inline-block ml-1" /> 未来预测
        </span>
        <span className="flex items-center gap-1">
          <Gauge className="w-3 h-3 text-rose-500" /> 生成时间 {nowLabel}
        </span>
      </div>
    </div>
  )
}

export default React.memo(LoadForecastChart)
