import ChartLegend from '../../components/ChartLegend'
import { CHART_COLORS, CHART_GRID, CHART_LEGEND } from '../../utils/chartTheme'
import React from 'react'
import { TrendingUp } from 'lucide-react'
import { ComposedChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import type { TrendDataPoint } from '../../types'

interface Props {
  trends: TrendDataPoint[]
  trendWindow: "hourly" | "daily" | "weekly"
  setTrendWindow: (w: "hourly" | "daily" | "weekly") => void
  trendDays: number
  setTrendDays: (n: number) => void
  loading: Record<string, boolean>
  errors: Record<string, string | null>
  loadTrends: () => void
}

export const TrendsTab: React.FC<Props> = ({ trends, trendWindow, setTrendWindow, trendDays, setTrendDays, loading, errors, loadTrends }) => {

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="card">
        <div className="card-header">
          <div className="card-header-icon bg-surface-muted">
            <TrendingUp className="w-5 h-5 text-primary-600" aria-hidden="true" />
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
              <ComposedChart data={trends} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                <CartesianGrid {...CHART_GRID} />
                <XAxis dataKey="time_label" stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false} angle={-15} textAnchor="end" height={60} padding={{ left: 24, right: 8 }} minTickGap={20} />
                <YAxis stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}`} />
                <Tooltip contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} formatter={(value: any) => [`${Number(value).toFixed(1)} MW`, '']} />
                <Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND} />
                <Area type="monotone" dataKey="predicted_load" name="预测负荷" stroke={CHART_COLORS.forecast} strokeWidth={3.2} fill={CHART_COLORS.forecast} fillOpacity={0.05} isAnimationActive={false} />
                {trends.some(t => t.actual_load != null) && (
                  <Line type="monotone" dataKey="actual_load" name="实际负荷" stroke={CHART_COLORS.actual} strokeWidth={3} dot={false} connectNulls={false} isAnimationActive={false} />
                )}
              </ComposedChart>
            </ResponsiveContainer>

            {trends.some(t => t.mape != null) && (
              <div className="mt-6">
                <h3 className="text-sm font-medium text-ink mb-3">MAPE 趋势变化</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={trends} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid {...CHART_GRID} />
                    <XAxis dataKey="time_label" stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false} angle={-15} textAnchor="end" height={60} padding={{ left: 24, right: 8 }} minTickGap={20} />
                    <YAxis stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                    <Tooltip contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} formatter={(value: any) => [`${Number(value).toFixed(2)}%`, 'MAPE']} />
                    <Line type="monotone" dataKey="mape" name="MAPE" stroke={CHART_COLORS.error} strokeWidth={3} dot={{ r: 3 }} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
