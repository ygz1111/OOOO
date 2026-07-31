import React from 'react'
import MetricCard from '../../components/MetricCard'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { Database, Clock, Target, Activity, Zap, Wind, Sun, AlertTriangle, CheckCircle } from 'lucide-react'
import { StatusBadge, toNum, formatNumber, formatTime, ModelTag, getInferenceColor } from './shared'
import type { AccuracyStats, PredictionRecord } from '../../types'

interface Props {
  loading: Record<string, boolean>
  accuracyStats: AccuracyStats | null
  history: PredictionRecord[]
  pvHealth: { totalRecords: number; nullCount: number; negativeCount: number; nightNonZeroCount: number; dayZeroCount: number; maxPv: number; avgPv: number; anomalies: string[]; isHealthy: boolean } | null
  errors: Record<string, string | null>
  loadHistory: () => void
}

export const OverviewTab: React.FC<Props> = ({ loading, accuracyStats, history, pvHealth, errors, loadHistory }) => {
  const totalPredictions = history.length
  const cacheHitRate = history.length > 0
    ? (history.filter(r => r.cache_hit).length / history.length) * 100
    : 0
  const windRecords = history.filter(r => r.wind_estimation_mw != null)
  const avgWindMw = windRecords.length > 0
    ? windRecords.reduce((sum, r) => sum + toNum(r.wind_estimation_mw), 0) / windRecords.length
    : 0
  const maxWindMw = windRecords.length > 0
    ? Math.max(...windRecords.map(r => toNum(r.wind_estimation_mw)))
    : 0
  const pvRecords = history.filter(r => r.pv_estimation_mw != null)
  const avgPvMw = pvRecords.length > 0
    ? pvRecords.reduce((sum, r) => sum + toNum(r.pv_estimation_mw), 0) / pvRecords.length
    : 0
  const maxPvMw = pvRecords.length > 0
    ? Math.max(...pvRecords.map(r => toNum(r.pv_estimation_mw)))
    : 0

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 核心指标 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="stagger-item stagger-1 h-full hover-lift">
          <MetricCard
            title="预测总记录数"
            value={loading.accuracy ? '--' : (accuracyStats?.count ?? totalPredictions)}
            icon={<Database className="w-5 h-5 text-primary-500" />}
            className="bg-gradient-to-br from-primary-500/10 to-blue-500/10 border-primary-500/20"
          />
        </div>
        <div className="stagger-item stagger-2 h-full hover-lift">
          <MetricCard
            title="MAPE (平均百分比误差)"
            value={loading.accuracy ? '--' : formatNumber(accuracyStats?.mape, 2)}
            unit="%"
            icon={<Target className="w-5 h-5 text-warning-500" />}
            trend={accuracyStats?.mape != null ? 'stable' : undefined}
            trendValue={accuracyStats?.mape != null
              ? (toNum(accuracyStats.mape) < 5 ? '优秀' : toNum(accuracyStats.mape) < 10 ? '良好' : '需关注')
              : undefined}
            className="bg-gradient-to-br from-warning-500/10 to-orange-500/10 border-warning-500/20"
          />
        </div>
        <div className="stagger-item stagger-3 h-full hover-lift">
          <MetricCard
            title="RMSE (均方根误差)"
            value={loading.accuracy ? '--' : formatNumber(accuracyStats?.rmse, 1)}
            unit="MW"
            icon={<Activity className="w-5 h-5 text-load-500" />}
            className="bg-gradient-to-br from-load-500/10 to-load-600/10 border-load-500/20"
          />
        </div>
        <div className="stagger-item stagger-4 h-full hover-lift">
          <MetricCard
            title="缓存命中率"
            value={formatNumber(cacheHitRate, 1)}
            unit="%"
            icon={<Zap className="w-5 h-5 text-success-500" />}
            trend={cacheHitRate > 50 ? 'up' : 'stable'}
            trendValue={cacheHitRate > 50 ? '高效' : '可优化'}
            className="bg-gradient-to-br from-success-500/10 to-green-500/10 border-success-500/20"
          />
        </div>
        <div className="stagger-item stagger-5 h-full hover-lift">
          <MetricCard
            title="风电均值 / 峰值"
            value={formatNumber(avgWindMw, 1)}
            unit="MW"
            icon={<Wind className="w-5 h-5 text-cyan-500" />}
            trendValue={`峰值 ${formatNumber(maxWindMw, 1)} MW`}
            className="bg-gradient-to-br from-cyan-500/10 to-teal-500/10 border-cyan-500/20"
          />
        </div>
        <div className="stagger-item stagger-6 h-full hover-lift">
          <MetricCard
            title="光伏均值 / 峰值"
            value={formatNumber(avgPvMw, 1)}
            unit="MW"
            icon={<Sun className="w-5 h-5 text-amber-500" />}
            trendValue={`峰值 ${formatNumber(maxPvMw, 1)} MW`}
            className="bg-gradient-to-br from-amber-500/10 to-orange-500/10 border-amber-500/20"
          />
        </div>
      </div>

      {/* MAPE 评级徽标行 */}
      {accuracyStats?.mape != null && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm text-dark-400">MAPE 评级：</span>
          {toNum(accuracyStats.mape) < 5 ? (
            <StatusBadge type="success" label="优秀" />
          ) : toNum(accuracyStats.mape) < 10 ? (
            <StatusBadge type="warning" label="良好" />
          ) : (
            <StatusBadge type="danger" label="需关注" />
          )}
          <span className="w-px h-4 bg-dark-600" />
          <span className="text-sm text-dark-400">缓存状态：</span>
          {cacheHitRate > 50 ? (
            <StatusBadge type="success" label="高效" />
          ) : (
            <StatusBadge type="warning" label="可优化" />
          )}
        </div>
      )}

      {/* 光伏数据健康检测 */}
      {pvHealth && (
        <div className={`card tech-grid-bg border-l-4 ${pvHealth.isHealthy ? 'border-l-success-500' : 'border-l-warning-500'}`}>
          <div className="card-header">
            <div className={`card-header-icon ${pvHealth.isHealthy ? 'bg-success-500/15' : 'bg-warning-500/15'}`}>
              <Sun className={`w-5 h-5 ${pvHealth.isHealthy ? 'text-success-400' : 'text-warning-400'}`} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">光伏历史数据健康检测</h2>
              <p className="card-header-subtitle">自动检测光伏估算数据是否存在异常</p>
            </div>
            <div className="ml-auto">
              {pvHealth.isHealthy ? (
                <StatusBadge type="success" label="数据正常" />
              ) : (
                <StatusBadge type="warning" label={`发现 ${pvHealth.anomalies.length} 项异常`} />
              )}
            </div>
          </div>

          <div className="p-4 space-y-4">
            {/* 统计指标 */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {[
                { label: '总记录数', value: pvHealth.totalRecords, color: 'text-white' },
                { label: '缺失值', value: pvHealth.nullCount, color: pvHealth.nullCount > 0 ? 'text-warning-400' : 'text-success-400' },
                { label: '负值数', value: pvHealth.negativeCount, color: pvHealth.negativeCount > 0 ? 'text-danger-400' : 'text-success-400' },
                { label: '夜间非零', value: pvHealth.nightNonZeroCount, color: pvHealth.nightNonZeroCount > 0 ? 'text-warning-400' : 'text-success-400' },
                { label: '峰值 (MW)', value: pvHealth.maxPv.toFixed(1), color: 'text-primary-400' },
                { label: '均值 (MW)', value: pvHealth.avgPv.toFixed(1), color: 'text-primary-400' },
              ].map((stat, i) => (
                <div key={i} className="bg-dark-700/50 rounded-lg p-3 border border-dark-600 hover-lift">
                  <p className="text-dark-400 text-xs mb-1">{stat.label}</p>
                  <p className={`text-lg font-bold ${stat.color}`}>{stat.value}</p>
                </div>
              ))}
            </div>

            {/* 异常列表 */}
            {pvHealth.anomalies.length > 0 ? (
              <div className="space-y-2">
                {pvHealth.anomalies.map((anomaly, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-warning-300 bg-warning-500/5 rounded-lg p-3 border border-warning-500/20">
                    <AlertTriangle className="w-4 h-4 text-warning-400 flex-shrink-0 mt-0.5" />
                    <span>{anomaly}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-success-300 bg-success-500/5 rounded-lg p-3 border border-success-500/20">
                <CheckCircle className="w-4 h-4 text-success-400 flex-shrink-0" />
                <span>光伏历史数据检测通过，未发现异常。数据符合昼夜规律，无负值或缺失。</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 最近预测记录 */}
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <Clock className="w-5 h-5 text-primary-400" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">最近预测记录</h2>
            <p className="card-header-subtitle">最新 {Math.min(history.length, 10)} 条预测数据</p>
          </div>
          <RefreshButton onClick={loadHistory} isLoading={loading.history} className="ml-auto" />
        </div>

        {errors.history ? (
          <ErrorBanner message={errors.history} onRetry={loadHistory} />
        ) : loading.history ? (
          <Spinner size="lg" />
        ) : history.length === 0 ? (
          <EmptyState
            icon={<Database className="w-12 h-12" />}
            title="暂无历史预测数据"
            description="请先执行预测操作以生成历史记录"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm table-zebra">
              <thead>
                <tr className="text-dark-400 border-b border-dark-600">
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">预测时间</th>
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">目标时间</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">预测负荷 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">光伏 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">风电 (MW)</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">净负荷 (MW)</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium">模型</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">耗时 (ms)</th>
                </tr>
              </thead>
              <tbody>
                {history.slice(0, 10).map((record) => (
                  <tr key={record.id} className="border-b border-dark-700">
                    <td className="py-2.5 px-3 text-dark-300 whitespace-nowrap">{formatTime(record.prediction_timestamp)}</td>
                    <td className="py-2.5 px-3 text-dark-300 whitespace-nowrap">{formatTime(record.target_timestamp)}</td>
                    <td className="py-2.5 px-3 text-right text-white font-medium">{toNum(record.load_forecast_mw).toFixed(1)}</td>
                    <td className="py-2.5 px-3 text-right text-success-400">{record.pv_estimation_mw != null ? toNum(record.pv_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2.5 px-3 text-right text-cyan-400">{record.wind_estimation_mw != null ? toNum(record.wind_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2.5 px-3 text-right text-warning-400">{record.net_load_mw != null ? toNum(record.net_load_mw).toFixed(1) : '--'}</td>
                    <td className="py-2.5 px-3 text-center">
                      <ModelTag model={record.model_type} />
                    </td>
                    <td className={`py-2.5 px-3 text-right font-mono ${getInferenceColor(toNum(record.inference_time_ms))}`}>
                      {record.inference_time_ms != null ? toNum(record.inference_time_ms).toFixed(0) : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
