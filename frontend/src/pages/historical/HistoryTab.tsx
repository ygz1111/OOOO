import React from 'react'
import { Database, CheckCircle } from 'lucide-react'
import { Spinner, EmptyState, ErrorBanner } from '../../components/Skeleton'
import { RefreshButton } from '../../components/ui/MicroInteractions'
import { ModelTag, SortableTh, getInferenceColor, toNum, formatTime, type SortField, type SortDirection } from './shared'
import type { PredictionRecord } from '../../types'

interface Props {
  history: PredictionRecord[]
  sortedHistory: PredictionRecord[]
  sortField: SortField
  sortDir: SortDirection
  handleSort: (field: string) => void
  historyLimit: number
  setHistoryLimit: (n: number) => void
  loading: Record<string, boolean>
  errors: Record<string, string | null>
  loadHistory: () => void
}

export const HistoryTab: React.FC<Props> = ({ history, sortedHistory, sortField, sortDir, handleSort, historyLimit, setHistoryLimit, loading, errors, loadHistory }) => {

  return (
    <div className="space-y-4">
      <div className="card tech-grid-bg">
        <div className="card-header">
          <div className="card-header-icon bg-primary-500/15">
            <Database className="w-5 h-5 text-primary-400" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="card-header-title">历史预测记录</h2>
            <p className="card-header-subtitle">浏览全部历史预测数据</p>
          </div>
          <div className="flex items-center gap-3 ml-auto">
            <select
              value={historyLimit}
              onChange={(e) => setHistoryLimit(Number(e.target.value))}
              className="select-dark !py-1.5"
            >
              <option value={20}>最近 20 条</option>
              <option value={50}>最近 50 条</option>
              <option value={100}>最近 100 条</option>
              <option value={200}>最近 200 条</option>
            </select>
            <RefreshButton onClick={loadHistory} isLoading={loading.history} />
          </div>
        </div>

        {errors.history ? (
          <ErrorBanner message={errors.history} onRetry={loadHistory} />
        ) : loading.history ? (
          <Spinner size="lg" />
        ) : history.length === 0 ? (
          <EmptyState icon={<Database className="w-12 h-12" />} title="暂无历史预测数据" />
        ) : (
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto rounded-lg">
            <table className="w-full text-sm table-zebra">
              <thead className="sticky top-0 z-10 bg-dark-800/95">
                <tr className="text-dark-400 border-b border-dark-600">
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">ID</th>
                  <SortableTh field="prediction_timestamp" currentField={sortField} currentDir={sortDir} onSort={handleSort}>预测时间</SortableTh>
                  <SortableTh field="target_timestamp" currentField={sortField} currentDir={sortDir} onSort={handleSort}>目标时间</SortableTh>
                  <SortableTh field="load_forecast_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">预测负荷</SortableTh>
                  <SortableTh field="pv_estimation_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">光伏</SortableTh>
                  <SortableTh field="wind_estimation_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">风电</SortableTh>
                  <SortableTh field="net_load_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">净负荷</SortableTh>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">置信下限</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">置信上限</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium">模型</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium">缓存</th>
                  <SortableTh field="inference_time_ms" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">耗时</SortableTh>
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">数据源</th>
                </tr>
              </thead>
              <tbody>
                {sortedHistory.map((r) => (
                  <tr key={r.id} className="border-b border-dark-700">
                    <td className="py-2 px-3 text-dark-400">{r.id}</td>
                    <td className="py-2 px-3 text-dark-300 whitespace-nowrap">{formatTime(r.prediction_timestamp)}</td>
                    <td className="py-2 px-3 text-dark-300 whitespace-nowrap">{formatTime(r.target_timestamp)}</td>
                    <td className="py-2 px-3 text-right text-white font-medium">{toNum(r.load_forecast_mw).toFixed(1)}</td>
                    <td className="py-2 px-3 text-right text-success-400">{r.pv_estimation_mw != null ? toNum(r.pv_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-cyan-400">{r.wind_estimation_mw != null ? toNum(r.wind_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-warning-400">{r.net_load_mw != null ? toNum(r.net_load_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-dark-400">{r.confidence_lower_mw != null ? toNum(r.confidence_lower_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-dark-400">{r.confidence_upper_mw != null ? toNum(r.confidence_upper_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-center">
                      <ModelTag model={r.model_type} />
                    </td>
                    <td className="py-2 px-3 text-center">
                      {r.cache_hit ? (
                        <CheckCircle className="w-4 h-4 text-success-500 mx-auto" />
                      ) : (
                        <span className="text-dark-500 text-xs">--</span>
                      )}
                    </td>
                    <td className={`py-2 px-3 text-right font-mono ${getInferenceColor(toNum(r.inference_time_ms))}`}>
                      {r.inference_time_ms != null ? toNum(r.inference_time_ms).toFixed(0) : '--'}
                    </td>
                    <td className="py-2 px-3 text-dark-400 text-xs">{r.data_source ?? '--'}</td>
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
