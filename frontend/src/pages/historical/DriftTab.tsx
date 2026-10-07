import React from 'react'
import { Activity, AlertTriangle, CheckCircle } from 'lucide-react'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { formatNumber, toNum } from './shared'
import type { DriftDetection } from '../../types'

interface Props {
  driftResult: DriftDetection | null
  loading: Record<string, boolean>
  errors: Record<string, string | null>
  loadDrift: () => void
}

export const DriftTab: React.FC<Props> = ({ driftResult, loading, errors, loadDrift }) => {

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="card">
        <div className="card-header">
          <div className="card-header-icon bg-surface-muted">
            <Activity className="w-5 h-5 text-primary-600" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">模型漂移检测</h2>
            <p className="card-header-subtitle">检测模型预测准确性是否随时间发生显著变化</p>
          </div>
          <RefreshButton onClick={loadDrift} isLoading={loading.drift} className="ml-auto" />
        </div>

        {errors.drift ? (
          <ErrorBanner message={errors.drift} onRetry={loadDrift} />
        ) : loading.drift ? (
          <Spinner size="lg" />
        ) : !driftResult ? (
          <EmptyState icon={<Activity className="w-12 h-12" />} title="暂无漂移检测数据" />
        ) : (
          <>
            <div className={`rounded p-6 mb-6 border  ${
              driftResult.drift_detected ? 'bg-danger-500/10 border-danger-500/30' : 'bg-success-500/10 border-success-500/30'
            }`}>
              <div className="flex items-center gap-4">
                {driftResult.drift_detected ? (
                  <AlertTriangle className="w-12 h-12 text-danger-700" />
                ) : (
                  <CheckCircle className="w-12 h-12 text-success-700" />
                )}
                <div>
                  <h3 className={`text-xl font-bold ${driftResult.drift_detected ? 'text-danger-700' : 'text-success-700'}`}>
                    {driftResult.drift_detected ? '检测到模型漂移' : '模型运行稳定'}
                  </h3>
                  <p className="text-ink text-sm mt-1">
                    {driftResult.recommendation || (driftResult.drift_detected ? '建议重新训练模型或检查数据质量' : '模型预测准确性保持在正常范围内')}
                  </p>
                  {driftResult.change_percent != null && (
                    <p className="text-ink-muted text-xs mt-1">
                      相对基准变化 {driftResult.change_percent >= 0 ? '+' : ''}{formatNumber(driftResult.change_percent, 1)}% · 有效样本 {driftResult.sample_count ?? '--'}
                    </p>
                  )}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {[
                { label: '漂移评分', value: formatNumber(driftResult.drift_score, 3), sub: `阈值: ${formatNumber(driftResult.threshold, 3)}`, color: driftResult.drift_detected ? 'text-danger-700' : 'text-success-700' },
                { label: '最近 MAPE', value: `${formatNumber(driftResult.recent_mape, 2)}%`, sub: '', color: 'text-warning-700' },
                { label: '基准 MAPE', value: `${formatNumber(driftResult.baseline_mape, 2)}%`, sub: '', color: 'text-primary-700' },
              ].map((m, i) => (
                <div key={i} className="bg-surface-muted rounded p-4  border border-edge">
                  <p className="text-ink-muted text-xs mb-1">{m.label}</p>
                  <p className={`text-2xl font-bold ${m.color}`}>{m.value}</p>
                  {m.sub && <p className="text-ink-muted text-xs mt-1">{m.sub}</p>}
                </div>
              ))}
            </div>

            <div className="mt-6">
              <h3 className="text-sm font-medium text-ink mb-3">漂移评分 vs 阈值</h3>
              <div className="relative h-8 bg-surface-muted rounded-full overflow-hidden">
                <div className="absolute inset-y-0 left-0 flex items-center justify-end rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min((toNum(driftResult.drift_score) / (toNum(driftResult.threshold) * 2)) * 100, 100)}%`,
                    background: driftResult.drift_detected ? 'var(--chart-error)' : 'var(--chart-replay)'
                  }}
                />
                <div className="absolute inset-y-0 flex items-center" style={{ left: `${(toNum(driftResult.threshold) / (toNum(driftResult.threshold) * 2)) * 100}%` }}>
                  <div className="w-0.5 h-full" style={{ background: 'var(--text)', opacity: 0.6 }} />
                </div>
              </div>
              <div className="flex justify-between mt-2 text-xs text-ink-muted">
                <span>0</span>
                <span className="text-ink font-medium">阈值: {formatNumber(driftResult.threshold, 3)}</span>
                <span>{formatNumber(toNum(driftResult.threshold) * 2, 3)}</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
