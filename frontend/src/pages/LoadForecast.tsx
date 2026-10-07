import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, ChevronLeft, ChevronRight, Clock, Download, Gauge, Search, TrendingDown, TrendingUp, X } from 'lucide-react'
import { useApi } from '../contexts/ApiContext'
import MetricCard from '../components/MetricCard'
import PredictionQualityNotice from '../components/PredictionQualityNotice'
import { useForecastClock } from '../hooks/useForecastClock'
import { forecastIntervalOpen } from '../utils/time'
import LoadForecastChart from '../components/LoadForecastChart'
import { ErrorBanner, MetricCardSkeleton } from '../components/Skeleton'
import { RefreshButton } from '../components/ui/MicroInteractions'
import { formatEasternISO, ET_DATE_TIME, ET_FULL } from '../utils/time'

const PAGE_SIZE = 12

const LoadForecast: React.FC = () => {
  const { prediction: storedPrediction, overview, loadOverview, isLoading, isInitialLoad, errors, loadPrediction } = useApi()
  const now = useForecastClock()
  const prediction = useMemo(() => storedPrediction ? { ...storedPrediction, predictions: storedPrediction.predictions.filter(row => storedPrediction.input_quality?.time_basis !== 'hour_end' || forecastIntervalOpen(row.timestamp, now)) } : null, [storedPrediction, now])
  const overviewLoading = isLoading.overview
  const overviewError = errors.overview
  const [historyHours, setHistoryHours] = useState(24)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)

  const refresh = useCallback(async () => {
    await loadPrediction(true)
    await loadOverview(true)
  }, [loadOverview, loadPrediction])

  const rows = useMemo(() => {
    const source = prediction?.predictions ?? []
    const normalized = query.trim().toLowerCase()
    if (!normalized) return source
    return source.filter((item) => {
      const time = formatEasternISO(item.timestamp, ET_DATE_TIME).toLowerCase()
      return time.includes(normalized) || String(item.hour).includes(normalized) || item.load_forecast_mw.toFixed(1).includes(normalized)
    })
  }, [prediction, query])

  useEffect(() => setPage(1), [query])
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const visibleRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const forecastMetrics = useMemo(() => {
    const values = prediction?.predictions.map((item) => item.load_forecast_mw) ?? []
    if (!values.length) return null
    const peak = Math.max(...values)
    const trough = Math.min(...values)
    const average = values.reduce((sum, value) => sum + value, 0) / values.length
    const peakIndex = values.indexOf(peak)
    return { peak, trough, average, peakTime: formatEasternISO(prediction!.predictions[peakIndex].timestamp, ET_DATE_TIME) }
  }, [prediction])

  const exportCsv = () => {
    if (!prediction?.predictions.length) return
    const records = [
      ['小时', '时间戳(ET)', '负荷预测(MW)', '较前一小时变化(MW)', '较前一小时变化(%)'],
      ...prediction.predictions.map((item, index, all) => {
        const previous = index > 0 ? all[index - 1].load_forecast_mw : null
        const change = previous == null ? '' : item.load_forecast_mw - previous
        const rate = previous == null || previous === 0 ? '' : ((item.load_forecast_mw - previous) / previous) * 100
        return [item.hour, formatEasternISO(item.timestamp, ET_FULL), item.load_forecast_mw, change, rate]
      }),
    ]
    const csv = records.map((record) => record.join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `负荷预测_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6 page-transition forecast-page relative">
      <div className="page-header relative z-10">
        <div className="page-title-block">
          <h1>负荷预测</h1>
          <p>未来 24 小时区域负荷预测与历史回测校核，数据来源 ISO-NE。</p>
        </div>
        <div className="page-actions">
          <label className="page-control">
            <span>历史回看</span>
            <select value={historyHours} onChange={(event) => setHistoryHours(Number(event.target.value))} className="select-dark" aria-label="历史回看时长">
              <option value={24}>24 小时</option>
              <option value={12}>12 小时</option>
              <option value={6}>6 小时</option>
            </select>
          </label>
          <RefreshButton onClick={refresh} isLoading={isLoading.prediction || overviewLoading} className="btn-primary" />
          <button className="btn btn-success" onClick={exportCsv} disabled={!prediction?.predictions.length}>
            <Download className="h-4 w-4" /> 导出预测数据
          </button>
        </div>
      </div>

      {errors.prediction && <ErrorBanner message={errors.prediction} onRetry={refresh} />}
      {overviewError && <ErrorBanner message={overviewError} onRetry={loadOverview} />}
      {!overview && <PredictionQualityNotice quality={prediction?.input_quality} task="load" />}

      {isInitialLoad.prediction && isLoading.prediction ? (
        <div className="metrics-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => <MetricCardSkeleton key={index} />)}
        </div>
      ) : forecastMetrics ? (
        <div className="metrics-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard title="最近实测负荷" value={overview?.current.actual_load_mw == null ? '--' : overview.current.actual_load_mw.toFixed(1)} unit={overview?.current.actual_load_mw == null ? '' : 'MW'} icon={<Activity className="h-5 w-5 text-primary-600" />} trendValue={overview?.current.time ? formatEasternISO(overview.current.time, ET_DATE_TIME) : '等待 ISO-NE 回填'} />
          <MetricCard title="未来峰值负荷" value={forecastMetrics.peak.toFixed(1)} unit="MW" icon={<TrendingUp className="h-5 w-5 text-primary-600" />} trendValue={`预计 ${forecastMetrics.peakTime} 出现`} />
          <MetricCard title="未来最低负荷" value={forecastMetrics.trough.toFixed(1)} unit="MW" icon={<TrendingDown className="h-5 w-5 text-primary-600" />} />
          <MetricCard title="未来平均负荷" value={forecastMetrics.average.toFixed(1)} unit="MW" icon={<Gauge className="h-5 w-5 text-primary-600" />} />
        </div>
      ) : null}

      <section className="card forecast-chart-card">
        <div className="card-header">
          <div className="card-header-icon bg-surface-muted border border-edge"><TrendingUp className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1"><h2 className="card-header-title text-base font-bold text-ink">24 小时负荷预测曲线</h2><p className="card-header-subtitle">仅展示实际负荷、历史负荷回测和未来负荷预测，单位 MW</p></div>
        </div>
        <LoadForecastChart data={overview} isLoading={overviewLoading && !overview} isRefreshing={overviewLoading && Boolean(overview)} historyHours={historyHours} showSolar={false} height={440} />
      </section>

      <section className="card">
        <div className="card-header flex-wrap">
          <div className="card-header-icon bg-surface-muted border border-edge"><BarChart3 className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1"><h2 className="card-header-title text-base font-bold text-ink">分小时负荷预测</h2><p className="card-header-subtitle">预测值、小时变化量与峰谷时段</p></div>
          <div className="relative ml-auto w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} className="input-dark pl-9 pr-9" placeholder="搜索日期、时间或负荷..." aria-label="搜索负荷预测时间或负荷" />
            {query && <button type="button" onClick={() => setQuery('')} className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded text-ink-muted hover:text-ink" aria-label="清除搜索"><X className="h-4 w-4" aria-hidden="true" /></button>}
          </div>
        </div>
        <div className="mb-2 table-result-count" aria-live="polite">匹配 {rows.length} / {prediction?.predictions.length ?? 0} 个小时</div>
        <p id="load-table-scroll-hint" className="table-scroll-hint">可左右滚动查看完整明细，也可聚焦表格后使用方向键。</p>
        <div className="data-table-scroll max-h-[620px]" tabIndex={0} role="region" aria-label="分小时负荷预测明细" aria-describedby="load-table-scroll-hint">
          <table className="data-table w-full min-w-[760px] text-sm">
            <thead className="sticky top-0 z-10 bg-surface-header backdrop-blur-md"><tr className="border-b border-edge text-ink"><th className="px-4 py-3 text-left font-semibold">时间（ET）</th><th className="px-4 py-3 text-right font-semibold">负荷预测</th><th className="px-4 py-3 text-right font-semibold">环比变化</th><th className="px-4 py-3 text-right font-semibold">变化率</th><th className="px-4 py-3 text-center font-semibold">负荷态势</th></tr></thead>
            <tbody>{rows.length === 0 && <tr><td colSpan={5} className="table-empty">{query ? '没有匹配结果，请调整搜索条件。' : isLoading.prediction ? '预测明细加载中…' : '暂无可用预测明细，请查看上方数据状态。'}</td></tr>}
              {visibleRows.map((item) => {
                const originalIndex = prediction?.predictions.indexOf(item) ?? -1
                const previous = originalIndex > 0 ? prediction!.predictions[originalIndex - 1].load_forecast_mw : null
                const change = previous == null ? null : item.load_forecast_mw - previous
                const rate = previous == null || previous === 0 ? null : (change! / previous) * 100
                const ratio = forecastMetrics ? (item.load_forecast_mw - forecastMetrics.trough) / Math.max(forecastMetrics.peak - forecastMetrics.trough, 1) : 0
                const status = ratio >= 0.75 ? '高峰' : ratio <= 0.25 ? '低谷' : '平段'
                return (
                  <tr key={item.timestamp} className="table-row">
                    <td className="px-4 py-3"><div className="flex items-center gap-2"><Clock className="h-4 w-4 text-primary-600" /><span className="font-semibold text-ink whitespace-nowrap tabular-nums">{formatEasternISO(item.timestamp, ET_DATE_TIME)}</span></div></td>
                    <td className="px-4 py-3 text-right font-bold tabular-nums text-ink tabular-nums">{item.load_forecast_mw.toLocaleString(undefined, { maximumFractionDigits: 1 })} <span className="text-xs text-ink-muted">MW</span></td>
                    <td className={`px-4 py-3 text-right tabular-nums tabular-nums ${change == null ? 'text-ink-muted' : change >= 0 ? 'text-amber-700' : 'text-emerald-700'}`}>{change == null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(1)} MW`}</td>
                    <td className="px-4 py-3 text-right tabular-nums tabular-nums text-ink">{rate == null ? '—' : `${rate >= 0 ? '+' : ''}${rate.toFixed(2)}%`}</td>
                    <td className="px-4 py-3 text-center"><span className={`badge ${status === '高峰' ? 'badge-warning' : status === '低谷' ? 'badge-success' : 'bg-surface-muted text-ink border border-edge'}`}>{status}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-edge pt-3 text-xs text-ink-muted tabular-nums">
          <span>第 {page} / {totalPages} 页 · 共 {rows.length} 条</span>
          <div className="flex gap-2"><button className="btn btn-ghost !px-3 !py-1.5 text-xs" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page === 1} aria-label="上一页"><ChevronLeft className="h-4 w-4" aria-hidden="true" /></button><button className="btn btn-ghost !px-3 !py-1.5 text-xs" onClick={() => setPage((value) => Math.min(totalPages, value + 1))} disabled={page === totalPages} aria-label="下一页"><ChevronRight className="h-4 w-4" aria-hidden="true" /></button></div>
        </div>
      </section>
    </div>
  )
}

export default LoadForecast
