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
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <Activity className="w-5 h-5 text-primary-400" aria-hidden="true" />
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
            <div className={`rounded-xl p-6 mb-6 border hover-lift ${
              driftResult.drift_detected ? 'bg-danger-500/10 border-danger-500/30' : 'bg-success-500/10 border-success-500/30'
            }`}>
              <div className="flex items-center gap-4">
                {driftResult.drift_detected ? (
                  <AlertTriangle className="w-12 h-12 text-danger-400" />
                ) : (
                  <CheckCircle className="w-12 h-12 text-success-400" />
                )}
                <div>
                  <h3 className={`text-xl font-bold ${driftResult.drift_detected ? 'text-danger-300' : 'text-success-300'}`}>
                    {driftResult.drift_detected ? '检测到模型漂移' : '模型运行稳定'}
                  </h3>
                  <p className="text-dark-300 text-sm mt-1">
                    {driftResult.recommendation || (driftResult.drift_detected ? '建议重新训练模型或检查数据质量' : '模型预测准确性保持在正常范围内')}
                  </p>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {[
                { label: '漂移评分', value: formatNumber(driftResult.drift_score, 3), sub: `阈值: ${formatNumber(driftResult.threshold, 3)}`, color: driftResult.drift_detected ? 'text-danger-400' : 'text-success-400' },
                { label: '最近 MAPE', value: `${formatNumber(driftResult.recent_mape, 2)}%`, sub: '', color: 'text-warning-400' },
                { label: '基准 MAPE', value: `${formatNumber(driftResult.baseline_mape, 2)}%`, sub: '', color: 'text-primary-400' },
              ].map((m, i) => (
                <div key={i} className="bg-dark-700/50 rounded-lg p-4 hover-lift border border-dark-600">
                  <p className="text-dark-400 text-xs mb-1">{m.label}</p>
                  <p className={`text-2xl font-bold ${m.color}`}>{m.value}</p>
                  {m.sub && <p className="text-dark-500 text-xs mt-1">{m.sub}</p>}
                </div>
              ))}
            </div>

            <div className="mt-6">
              <h3 className="text-sm font-medium text-dark-300 mb-3">漂移评分 vs 阈值</h3>
              <div className="relative h-8 bg-dark-700 rounded-full overflow-hidden">
                <div className="absolute inset-y-0 left-0 flex items-center justify-end rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min((toNum(driftResult.drift_score) / (toNum(driftResult.threshold) * 2)) * 100, 100)}%`,
                    background: driftResult.drift_detected ? 'linear-gradient(90deg, #f59e0b, #ef4444)' : 'linear-gradient(90deg, #10B981, #3B82F6)'
                  }}
                />
                <div className="absolute inset-y-0 flex items-center" style={{ left: `${(toNum(driftResult.threshold) / (toNum(driftResult.threshold) * 2)) * 100}%` }}>
                  <div className="w-0.5 h-full bg-white/50" />
                </div>
              </div>
              <div className="flex justify-between mt-2 text-xs text-dark-400">
                <span>0</span>
                <span className="text-white font-medium">阈值: {formatNumber(driftResult.threshold, 3)}</span>
                <span>{formatNumber(toNum(driftResult.threshold) * 2, 3)}</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
