import ChartLegend from '../../components/ChartLegend'
import { CHART_COLORS, CHART_GRID, CHART_LEGEND, CHART_AXIS } from '../../utils/chartTheme'
import React, { useMemo } from 'react'
import {
  CalendarDays, Clock, Target, Activity, TrendingDown, Zap,
  Thermometer, Wind, Cloud, Sun,
} from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import MetricCard from '../../components/MetricCard'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { formatEasternISO, ET_TIME_HM, ET_FULL } from '../../utils/time'
import { formatNumber } from './shared'
import type { DayBacktestData } from '../../types'

interface Props {
  date: string | null
  range: { earliest: string | null; latest: string | null } | null
  data: DayBacktestData | null
  loading: boolean
  error: string | null
  onDateChange: (date: string) => void
  onRefresh: () => void
}

// 逐小时数据提示
interface ChartTooltipEntry {
  dataKey: string
  name?: string
  value?: number | null
  stroke?: string
  unit?: string
  payload: { timeLabel: string }
}

interface ChartTooltipProps {
  active?: boolean
  payload?: ChartTooltipEntry[]
}

const ChartTooltip = ({ active, payload }: ChartTooltipProps) => {
  if (!active || !payload || payload.length === 0) return null
  const point = payload[0].payload
  return (
    <div className="chart-tooltip p-4">
      <div className="flex items-center gap-2 mb-2 text-sm text-ink">
        <Clock className="w-4 h-4" aria-hidden="true" />
        {point.timeLabel}（ET）
      </div>
      {payload.map((entry) => (
        <div key={entry.dataKey} className="flex items-center justify-between gap-4 text-sm">
          <span className="flex items-center gap-2 text-ink">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: entry.stroke }} />
            {entry.name}
          </span>
          <span className="font-medium text-ink">
            {entry.value != null ? `${Number(entry.value).toFixed(1)} ${entry.unit}` : '--'}
          </span>
        </div>
      ))}
    </div>
  )
}

const getErrorColor = (absError: number | null): string => {
  if (absError == null) return 'text-ink-muted'
  if (absError < 300) return 'text-success-700'
  if (absError < 800) return 'text-warning-700'
  return 'text-danger-700'
}

const _avg = (vals: Array<number | null>): number | null => {
  const valid = vals.filter((v): v is number => v != null)
  return valid.length > 0 ? valid.reduce((a, b) => a + b, 0) / valid.length : null
}

