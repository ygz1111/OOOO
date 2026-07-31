import React from 'react'
import { BarChart3 } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { ModelTag, getInferenceColor, toNum, formatNumber, MODEL_COLORS } from './shared'
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
    const models = Object.entries(modelComparison).filter(([, item]) => item != null)
    const chartData = models.map(([name, item]) => ({
      name,
      mape: toNum(item?.mape),
      rmse: toNum(item?.rmse),
      mae: toNum(item?.mae),
      count: item?.count ?? 0,
      inferenceTime: toNum(item?.avg_inference_time_ms),
    }))

  return (
      <div className="space-y-4 animate-fade-in">
        <div className="card tech-grid-bg">
          <div className="card-header">
            <div className="card-header-icon bg-primary-500/15">
              <BarChart3 className="w-5 h-5 text-primary-400" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="card-header-title">多模型预测对比</h2>
              <p className="card-header-subtitle">对比不同模型在最近 {modelCompareHours} 小时的预测表现</p>
            </div>
            <div className="flex items-center gap-3 ml-auto">
              <select
                value={modelCompareHours}
                onChange={(e) => setModelCompareHours(Number(e.target.value))}
                className="select-dark !py-1.5"
              >
                <option value={6}>最近 6 小时</option>
                <option value={24}>最近 24 小时</option>
                <option value={72}>最近 3 天</option>
                <option value={168}>最近 7 天</option>
              </select>
              <RefreshButton onClick={loadModelComparison} isLoading={loading.models} />
            </div>
          </div>

          {errors.models ? (
            <ErrorBanner message={errors.models} onRetry={loadModelComparison} />
          ) : loading.models ? (
            <Spinner size="lg" />
          ) : chartData.length === 0 ? (
            <EmptyState icon={<BarChart3 className="w-12 h-12" />} title="暂无模型对比数据" />
          ) : (
            <>
              <div className="mb-6">
                <h3 className="text-sm font-medium text-dark-300 mb-3">MAPE 对比 (越低越好)</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
                    <YAxis stroke="#64748b" fontSize={12} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }} labelStyle={{ color: '#cbd5e1' }} />
                    <Bar dataKey="mape" name="MAPE (%)" radius={[4, 4, 0, 0]}>
                      {chartData.map((_, index) => (
                        <Cell key={`cell-mape-${index}`} fill={MODEL_COLORS[index % MODEL_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="mb-6">
                <h3 className="text-sm font-medium text-dark-300 mb-3">RMSE & MAE 对比 (MW)</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
                    <YAxis stroke="#64748b" fontSize={12} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #1F2937', borderRadius: '8px' }} labelStyle={{ color: '#cbd5e1' }} />
                    <Legend wrapperStyle={{ paddingTop: '10px' }} />
                    <Bar dataKey="rmse" name="RMSE (MW)" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="mae" name="MAE (MW)" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="overflow-x-auto rounded-lg">
                <table className="w-full text-sm table-zebra">
                  <thead>
                    <tr className="text-dark-400 border-b border-dark-600">
                      <th scope="col" className="text-left py-2.5 px-3 font-medium">模型名称</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">预测次数</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">MAPE (%)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">RMSE (MW)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">MAE (MW)</th>
                      <th scope="col" className="text-right py-2.5 px-3 font-medium">平均推理时间 (ms)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map(([name, item]) => (
                      <tr key={name} className="border-b border-dark-700">
                        <td className="py-2.5 px-3 text-white font-medium">
                          <ModelTag model={name} />
                        </td>
                        <td className="py-2.5 px-3 text-right text-dark-300">{item?.count ?? 0}</td>
                        <td className="py-2.5 px-3 text-right text-warning-400">{formatNumber(item?.mape, 2)}</td>
                        <td className="py-2.5 px-3 text-right text-primary-400">{formatNumber(item?.rmse, 1)}</td>
                        <td className="py-2.5 px-3 text-right text-success-400">{formatNumber(item?.mae, 1)}</td>
                        <td className={`py-2.5 px-3 text-right font-mono ${getInferenceColor(toNum(item?.avg_inference_time_ms))}`}>
                          {formatNumber(item?.avg_inference_time_ms, 1)}
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
