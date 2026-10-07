import React from 'react'
import MetricCard from '../../components/MetricCard'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { Database, Clock, Target, Activity, Sun, AlertTriangle, CheckCircle } from 'lucide-react'
import { StatusBadge, toNum, formatNumber, formatTime, ModelTag, getInferenceColor } from './shared'
import type { AccuracyStats, PredictionRecord } from '../../types'
import { LeadTimeAccuracyPanel } from './LeadTimeAccuracyPanel'

interface Props {
  loading: Record<string, boolean>
  accuracyStats: AccuracyStats | null
  accuracyDays: number
  setAccuracyDays: (days: number) => void
  history: PredictionRecord[]
  pvHealth: { totalRecords: number; nullCount: number; negativeCount: number; nightNonZeroCount: number; dayZeroCount: number; maxPv: number; avgPv: number; anomalies: string[]; isHealthy: boolean } | null
  errors: Record<string, string | null>
  refreshOverview: () => void
}

export const OverviewTab: React.FC<Props> = ({ loading, accuracyStats, accuracyDays, setAccuracyDays, history, pvHealth, errors, refreshOverview }) => {
  const totalPredictions = history.length
  const latestTargetRecords = Array.from(
    history.reduce((map, record) => {
      const key = String(record.target_timestamp)
      if (!map.has(key)) map.set(key, record)
      return map
    }, new Map<string, PredictionRecord>()).values(),
  )
  // 2026-08 优化：无历史记录时指标显示 '--' 占位（formatNumber(null)），
  // 不显示 0，避免把"无数据"误导为"真实值为 0"
  const actualCoverage = latestTargetRecords.length > 0
    ? (latestTargetRecords.filter(r => r.actual_load_mw != null).length / latestTargetRecords.length) * 100
    : null
  const pvRecords = latestTargetRecords.filter(r => r.pv_estimation_mw != null)
  const avgPvMw = pvRecords.length > 0
    ? pvRecords.reduce((sum, r) => sum + toNum(r.pv_estimation_mw), 0) / pvRecords.length
    : null
  const maxPvMw = pvRecords.length > 0
    ? Math.max(...pvRecords.map(r => toNum(r.pv_estimation_mw)))
    : null

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="data-toolbar text-sm">
        <label className="data-toolbar-group" htmlFor="online-accuracy-days">
        <span>统计范围</span>
        <select
          id="online-accuracy-days"
          value={accuracyDays}
          onChange={(e) => setAccuracyDays(Number(e.target.value))}
          className="select-dark !py-1.5"
          aria-label="在线误差统计时间范围"
        >
          <option value={1}>最近 1 天</option>
          <option value={7}>最近 7 天</option>
          <option value={30}>最近 30 天</option>
        </select>
        </label>
        <span className="min-w-0 flex-1 basis-[240px] text-ink-muted text-xs leading-relaxed">
          当前 TensorFlow 负荷模型的在线最新快照；
          样本 {accuracyStats?.count ?? 0} 条；仅统计已回填 ISO-NE 实际负荷的预测记录。
        </span>
        <RefreshButton onClick={refreshOverview} isLoading={!!loading.history || !!loading.accuracy} className="ml-auto" />
      </div>
      {accuracyStats?.metric_note && (
        <p className="px-1 text-xs text-ink-muted">统计说明：{accuracyStats.metric_note}</p>
      )}
      {errors.accuracy && <ErrorBanner message={errors.accuracy} onRetry={refreshOverview} />}
      {/* 核心指标（2026-08 优化：小屏 2 列 / 大屏 3 列，卡片紧凑统一） */}
      <div className="history-metrics metrics-grid grid grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5 gap-3 md:gap-4">
        <div className="stagger-item stagger-1 h-full ">
          <MetricCard
            title="历史记录数（本次查询）"
            value={totalPredictions}
            icon={<Database className="w-5 h-5 text-primary-600" />}
            className="bg-surface-raised border-edge"
          />
        </div>
        <div className="stagger-item stagger-2 h-full ">
          <MetricCard
            title={`在线快照 MAPE（最近 ${accuracyDays} 天）`}
            value={loading.accuracy ? '--' : formatNumber(accuracyStats?.mape, 2)}
            unit="%"
            icon={<Target className="w-5 h-5 text-primary-600" />}
            trend={accuracyStats?.mape != null ? 'stable' : undefined}
            trendValue={accuracyStats?.mape != null
              ? (toNum(accuracyStats.mape) < 5 ? '优秀' : toNum(accuracyStats.mape) < 10 ? '良好' : '需关注')
              : undefined}
            className="bg-surface-raised border-edge"
          />
        </div>
        <div className="stagger-item stagger-3 h-full ">
          <MetricCard
            title={`RMSE（最近 ${accuracyDays} 天）`}
            value={loading.accuracy ? '--' : formatNumber(accuracyStats?.rmse, 1)}
            unit="MW"
            icon={<Activity className="w-5 h-5 text-primary-600" />}
            className="bg-surface-raised border-edge"
          />
        </div>
        <div className="stagger-item stagger-4 h-full ">
          <MetricCard
            title="真实负荷回填覆盖率"
            value={formatNumber(actualCoverage, 1)}
            unit="%"
            icon={<CheckCircle className="w-5 h-5 text-primary-600" />}
            trend={actualCoverage != null && actualCoverage >= 80 ? 'up' : undefined}
            trendValue={actualCoverage != null ? `${latestTargetRecords.filter(r => r.actual_load_mw != null).length}/${latestTargetRecords.length} 个目标小时` : undefined}
            className="bg-surface-raised border-edge"
          />
        </div>
        <div className="stagger-item stagger-5 h-full ">
          <MetricCard
            title="光伏均值 / 峰值"
            value={formatNumber(avgPvMw, 1)}
            unit="MW"
            icon={<Sun className="w-5 h-5 text-primary-600" />}
            trendValue={maxPvMw != null ? `峰值 ${formatNumber(maxPvMw, 1)} MW` : undefined}
            className="bg-surface-raised border-edge"
          />
        </div>
      </div>

      {/* MAPE 评级徽标行 */}
      {accuracyStats?.mape != null && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm text-ink-muted">MAPE 评级：</span>
          {toNum(accuracyStats.mape) < 5 ? (
            <StatusBadge type="success" label="优秀" />
          ) : toNum(accuracyStats.mape) < 10 ? (
            <StatusBadge type="warning" label="良好" />
          ) : (
            <StatusBadge type="danger" label="需关注" />
          )}
          <span className="w-px h-4 bg-edge" />
          <span className="text-sm text-ink-muted">真实值回填：</span>
          {actualCoverage != null && actualCoverage >= 80 ? (
            <StatusBadge type="success" label="覆盖充分" />
          ) : actualCoverage != null ? (
            <StatusBadge type="warning" label="仍在回填" />
          ) : (
            <span className="text-ink-muted text-sm">--</span>
          )}
        </div>
      )}

      <LeadTimeAccuracyPanel stats={accuracyStats} loading={!!loading.accuracy} />

      {/* 光伏数据健康检测 */}
      {pvHealth && (
        <div className={`card  border-l-4 ${pvHealth.isHealthy ? 'border-l-success-500' : 'border-l-warning-500'}`}>
          <div className="card-header flex-wrap">
            <div className={`card-header-icon ${pvHealth.isHealthy ? 'bg-success-500/15' : 'bg-warning-500/15'}`}>
              <Sun className={`w-5 h-5 ${pvHealth.isHealthy ? 'text-success-700' : 'text-warning-700'}`} aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1 basis-[220px]">
              <h2 className="card-header-title">光伏预测快照健康检测</h2>
              <p className="card-header-subtitle">按目标小时去重，检查预测值结构；不等同于 ISO-NE BTM 实际值质量</p>
            </div>
            <div className="ml-auto">
              {pvHealth.isHealthy ? (
                <StatusBadge type="success" label="数据正常" />
              ) : (
                <StatusBadge type="warning" label={`发现 ${pvHealth.anomalies.length} 项异常`} />
              )}
            </div>
          </div>

          <div className="py-4 space-y-4">
            {/* 统计指标 */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {[
                { label: '去重目标小时', value: pvHealth.totalRecords, color: 'text-ink' },
                { label: '缺失值', value: pvHealth.nullCount, color: pvHealth.nullCount > 0 ? 'text-warning-700' : 'text-success-700' },
                { label: '负值数', value: pvHealth.negativeCount, color: pvHealth.negativeCount > 0 ? 'text-danger-700' : 'text-success-700' },
                { label: '夜间非零', value: pvHealth.nightNonZeroCount, color: pvHealth.nightNonZeroCount > 0 ? 'text-warning-700' : 'text-success-700' },
                { label: '峰值 (MW)', value: pvHealth.maxPv.toFixed(1), color: 'text-primary-700' },
                { label: '均值 (MW)', value: pvHealth.avgPv.toFixed(1), color: 'text-primary-700' },
              ].map((stat, i) => (
                <div key={i} className="bg-surface-muted rounded p-3 border border-edge ">
                  <p className="text-ink-muted text-xs mb-1">{stat.label}</p>
                  <p className={`text-lg font-bold ${stat.color}`}>{stat.value}</p>
                </div>
              ))}
            </div>

            {/* 异常列表 */}
            {pvHealth.anomalies.length > 0 ? (
              <div className="space-y-2">
                {pvHealth.anomalies.map((anomaly, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-warning-700 bg-warning-500/5 rounded p-3 border border-warning-500/20">
                    <AlertTriangle className="w-4 h-4 text-warning-700 flex-shrink-0 mt-0.5" />
                    <span>{anomaly}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-success-700 bg-success-500/5 rounded p-3 border border-success-500/20">
                <CheckCircle className="w-4 h-4 text-success-700 flex-shrink-0" />
                <span>光伏预测快照结构检测通过：核心昼夜时段、非负值与缺失项未发现异常。</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 最近预测记录 */}
      <div className="card">
        <div className="card-header flex-wrap">
          <div className="card-header-icon bg-surface-muted">
            <Clock className="w-5 h-5 text-primary-600" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1 basis-[220px]">
            <h2 className="card-header-title">最近预测记录</h2>
            <p className="card-header-subtitle">最新 {Math.min(history.length, 10)} 条预测数据</p>
          </div>
          <RefreshButton onClick={refreshOverview} isLoading={!!loading.history || !!loading.accuracy} className="ml-auto" />
        </div>

        {errors.history ? (
          <ErrorBanner message={errors.history} onRetry={refreshOverview} />
        ) : loading.history ? (
          <Spinner size="lg" />
        ) : history.length === 0 ? (
          <EmptyState
            icon={<Database className="w-12 h-12" />}
            title="暂无历史预测数据"
            description="请先执行预测操作以生成历史记录"
          />
        ) : (
          <>
          <p id="recent-table-scroll-hint" className="table-scroll-hint">左右滚动可查看完整记录；键盘用户可聚焦表格区域后使用方向键。</p>
          <div className="data-table-scroll" tabIndex={0} role="region" aria-label="最近预测记录表，可横向滚动" aria-describedby="recent-table-scroll-hint">
            <table className="data-table w-full min-w-[1080px] text-sm table-zebra">
              <caption className="sr-only">最近在线预测记录；时间为美国东部时间，负荷与光伏单位 MW。</caption>
              <thead>
                <tr className="text-ink-muted border-b border-edge">
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">预测时间</th>
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">目标时间</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">预测负荷 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">光伏 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">净负荷 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">实际负荷 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">误差 (MW)</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium min-w-[210px]">模型</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">耗时 (ms)</th>
                </tr>
              </thead>
              <tbody>
                {history.slice(0, 10).map((record) => (
                  <tr key={record.id} className="border-b border-edge">
                    <td className="py-2.5 px-3 text-ink whitespace-nowrap">{formatTime(record.prediction_timestamp)}</td>
                    <td className="py-2.5 px-3 text-ink whitespace-nowrap">{formatTime(record.target_timestamp)}</td>
                    <td className="py-2.5 px-3 text-right text-ink font-medium">{toNum(record.load_forecast_mw).toFixed(1)}</td>
                    <td className="py-2.5 px-3 text-right text-success-700">{record.pv_estimation_mw != null ? toNum(record.pv_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2.5 px-3 text-right text-warning-700">{record.net_load_mw != null ? toNum(record.net_load_mw).toFixed(1) : '--'}</td>
                    {/* 2026-08 优化：展示 ISO-NE 回填的实际负荷与误差，便于直接核对预测精度 */}
                    <td className="py-2.5 px-3 text-right text-success-700">
                      {record.actual_load_mw != null ? toNum(record.actual_load_mw).toFixed(1) : '--'}
                    </td>
                    <td className={`py-2.5 px-3 text-right tabular-nums ${
                      record.actual_load_mw != null
                        ? Math.abs(toNum(record.load_forecast_mw) - toNum(record.actual_load_mw)) < 300
                          ? 'text-success-700'
                          : Math.abs(toNum(record.load_forecast_mw) - toNum(record.actual_load_mw)) < 800
                            ? 'text-warning-700'
                            : 'text-danger-700'
                        : 'text-ink-muted'
                    }`}>
                      {record.actual_load_mw != null
                        ? `${(toNum(record.load_forecast_mw) - toNum(record.actual_load_mw)) >= 0 ? '+' : ''}${(toNum(record.load_forecast_mw) - toNum(record.actual_load_mw)).toFixed(1)}`
                        : '--'}
                    </td>
                    <td className="py-2.5 px-3 text-center min-w-[210px] max-w-[280px] break-words" title={record.model_type}>
                      <ModelTag model={record.model_type} />
                    </td>
                    <td className={`py-2.5 px-3 text-right tabular-nums ${getInferenceColor(toNum(record.inference_time_ms))}`}>
                      {record.inference_time_ms != null ? toNum(record.inference_time_ms).toFixed(0) : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>
    </div>
  )
}
