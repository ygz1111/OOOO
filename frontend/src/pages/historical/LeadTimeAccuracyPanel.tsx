import React from 'react'
import { Clock } from 'lucide-react'
import { Spinner } from '../../components/Skeleton'
import type { AccuracyStats, LeadTimeAccuracyGroup } from '../../types'
import { formatNumber } from './shared'

interface Props {
  stats: AccuracyStats | null
  loading: boolean
}

const QUALITY_LABELS = [
  { quality: 'complete', label: '完整输入' },
  { quality: 'estimated', label: '估计补齐输入' },
  { quality: 'unknown', label: '输入质量未留档' },
] as const

const metricValue = (group: { count: number; mae: number | null; rmse: number | null; mape: number | null }, key: 'mae' | 'rmse' | 'mape') => (
  group.count > 0 ? formatNumber(group[key], key === 'mape' ? 2 : 1) : '--'
)

const GroupCard: React.FC<{ group: LeadTimeAccuracyGroup }> = ({ group }) => (
  <section aria-label={group.label} className="min-w-0 rounded border border-edge bg-surface">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge bg-surface-header px-4 py-3">
      <h3 className="text-sm font-semibold text-ink">{group.label}</h3>
      <span className="text-xs text-muted">{group.count} 个独立目标小时</span>
    </div>
    <div className="px-4 py-4">
      <dl className="grid grid-cols-3 gap-3">
        {[
          { key: 'mae', label: 'MAE', unit: 'MW' },
          { key: 'rmse', label: 'RMSE', unit: 'MW' },
          { key: 'mape', label: 'MAPE', unit: '%' },
        ].map(({ key, label, unit }) => (
          <div key={key} className="min-w-0">
            <dt className="text-xs text-muted">{label} <span>({unit})</span></dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums text-ink">{metricValue(group, key as 'mae' | 'rmse' | 'mape')}</dd>
          </div>
        ))}
      </dl>
      {group.count === 0 && <p className="mt-3 text-xs text-muted">暂无已对齐实测</p>}
      <div className="mt-4 space-y-1 border-t border-edge pt-3 text-xs text-muted">
        {QUALITY_LABELS.map(({ quality, label }) => {
          const values = group.input_quality.find(item => item.quality === quality)
          return (
            <div key={quality} className="flex justify-between gap-2">
              <span>{label}</span>
              <span className="tabular-nums">{values?.count ?? '--'} 个小时</span>
            </div>
          )
        })}
      </div>
      {group.count > 0 && (
        <details className="mt-3 text-xs text-muted">
          <summary className="cursor-pointer py-1 font-medium text-primary-700">按输入质量查看误差</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <caption className="sr-only">{group.label}按输入质量的误差；MAE和RMSE单位MW，MAPE单位百分比</caption>
              <thead>
                <tr className="border-b border-edge text-muted">
                  <th scope="col" className="py-2 text-left font-medium">输入质量</th>
                  <th scope="col" className="py-2 text-right font-medium">小时数</th>
                  <th scope="col" className="py-2 text-right font-medium">MAE</th>
                  <th scope="col" className="py-2 text-right font-medium">RMSE</th>
                  <th scope="col" className="py-2 text-right font-medium">MAPE</th>
                </tr>
              </thead>
              <tbody>
                {group.input_quality.map(values => (
                  <tr key={values.quality} className="border-b border-edge">
                    <th scope="row" className="py-2 pr-2 text-left font-normal">{QUALITY_LABELS.find(item => item.quality === values.quality)?.label ?? values.label}</th>
                    <td className="py-2 text-right tabular-nums">{values.count}</td>
                    <td className="py-2 text-right tabular-nums">{metricValue(values, 'mae')}</td>
                    <td className="py-2 text-right tabular-nums">{metricValue(values, 'rmse')}</td>
                    <td className="py-2 text-right tabular-nums">{metricValue(values, 'mape')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  </section>
)

export const LeadTimeAccuracyPanel: React.FC<Props> = ({ stats, loading }) => {
  const groups = stats?.lead_time_groups
  return (
    <section className="card" aria-labelledby="lead-time-accuracy-title">
      <div className="card-header">
        <div className="card-header-icon bg-surface-muted">
          <Clock className="w-5 h-5 text-primary-600" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h2 className="card-header-title" id="lead-time-accuracy-title">按提前量统计在线负荷误差</h2>
          <p className="card-header-subtitle">仅比较同一目标小时的在线负荷预测与 ISO-NE 实际负荷</p>
        </div>
      </div>
      <div className="pb-4">
        <p className="mb-4 text-xs leading-relaxed text-muted">
          {stats?.lead_time_note ?? '按原始预测生成时间计算提前量；组内每个目标小时保留最早生成的预测。同一目标可在不同组出现，三组小时数不可相加作为总样本数。'}
        </p>
        <p className="mb-4 text-xs leading-relaxed text-muted">上方总体指标取每个目标小时的最新快照，本项分别评估不同提前量。估计补齐指预测输入，比较依据始终为实际负荷；历史输入未留档单独列示。</p>
        {loading ? <Spinner size="lg" /> : groups?.length ? (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            {groups.map(group => <GroupCard key={group.key} group={group} />)}
          </div>
        ) : (
          <p className="rounded border border-edge bg-surface-muted px-4 py-3 text-sm text-muted">暂无按提前量统计的数据，请刷新后重试。</p>
        )}
      </div>
    </section>
  )
}