export const BacktestTab: React.FC<Props> = ({
  date, range, data, loading, error, onDateChange, onRefresh,
}) => {
  // 图表数据：实际 / 回测预测 / 温度（按 target_time 对齐，与后端 weather 一一对应）
  const chartData = useMemo(() => {
    if (!data) return []
    const tempByTime = new Map(data.weather.map((w) => [w.target_time, w.temperature_2m]))
    return data.pairs.map((p) => ({
      timeLabel: formatEasternISO(p.target_time, ET_TIME_HM),
      actual: p.historical_actual,
      forecast: p.historical_forecast,
      temp: tempByTime.get(p.target_time) ?? null,
    }))
  }, [data])

  const weatherByTime = useMemo(
    () => new Map((data?.weather ?? []).map((point) => [point.target_time, point])),
    [data],
  )

  // 汇总统计（峰值 / 最大误差 / 气象均值）
  const stats = useMemo(() => {
    if (!data) return null
    const actuals = data.pairs.filter((p) => p.historical_actual != null)
    const actualPeak = actuals.length > 0
      ? Math.max(...actuals.map((p) => p.historical_actual as number))
      : null
    const maxAbs = data.pairs.reduce(
      (m, p) => (p.absolute_error_mw != null ? Math.max(m, p.absolute_error_mw) : m), 0
    )
    const peakRadiation = data.weather.reduce(
      (m, w) => (w.shortwave_radiation != null ? Math.max(m, w.shortwave_radiation) : m), 0
    )
    return {
      actualPeak,
      maxAbs,
      validCount: actuals.length,
      avgTemp: _avg(data.weather.map((w) => w.temperature_2m)),
      avgWind: _avg(data.weather.map((w) => w.wind_speed_10m)),
      avgCloud: _avg(data.weather.map((w) => w.cloud_cover)),
      peakRadiation,
    }
  }, [data])

  const m = data?.metrics ?? null

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 日期控制 */}
      <div className="card">
        <div className="card-header flex-wrap">
          <div className="card-header-icon bg-surface-muted">
            <CalendarDays className="w-5 h-5 text-primary-600" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">任意日期历史回测与对比</h2>
            <p className="card-header-subtitle">
              选择日期，使用该日历史特征回放重新调用负荷模型，与 ISO-NE 真实负荷逐小时对比
            </p>
          </div>
          <RefreshButton onClick={onRefresh} isLoading={loading} className="ml-auto" />
        </div>
        <div className="py-4 flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="backtest-date" className="text-xs text-ink-muted">回测日期（ET 时区）</label>
            <input
              id="backtest-date"
              type="date"
              className="input-dark w-44"
              value={date ?? ''}
              min={range?.earliest ?? undefined}
              max={range?.latest ?? undefined}
              disabled={loading}
              onChange={(e) => { if (e.target.value) onDateChange(e.target.value) }}
            />
          </div>
          <p className="text-xs text-ink-muted pb-2.5">
            可用真实负荷范围：
            {range?.earliest || range?.latest
              ? ` ${range.earliest ?? '—'} ~ ${range.latest ?? '—'}`
              : ' 加载中…'}
            {data?.date ? ` · 当前回测：${data.date}` : ''}
          </p>
        </div>
      </div>

      {error ? (
        <ErrorBanner message={error} onRetry={onRefresh} />
      ) : loading && !data ? (
        <div className="card">
          <Spinner size="lg" />
        </div>
      ) : !data ? (
        <div className="card">
          <EmptyState
            icon={<CalendarDays className="w-12 h-12" />}
            title="选择日期查看历史回测对比"
            description="后端将重跑 24 次模型推理并与该日真实负荷对比（只读，不写入数据库）"
          />
        </div>
      ) : (
        <>
          {/* 核心指标 */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5 gap-4">
            <div className="stagger-item stagger-1 h-full ">
              <MetricCard
                title="MAE (平均绝对误差)"
                value={m ? formatNumber(m.mae_mw, 1) : '--'}
                unit="MW"
                icon={<Target className="w-5 h-5 text-primary-600" />}
                className="bg-surface-raised border-edge"
              />
            </div>
            <div className="stagger-item stagger-2 h-full ">
              <MetricCard
                title="RMSE (均方根误差)"
                value={m ? formatNumber(m.rmse_mw, 1) : '--'}
                unit="MW"
                icon={<Activity className="w-5 h-5 text-primary-600" />}
                className="bg-surface-raised border-edge"
              />
            </div>
            <div className="stagger-item stagger-3 h-full ">
              <MetricCard
                title="MAPE (平均百分比误差)"
                value={m?.mape != null ? formatNumber(m.mape, 2) : '--'}
                unit="%"
                icon={<TrendingDown className="w-5 h-5 text-primary-600" />}
                trendValue={m?.mape != null
                  ? (m.mape < 5 ? '优秀' : m.mape < 10 ? '良好' : '需关注')
                  : undefined}
                className="bg-surface-raised border-edge"
              />
            </div>
            <div className="stagger-item stagger-4 h-full ">
              <MetricCard
                title="当日实际峰值负荷"
                value={stats?.actualPeak != null ? formatNumber(stats.actualPeak, 0) : '--'}
                unit="MW"
                icon={<Zap className="w-5 h-5 text-primary-600" />}
                trendValue={stats ? `有效实际 ${stats.validCount}/24 h` : undefined}
                className="bg-surface-raised border-edge"
              />
            </div>
            <div className="stagger-item stagger-5 h-full ">
              <MetricCard
                title="最大绝对误差（小时）"
                value={stats && stats.maxAbs > 0 ? formatNumber(stats.maxAbs, 0) : '--'}
                unit="MW"
                icon={<TrendingDown className="w-5 h-5 text-primary-600" />}
                className="bg-surface-raised border-edge"
              />
            </div>
          </div>

          {/* 回测对比图 */}
          <div className="card">
            <div className="card-header">
              <div className="card-header-icon bg-surface-muted">
                <Activity className="w-5 h-5 text-primary-600" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">回测预测 vs 实际负荷（{data.date}）</h2>
                <p className="card-header-subtitle">
                  深灰实线 ISO-NE 真实负荷 · 青绿虚线模型回测预测 · 蓝色温度右轴；缺失小时为真实负荷尚未回填
                </p>
              </div>
            </div>
            <div className="py-4">
              <ResponsiveContainer width="100%" height={420}>
                <LineChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                  <CartesianGrid {...CHART_GRID} />
                  <XAxis
                    dataKey="timeLabel"
                    tick={CHART_AXIS}
                    interval="preserveStartEnd"
                    minTickGap={18}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    yAxisId="load"
                    tick={CHART_AXIS}
                    tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    yAxisId="temp"
                    orientation="right"
                    tick={CHART_AXIS}
                    tickFormatter={(v: number) => `${v}°`}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND} />
                  <Line
                    yAxisId="load"
                    type="monotone"
                    dataKey="actual"
                    name="实际负荷"
                    unit="MW"
                    stroke={CHART_COLORS.actual}
                    strokeWidth={3}
                    dot={{ r: 2.5, fill: CHART_COLORS.actual }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                  <Line
                    yAxisId="load"
                    type="monotone"
                    dataKey="forecast"
                    name="回测预测"
                    unit="MW"
                    stroke={CHART_COLORS.replay}
                    strokeWidth={3}
                    strokeDasharray="8 4"
                    dot={{ r: 2.5, fill: CHART_COLORS.replay }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                  <Line
                    yAxisId="temp"
                    type="monotone"
                    dataKey="temp"
                    name="温度"
                    unit="°C"
                    stroke={CHART_COLORS.forecast}
                    strokeWidth={2}
                    strokeDasharray="2 5"
                    dot={false}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* 当日气象概览 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: '平均温度', value: stats?.avgTemp != null ? `${formatNumber(stats.avgTemp, 1)} °C` : '--', icon: <Thermometer className="w-5 h-5 text-primary-600" /> },
              { label: '平均风速', value: stats?.avgWind != null ? `${formatNumber(stats.avgWind, 1)} m/s` : '--', icon: <Wind className="w-5 h-5 text-primary-600" /> },
              { label: '平均云量', value: stats?.avgCloud != null ? `${formatNumber(stats.avgCloud, 0)} %` : '--', icon: <Cloud className="w-5 h-5 text-ink" /> },
              { label: '峰值短波辐射', value: stats && stats.peakRadiation > 0 ? `${formatNumber(stats.peakRadiation, 0)} W/m²` : '--', icon: <Sun className="w-5 h-5 text-primary-600" /> },
            ].map((item, i) => (
              <div key={i} className="bg-surface-muted rounded p-3 border border-edge  flex items-center gap-3">
                <div className="bg-surface-muted rounded p-2">{item.icon}</div>
                <div className="min-w-0">
                  <p className="text-ink-muted text-xs mb-0.5">{item.label}</p>
                  <p className="text-ink font-bold text-sm tabular-nums">{item.value}</p>
                </div>
              </div>
            ))}
          </div>

          {/* 逐小时明细 */}
          <div className="card">
            <div className="card-header">
              <div className="card-header-icon bg-surface-muted">
                <Clock className="w-5 h-5 text-primary-600" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="card-header-title">逐小时对比明细</h2>
                <p className="card-header-subtitle">误差 = 预测 − 实际（正=高估）；实际未回填的小时显示 --</p>
              </div>
            </div>
            <div className="overflow-x-auto max-h-[600px] overflow-y-auto rounded">
              <table className="w-full text-sm table-zebra">
                <thead className="sticky top-0 z-10 bg-surface-muted">
                  <tr className="text-ink-muted border-b border-edge">
                    <th scope="col" className="text-left py-2.5 px-3 font-medium">时刻 (ET)</th>
                    <th scope="col" className="text-right py-2.5 px-3 font-medium">实际负荷 (MW)</th>
                    <th scope="col" className="text-right py-2.5 px-3 font-medium">回测预测 (MW)</th>
                    <th scope="col" className="text-right py-2.5 px-3 font-medium">误差 (MW)</th>
                    <th scope="col" className="text-right py-2.5 px-3 font-medium">绝对误差 (MW)</th>
                    <th scope="col" className="text-right py-2.5 px-3 font-medium">误差率 (%)</th>
                    <th scope="col" className="text-right py-2.5 px-3 font-medium">温度 (°C)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.pairs.map((p) => (
                    <tr key={p.target_time} className="border-b border-edge">
                      <td className="py-2.5 px-3 text-ink whitespace-nowrap">{formatEasternISO(p.target_time, ET_FULL)}</td>
                      <td className="py-2.5 px-3 text-right text-ink">
                        {p.historical_actual != null ? p.historical_actual.toFixed(1) : '--'}
                      </td>
                      <td className="py-2.5 px-3 text-right text-primary-700">{p.historical_forecast.toFixed(1)}</td>
                      <td className={`py-2.5 px-3 text-right tabular-nums ${getErrorColor(p.absolute_error_mw)}`}>
                        {p.error_mw != null ? `${p.error_mw >= 0 ? '+' : ''}${p.error_mw.toFixed(1)}` : '--'}
                      </td>
                      <td className={`py-2.5 px-3 text-right tabular-nums ${getErrorColor(p.absolute_error_mw)}`}>
                        {p.absolute_error_mw != null ? p.absolute_error_mw.toFixed(1) : '--'}
                      </td>
                      <td className={`py-2.5 px-3 text-right tabular-nums ${getErrorColor(p.absolute_error_mw)}`}>
                        {p.percentage_error != null ? `${p.percentage_error >= 0 ? '+' : ''}${p.percentage_error.toFixed(2)}` : '--'}
                      </td>
                      <td className="py-2.5 px-3 text-right text-ink">
                        {weatherByTime.get(p.target_time)?.temperature_2m != null
                          ? weatherByTime.get(p.target_time)!.temperature_2m!.toFixed(1)
                          : '--'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* 口径说明 */}
          <div className="px-4 py-2.5 rounded bg-surface-muted border border-edge text-xs text-ink leading-relaxed">
            <span className="text-load-700 font-medium">口径说明：</span>
            {data.note}
          </div>
        </>
      )}
    </div>
  )
}
