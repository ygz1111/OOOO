import { CHART_COLORS, CHART_GRID } from '../../utils/chartTheme'
import React from 'react'
import { Target } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { formatNumber } from './shared'
import type { ErrorDistribution } from '../../types'

interface Props {
  errorDist: ErrorDistribution | null
  errorDays: number
  setErrorDays: (n: number) => void
  loading: Record<string, boolean>
  errors: Record<string, string | null>
  loadErrorDist: () => void
}

export const ErrorsTab: React.FC<Props> = ({ errorDist, errorDays, setErrorDays, loading, errors, loadErrorDist }) => {

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="card">
        <div className="card-header">
          <div className="card-header-icon bg-surface-muted">
            <Target className="w-5 h-5 text-primary-600" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">预测误差分布分析</h2>
            <p className="card-header-subtitle">误差 = 预测 − 实际；正值表示高估，负值表示低估</p>
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
                { label: '平均误差', value: formatNumber(errorDist.mean_error, 1), unit: 'MW', color: 'text-ink' },
                { label: '标准差', value: formatNumber(errorDist.std_error, 1), unit: 'MW', color: 'text-ink' },
                { label: '最大绝对误差', value: formatNumber(errorDist.max_absolute_error, 1), unit: 'MW', color: 'text-danger-700' },
                { label: '偏差方向', value: errorDist.bias === 'over_predict' ? '高估' : errorDist.bias === 'under_predict' ? '低估' : '均衡', unit: '', color: errorDist.bias === 'over_predict' ? 'text-danger-700' : errorDist.bias === 'under_predict' ? 'text-warning-700' : 'text-success-700' },
              ].map((stat, i) => (
                <div key={i} className="bg-surface-muted rounded p-4  border border-edge">
                  <p className="text-ink-muted text-xs mb-1">{stat.label}</p>
                  <p className={`text-xl font-bold ${stat.color}`}>{stat.value} {stat.unit && <span className="text-sm text-ink-muted">{stat.unit}</span>}</p>
                </div>
              ))}
            </div>

            <div className="mb-6">
              <h3 className="text-sm font-medium text-ink mb-3">误差百分位数</h3>
              <div className="grid grid-cols-4 gap-3">
                {[
                  { label: 'P25', value: errorDist.percentiles?.p25, color: 'text-ink' },
                  { label: 'P50 (中位数)', value: errorDist.percentiles?.p50, color: 'text-primary-700' },
                  { label: 'P75', value: errorDist.percentiles?.p75, color: 'text-ink' },
                  { label: 'P95', value: errorDist.percentiles?.p95, color: 'text-danger-700' },
                ].map((p, i) => (
                  <div key={i} className="bg-surface-muted rounded p-3 text-center  border border-edge">
                    <p className="text-ink-muted text-xs mb-1">{p.label}</p>
                    <p className={`text-lg font-bold ${p.color}`}>{formatNumber(p.value, 1)}</p>
                    <p className="text-ink-muted text-xs">MW</p>
                  </div>
                ))}
              </div>
            </div>

            {errorDist.histogram && errorDist.histogram.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-ink mb-3">误差分布直方图</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={errorDist.histogram} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid {...CHART_GRID} />
                    <XAxis dataKey="bin" stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
                    <Bar dataKey="count" name="频次" fill={CHART_COLORS.forecast} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
