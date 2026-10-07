import React from 'react'
import { Database } from 'lucide-react'
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
      <div className="card">
        <div className="card-header flex-wrap">
          <div className="card-header-icon bg-surface-muted">
            <Database className="w-5 h-5 text-primary-600" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="card-header-title">历史预测记录</h2>
            <p className="card-header-subtitle">浏览全部历史预测数据</p>
          </div>
        </div>
        <div className="data-toolbar mb-4">
          <label className="data-toolbar-group" htmlFor="history-record-limit">
            <span>记录范围</span>
            <select
              id="history-record-limit"
              value={historyLimit}
              onChange={(e) => setHistoryLimit(Number(e.target.value))}
              className="select-dark !py-1.5"
            >
              <option value={20}>最近 20 条</option>
              <option value={50}>最近 50 条</option>
              <option value={100}>最近 100 条</option>
              <option value={200}>最近 200 条</option>
            </select>
          </label>
          <span className="text-xs text-ink-muted">时间统一为美国东部时间（ET），负荷与光伏单位 MW。</span>
          <RefreshButton onClick={loadHistory} isLoading={loading.history} className="ml-auto" />
        </div>

        {errors.history ? (
          <ErrorBanner message={errors.history} onRetry={loadHistory} />
        ) : loading.history ? (
          <Spinner size="lg" />
        ) : history.length === 0 ? (
          <EmptyState icon={<Database className="w-12 h-12" />} title="暂无历史预测数据" />
        ) : (
          <>
          <p id="history-table-scroll-hint" className="table-scroll-hint">左右滚动可查看全部列；键盘用户可聚焦表格区域后使用方向键。</p>
          <div className="data-table-scroll max-h-[600px] overflow-y-auto rounded" tabIndex={0} role="region" aria-label="历史预测记录表，可横向滚动" aria-describedby="history-table-scroll-hint">
            <table className="data-table w-full min-w-[1440px] text-sm table-zebra">
              <caption className="sr-only">历史在线预测快照；时间为美国东部时间，负荷与光伏单位 MW，耗时单位毫秒。</caption>
              <thead className="sticky top-0 z-10 bg-surface-muted">
                <tr className="text-ink-muted border-b border-edge">
                  <th scope="col" className="text-left py-2.5 px-3 font-medium">ID</th>
                  <SortableTh field="prediction_timestamp" currentField={sortField} currentDir={sortDir} onSort={handleSort}>预测时间</SortableTh>
                  <SortableTh field="target_timestamp" currentField={sortField} currentDir={sortDir} onSort={handleSort}>目标时间</SortableTh>
                  <SortableTh field="load_forecast_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">预测负荷</SortableTh>
                  <SortableTh field="pv_estimation_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">光伏</SortableTh>
                  <SortableTh field="net_load_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">净负荷</SortableTh>
                  <SortableTh field="actual_load_mw" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">实际负荷</SortableTh>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium" title="预测负荷 - 实际负荷（正=高估）">误差</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">置信下限</th>
                  <th scope="col" className="text-right py-2.5 px-3 font-medium">置信上限</th>
                  <th scope="col" className="text-center py-2.5 px-3 font-medium min-w-[210px]">模型</th>
                  <SortableTh field="inference_time_ms" currentField={sortField} currentDir={sortDir} onSort={handleSort} align="right">耗时</SortableTh>
                  <th scope="col" className="text-left py-2.5 px-3 font-medium min-w-[200px]">数据源</th>
                </tr>
              </thead>
              <tbody>
                {sortedHistory.map((r) => (
                  <tr key={r.id} className="border-b border-edge">
                    <td className="py-2 px-3 text-ink-muted">{r.id}</td>
                    <td className="py-2 px-3 text-ink whitespace-nowrap">{formatTime(r.prediction_timestamp)}</td>
                    <td className="py-2 px-3 text-ink whitespace-nowrap">{formatTime(r.target_timestamp)}</td>
                    <td className="py-2 px-3 text-right text-ink font-medium">{toNum(r.load_forecast_mw).toFixed(1)}</td>
                    <td className="py-2 px-3 text-right text-success-700">{r.pv_estimation_mw != null ? toNum(r.pv_estimation_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-warning-700">{r.net_load_mw != null ? toNum(r.net_load_mw).toFixed(1) : '--'}</td>
                    {/* 2026-08 优化：新增实际负荷/误差列（ISO-NE 真实值回填后显示），
                        使历史记录具备"预测 vs 实际"直接对比的分析价值 */}
                    <td className="py-2 px-3 text-right text-success-700">
                      {r.actual_load_mw != null ? toNum(r.actual_load_mw).toFixed(1) : '--'}
                    </td>
                    <td className={`py-2 px-3 text-right tabular-nums ${
                      r.actual_load_mw != null
                        ? Math.abs(toNum(r.load_forecast_mw) - toNum(r.actual_load_mw)) < 300
                          ? 'text-success-700'
                          : Math.abs(toNum(r.load_forecast_mw) - toNum(r.actual_load_mw)) < 800
                            ? 'text-warning-700'
                            : 'text-danger-700'
                        : 'text-ink-muted'
                    }`}>
                      {r.actual_load_mw != null
                        ? `${(toNum(r.load_forecast_mw) - toNum(r.actual_load_mw)) >= 0 ? '+' : ''}${(toNum(r.load_forecast_mw) - toNum(r.actual_load_mw)).toFixed(1)}`
                        : '--'}
                    </td>
                    <td className="py-2 px-3 text-right text-ink-muted">{r.confidence_lower_mw != null ? toNum(r.confidence_lower_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-right text-ink-muted">{r.confidence_upper_mw != null ? toNum(r.confidence_upper_mw).toFixed(1) : '--'}</td>
                    <td className="py-2 px-3 text-center min-w-[210px] max-w-[280px] break-words" title={r.model_type}>
                      <ModelTag model={r.model_type} />
                    </td>
                    <td className={`py-2 px-3 text-right tabular-nums ${getInferenceColor(toNum(r.inference_time_ms))}`}>
                      {r.inference_time_ms != null ? toNum(r.inference_time_ms).toFixed(0) : '--'}
                    </td>
                    <td className="py-2 px-3 text-ink-muted text-xs min-w-[200px] max-w-[280px] break-all" title={r.data_source ?? undefined}>{r.data_source ?? '--'}</td>
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
