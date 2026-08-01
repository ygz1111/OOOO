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
import { LoadPredictionResponse } from '../types'
import { ChartSkeleton, EmptyState } from './Skeleton'
import { TrendingUp, RefreshCw, Clock } from 'lucide-react'

interface LoadForecastChartProps {
  data: LoadPredictionResponse | null
  /** 最近已发生的实际负荷（ISO-NE 真实数据），叠加在 hour 轴负区间（过去） */
  actualData?: Array<{ target_timestamp: string; actual_load_mw: number }>
  /** 仅在首次加载（无数据）时为 true，触发骨架屏 */
  isLoading?: boolean
  /** 刷新中（已有旧数据），触发轻量遮罩 */
  isRefreshing?: boolean
  height?: number
}

// ── 提取为独立组件：避免每次父组件渲染都重新创建 Tooltip 组件 ──
const ChartTooltip: React.FC<any> = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null

  const timeStr = payload[0]?.payload?.timestamp
    ? format(payload[0].payload.timestamp, 'HH:mm', { locale: zhCN })
    : `${label}时`

  return (
    <div className="chart-tooltip-glass p-4 shadow-2xl">
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-white/10">
        <Clock className="w-3.5 h-3.5 text-primary-400" aria-hidden="true" />
        <p className="text-white text-sm font-semibold tracking-wide">
          {timeStr}
        </p>
      </div>
      <div className="space-y-2">
        {payload.map((entry: any, index: number) => (
          <div key={index} className="flex items-center gap-3 text-sm">
            <span
              className="w-3 h-3 rounded-md flex-shrink-0 shadow-sm"
              style={{ backgroundColor: entry.color, boxShadow: `0 0 8px ${entry.color}80` }}
              aria-hidden="true"
            ></span>
            <span className="text-dark-300 min-w-[64px]">{entry.name}</span>
            <span className="font-semibold tabular-nums ml-auto" style={{ color: entry.color }}>
              {Number(entry.value).toLocaleString()}
            </span>
            <span className="text-dark-400 text-xs">MW</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// React.memo 包裹 Tooltip：props 稳定时跳过重渲染
const MemoizedTooltip = React.memo(ChartTooltip)

const renderColorfulLegendText = (value: string) => (
  <span className="text-dark-300 text-sm font-medium">{value}</span>
)

const LoadForecastChart: React.FC<LoadForecastChartProps> = ({
  data,
  actualData = [],
  isLoading = false,
  isRefreshing = false,
  height = 400,
}) => {
  // 仅在首次加载（无任何数据）时显示骨架屏
  if (isLoading) {
    return <ChartSkeleton height={height} />
  }

  if (!data || !data.predictions || data.predictions.length === 0) {
    return (
      <div style={{ height }} className="flex items-center justify-center">
        <EmptyState icon={<TrendingUp className="w-12 h-12" />} title="暂无预测数据" />
      </div>
    )
  }

  // 转换数据格式用于图表显示
  const nowMs = Date.now()
  const actualPoints = (actualData ?? []).map((a) => {
    const t = new Date(a.target_timestamp).getTime()
    const hourOffset = Math.round((t - nowMs) / 3600000)
    return {
      hour: hourOffset,
      timestamp: new Date(a.target_timestamp),
      实际负荷: a.actual_load_mw,
      总负荷: null,
      光伏发电: null,
      风电发电: null,
      净负荷: null,
    }
  })
  const forecastPoints = data.predictions.map((pred) => ({
    hour: pred.hour,
    timestamp: new Date(pred.timestamp),
    实际负荷: null,
    总负荷: pred.load_forecast_mw,
    光伏发电: pred.pv_estimation_mw,
    风电发电: pred.wind_estimation_mw ?? 0,
    净负荷: pred.net_load_mw,
  }))
  const chartData = [...actualPoints, ...forecastPoints].sort((a, b) => a.hour - b.hour)

  return (
    <div
      className="relative w-full animate-fade-in"
      style={{ height }}
      role="img"
      aria-label={`负荷预测趋势图：包含总负荷、光伏发电、风电发电和净负荷四条数据线，共 ${chartData.length} 个时间点`}
    >
      {/* 无障碍：实时数据更新通知 */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {isRefreshing ? '图表数据刷新中' : '图表数据已更新'}
      </span>
      {/* 刷新中轻量遮罩：不遮挡旧数据，仅添加视觉提示 */}
      {isRefreshing && (
        <div className="absolute inset-0 z-10 flex items-start justify-end pointer-events-none">
          <div className="flex items-center gap-1.5 mt-1 mr-2 px-2.5 py-1 rounded-lg bg-dark-900/70 border border-dark-600 backdrop-blur-sm">
            <RefreshCw className="w-3 h-3 text-load-400 animate-spin" aria-hidden="true" />
            <span className="text-xs text-dark-300">刷新中</span>
          </div>
        </div>
      )}
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <defs>
            <linearGradient id="loadGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="pvGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#10B981" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="netGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="windGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#06B6D4" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#06B6D4" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" opacity={0.4} />

          <XAxis
            dataKey="hour"
            stroke="#64748b"
            fontSize={12}
            tickFormatter={(value) => value < 0 ? `${-value}h前` : value === 0 ? '现在' : `${value}h`}
            tick={{ fill: '#64748b' }}
            axisLine={{ stroke: '#1F2937' }}
          />

          <YAxis
            stroke="#64748b"
            fontSize={12}
            tickFormatter={(value) => `${(value / 1000).toFixed(1)}k`}
            tick={{ fill: '#64748b' }}
            axisLine={{ stroke: '#1F2937' }}
          />

          <Tooltip content={<MemoizedTooltip />} cursor={{ stroke: '#475569', strokeWidth: 1, strokeDasharray: '4 4' }} />

          <Legend
            wrapperStyle={{ paddingTop: '20px' }}
            iconType="line"
            formatter={renderColorfulLegendText}
          />

          {/* 当前时间参考线 */}
          <ReferenceLine
            x={0}
            stroke="#ef4444"
            strokeDasharray="5 5"
            label={{
              value: '当前',
              position: 'insideBottomRight',
              fill: '#ef4444',
              fontSize: 11,
            }}
          />

          {/* 实际负荷（ISO-NE 真实数据）- 绿色粗实线 */}
          <Line
            type="monotone"
            dataKey="实际负荷"
            stroke="#10B981"
            strokeWidth={3}
            connectNulls={false}
            dot={{ r: 4, fill: '#10B981' }}
            activeDot={{ r: 6, fill: '#10B981', stroke: 'white', strokeWidth: 2 }}
            isAnimationActive={true}
            animationDuration={600}
          />

          {/* 总负荷 - 实线 */}
          <Line
            type="monotone"
            dataKey="总负荷"
            stroke="#3B82F6"
            strokeWidth={3}
            dot={{ r: 4, fill: '#3B82F6' }}
            activeDot={{ r: 6, fill: '#3B82F6', stroke: 'white', strokeWidth: 2 }}
            fill="url(#loadGradient)"
            isAnimationActive={true}
            animationDuration={600}
          />

          {/* 光伏发电 - 虚线（无障碍：通过线型区分） */}
          <Line
            type="monotone"
            dataKey="光伏发电"
            stroke="#10B981"
            strokeWidth={2.5}
            strokeDasharray="8 4"
            dot={{ r: 3, fill: '#10B981' }}
            activeDot={{ r: 5, fill: '#10B981', stroke: 'white', strokeWidth: 2 }}
            isAnimationActive={true}
            animationDuration={600}
          />

          {/* 风电发电 - 长划线（无障碍：通过线型+颜色区分） */}
          <Line
            type="monotone"
            dataKey="风电发电"
            stroke="#06B6D4"
            strokeWidth={2.5}
            strokeDasharray="6 3 2 3"
            dot={{ r: 3, fill: '#06B6D4' }}
            activeDot={{ r: 5, fill: '#06B6D4', stroke: 'white', strokeWidth: 2 }}
            fill="url(#windGradient)"
            isAnimationActive={true}
            animationDuration={600}
          />

          {/* 净负荷 - 点划线（无障碍：通过线型区分） */}
          <Line
            type="monotone"
            dataKey="净负荷"
            stroke="#f59e0b"
            strokeWidth={2.5}
            strokeDasharray="2 4"
            dot={{ r: 3, fill: '#f59e0b' }}
            activeDot={{ r: 5, fill: '#f59e0b', stroke: 'white', strokeWidth: 2 }}
            isAnimationActive={true}
            animationDuration={600}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// React.memo 优化：纯展示组件，props 稳定时避免不必要的重渲染
export default React.memo(LoadForecastChart)
