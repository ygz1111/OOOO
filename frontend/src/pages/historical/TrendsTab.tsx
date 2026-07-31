import React from 'react'
import { TrendingUp } from 'lucide-react'
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
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
}
