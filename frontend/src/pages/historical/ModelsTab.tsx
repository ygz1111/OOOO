import ChartLegend from '../../components/ChartLegend'
import { CHART_COLORS, CHART_GRID, CHART_LEGEND } from '../../utils/chartTheme'
import React from 'react'
import { BarChart3 } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { ModelTag, getInferenceColor, toNum, formatNumber, getModelColor } from './shared'
import { useApi } from '../../contexts/ApiContext'
import type { ModelComparisonItem } from '../../types'

interface Props {
  modelComparison: Record<string, ModelComparisonItem>
  modelCompareHours: number
  setModelCompareHours: (n: number) => void
  loading: Record<string, boolean>
  errors: Record<string, string | null>
  loadModelComparison: () => void
}

export const ModelsTab: React.FC<Props> = ({ modelComparison, modelCompareHours, setModelCompareHours, loading, errors, loadModelComparison }) => {
    const { systemStatus, isLoading: systemLoading, errors: systemErrors } = useApi()
    const productionModels = systemStatus?.model_details ?? []
    const statusRequestFailed = Boolean(systemErrors.systemStatus)
    const models = Object.entries(modelComparison).filter(([, item]) => item != null)
    const nullableMetric = (value: number | null | undefined) =>
      value == null || !Number.isFinite(Number(value)) ? null : Number(value)
    const chartData = models.map(([name, item], index) => ({
      name,
      label: name === 'tf_split_v1' ? '当前负荷模型' : name === 'tf_v2' ? '归档 TF v2' : name === 'ensemble' ? '归档 ensemble' : name,
      color: getModelColor(name, index),
      mape: nullableMetric(item?.mape),
      rmse: nullableMetric(item?.rmse),
      mae: nullableMetric(item?.mae),
      count: item?.count ?? 0,
      inferenceTime: toNum(item?.avg_inference_time_ms),
    }))
    const metricsTitle = models.length > 1 ? '负荷模型版本对比' : '负荷模型指标'
    const metricTooltip = (value: unknown, name: unknown): [string, string] => {
      const metric = String(name)
      const number = typeof value === 'number' || (typeof value === 'string' && value.trim())
        ? nullableMetric(Number(value)) : null
      return [number == null ? '--' : metric.startsWith('MAPE') ? `${number.toFixed(2)}%` : `${number.toFixed(1)} MW`, metric]
    }

  return (
      <div className="space-y-4 animate-fade-in">
        <section className="card" aria-labelledby="production-models-title">
          <div className="card-header flex-wrap">
            <div className="min-w-0 flex-1">
              <h2 id="production-models-title" className="card-header-title">当前生产模型</h2>
              <p className="card-header-subtitle">来自系统共享运行状态；模型已加载不代表预测输入已经就绪</p>
            </div>
            {systemStatus && <span className="text-sm text-ink-muted">
              {statusRequestFailed ? '上次报告已加载' : '已加载'} {Number.isFinite(systemStatus.models_loaded) ? systemStatus.models_loaded : '--'} / {Number.isFinite(systemStatus.models_total) ? systemStatus.models_total : '--'}
            </span>}
          </div>
          {statusRequestFailed && <p role="alert" className="mb-3 text-sm text-danger-700">
            系统状态获取失败：{systemErrors.systemStatus}。{systemStatus ? '下列为上次报告，无法确认当前加载状态。' : '无法确认当前生产模型及加载状态。'}
          </p>}
          {!statusRequestFailed && systemStatus?.status === 'error' && <p role="alert" className="mb-3 text-sm text-danger-700">系统运行状态异常，请结合各模型加载状态检查服务。</p>}
          {productionModels.length ? <div className="grid gap-3 md:grid-cols-3">
            {productionModels.map(model => <article key={model.id} className="rounded border border-edge bg-surface-muted p-3" aria-label={model.name || model.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className="min-w-0 text-sm font-semibold text-ink">{model.name || model.id}</h3>
                <span className={`shrink-0 text-xs ${model.loaded === true ? 'text-success-700' : 'text-warning-700'}`}>
                  {statusRequestFailed ? '上次报告：' : ''}{model.loaded === true ? '已加载' : model.loaded === false ? '未加载' : '状态未知'}
                </span>
              </div>
              <dl className="mt-3 space-y-1 text-xs text-ink-muted">
                <div><dt className="inline">任务：</dt><dd className="inline">{model.task || '未提供'}</dd></div>
                <div><dt className="inline">架构：</dt><dd className="inline">{model.architecture || '未提供'}</dd></div>
                <div><dt className="inline">框架：</dt><dd className="inline">{model.framework || '未提供'}</dd></div>
              </dl>
            </article>)}
          </div> : <p className="text-sm text-ink-muted" role="status">
            {systemLoading.systemStatus && !systemStatus ? '正在获取生产模型状态...' : '暂未获得生产模型明细，无法确认各模型加载状态。'}
          </p>}
        </section>
        <section className="card" aria-labelledby="load-model-metrics-title">
          <div className="card-header flex-wrap">
            <div className="card-header-icon bg-surface-muted">
              <BarChart3 className="w-5 h-5 text-primary-700" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 id="load-model-metrics-title" className="card-header-title">{metricsTitle}</h2>
              <p className="card-header-subtitle">{models.length > 1 ? '仅在共同目标小时上公平比较负荷版本；不混入电价或光伏模型' : '当前负荷版本的实测配对指标；不混入电价或光伏模型'}</p>
            </div>
            <div className="flex flex-wrap items-center gap-3 ml-auto">
              <label htmlFor="model-compare-hours" className="text-xs text-ink-muted">预测生成时间范围</label>
              <select
                id="model-compare-hours"
                aria-describedby="model-comparison-scope"
                value={modelCompareHours}
                onChange={(e) => setModelCompareHours(Number(e.target.value))}
                className="select-dark !py-1.5"
              >
                <option value={6}>最近 6 小时</option>
                <option value={24}>最近 24 小时</option>
                <option value={72}>最近 72 小时</option>
                <option value={168}>最近 168 小时</option>
                <option value={720}>最近 720 小时</option>
              </select>
              <RefreshButton onClick={loadModelComparison} isLoading={loading.models} />
            </div>
          </div>

          <div id="model-comparison-scope" className="mb-4 space-y-1 rounded border border-edge bg-surface-muted px-4 py-2.5 text-xs text-ink">
            <p>生产模型分别承担负荷、电价、光伏预测，任务和单位不同；以下仅统计负荷历史版本。窗口内只有 1 个负荷版本属正常情况。</p>
            <p>按生成时间筛选最近 {modelCompareHours} 小时内的预测记录，再按目标小时保留最新快照。目标小时含尚未到期的未来目标，因此可能大于筛选小时数；实测配对小时仅包括已回填真实值的小时，多版本只使用共同目标小时。</p>
            <p>最新快照对应不同预测提前量，指标不等同于固定提前 24 小时的精度；“--”表示缺少实测或无法公平比较。</p>
            <p>预测记录平均耗时来自预测响应记录，可能包含负荷、电价、光伏整条链耗时，并非此负荷模型单独计时。</p>
          </div>

          {errors.models ? (
            <ErrorBanner message={errors.models} onRetry={loadModelComparison} />
          ) : loading.models ? (
            <Spinner size="lg" />
          ) : chartData.length === 0 ? (
            <EmptyState icon={<BarChart3 className="w-12 h-12" />} title="暂无负荷版本统计记录" />
          ) : (
            <>
              <div className="mb-6">
                <h3 className="text-sm font-medium text-ink mb-3">MAPE{models.length > 1 ? ' 对比' : ''} (%) · 越低越好</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid {...CHART_GRID} />
                    <XAxis dataKey="label" stroke={CHART_COLORS.axis} tick={{ fill: CHART_COLORS.axis, fontSize: 12 }} tickLine={false} axisLine={false} />
                    <YAxis stroke={CHART_COLORS.axis} tick={{ fill: CHART_COLORS.axis, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                    <Tooltip formatter={metricTooltip} cursor={{ fill: 'var(--surface-muted)' }} contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
                    <Bar dataKey="mape" name="MAPE (%)" maxBarSize={56} radius={[4, 4, 0, 0]}>
                      {chartData.map((row) => (
                        <Cell key={`cell-mape-${row.name}`} fill={row.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="mb-6">
                <h3 className="text-sm font-medium text-ink mb-3">RMSE & MAE{models.length > 1 ? ' 对比' : ''} (MW)</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid {...CHART_GRID} />
                    <XAxis dataKey="label" stroke={CHART_COLORS.axis} tick={{ fill: CHART_COLORS.axis, fontSize: 12 }} tickLine={false} axisLine={false} />
                    <YAxis stroke={CHART_COLORS.axis} tick={{ fill: CHART_COLORS.axis, fontSize: 12 }} tickLine={false} axisLine={false} />
                    <Tooltip formatter={metricTooltip} cursor={{ fill: 'var(--surface-muted)' }} contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
                    <Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND} />
                    <Bar dataKey="rmse" name="RMSE (MW)" maxBarSize={56} fill={CHART_COLORS.forecast} radius={[4, 4, 0, 0]} />
                    <Bar dataKey="mae" name="MAE (MW)" maxBarSize={56} fill={CHART_COLORS.replay} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="overflow-x-auto rounded">
                <table className="w-full text-sm table-zebra">
                  <thead>
                    <tr className="text-ink-muted border-b border-edge">
                      <th scope="col" className="text-left py-2.5 px-3 font-medium">模型名称</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">目标小时（含未来）</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">实测配对小时</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">MAPE (%)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">RMSE (MW)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">MAE (MW)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium" title="来自预测响应记录，可能包含负荷、电价、光伏整条链耗时，并非此负荷模型单独计时">预测记录平均耗时 (ms)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map(([name, item]) => (
                      <tr key={name} className="border-b border-edge">
                        <td className="py-2.5 px-3 text-ink font-medium">
                          <ModelTag model={name} />
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink">{item?.count ?? 0}</td>
                        <td className="py-2.5 px-3 text-right text-ink" title={item?.comparison_note}>{item?.metric_count ?? 0}</td>
                        <td className="py-2.5 px-3 text-right text-warning-700">{formatNumber(item?.mape, 2)}</td>
                        <td className="py-2.5 px-3 text-right text-primary-700">{formatNumber(item?.rmse, 1)}</td>
                        <td className="py-2.5 px-3 text-right text-success-700">{formatNumber(item?.mae, 1)}</td>
                        <td className={`py-2.5 px-3 text-right tabular-nums ${getInferenceColor(toNum(item?.avg_inference_time_ms))}`}>
                          {formatNumber(item?.avg_inference_time_ms, 1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
  )
}
