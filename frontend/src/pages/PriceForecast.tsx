import React, { useMemo, useState } from 'react'
import { Activity, BarChart3, Calendar, Clock, DollarSign, Download, Search, TrendingDown, TrendingUp, X } from 'lucide-react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import apiService from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import { createForecastResource, useForecastResource } from '../hooks/useForecastResource'
import { usePriceBacktest } from '../hooks/usePriceBacktest'
import MetricCard from '../components/MetricCard'
import PredictionQualityNotice from '../components/PredictionQualityNotice'
import { useForecastClock } from '../hooks/useForecastClock'
import { forecastIntervalOpen } from '../utils/time'
import { ChartSkeleton, ErrorBanner, MetricCardSkeleton } from '../components/Skeleton'
import { RefreshButton } from '../components/ui/MicroInteractions'
import { formatEasternISO, ET_DATE_TIME, ET_FULL, ET_TIME_HM, easternHourOf } from '../utils/time'
import { CHART_AXIS, CHART_COLORS, CHART_GRID, CHART_LEGEND } from '../utils/chartTheme'
import ChartLegend from '../components/ChartLegend'

const priceResource = createForecastResource(
  (forceRefresh) => apiService.getPriceForecast(forceRefresh),
  data => data.input_quality, 'price', '电价预测加载失败',
)

const PriceForecast: React.FC = () => {
  const { token } = useAuth()
  const { data: storedForecast, loading, error, refresh: loadForecast } = useForecastResource(priceResource, token ?? '')
  const now = useForecastClock()
  const forecast = useMemo(() => storedForecast ? { ...storedForecast, predictions: storedForecast.predictions.filter(row => storedForecast.input_quality?.time_basis !== 'hour_end' || forecastIntervalOpen(row.timestamp, now)) } : null, [storedForecast, now])
  const [query, setQuery] = useState('')
  const { data: backtest, date: backtestDate, range: backtestRange, loading: backtestLoading,
    error: backtestError, selectDate: loadBacktest, refresh: refreshBacktest } = usePriceBacktest(token ?? '')

  const chartData = useMemo(() => forecast?.predictions.map((item) => ({
    time: formatEasternISO(item.timestamp, ET_DATE_TIME),
    P10: item.price_p10,
    P50: item.price_p50,
    P90: item.price_p90,
  })) ?? [], [forecast])

  const stats = useMemo(() => {
    const points = forecast?.predictions ?? []
    if (!points.length) return null
    const p50 = points.map((item) => item.price_p50)
    const widths = points.map((item) => item.price_p90 - item.price_p10)
    const peak = Math.max(...p50)
    const minimum = Math.min(...p50)
    const peakIndex = p50.indexOf(peak)
    return {
      peak,
      minimum,
      average: p50.reduce((sum, value) => sum + value, 0) / p50.length,
      averageWidth: widths.reduce((sum, value) => sum + value, 0) / widths.length,
      peakTime: formatEasternISO(points[peakIndex].timestamp, ET_DATE_TIME),
    }
  }, [forecast])

  const filteredRows = useMemo(() => {
    const points = forecast?.predictions ?? []
    const normalized = query.trim().toLowerCase()
    if (!normalized) return points
    return points.filter((item) => formatEasternISO(item.timestamp, ET_DATE_TIME).toLowerCase().includes(normalized)
      || item.price_p50.toFixed(2).includes(normalized))
  }, [forecast, query])

  const backtestChart = useMemo(() => backtest?.points.map((item) => ({
    time: formatEasternISO(item.timestamp, ET_TIME_HM),
    '真实电价': item.price_actual,
    '预测 P50': item.price_p50,
    P10: item.price_p10,
    P90: item.price_p90,
  })) ?? [], [backtest])

  const exportCsv = () => {
    if (!forecast?.predictions.length) return
    const records = [
      ['小时', '时间戳(ET)', '电价P10(USD/MWh)', '电价P50(USD/MWh)', '电价P90(USD/MWh)', '区间宽度(USD/MWh)'],
      ...forecast.predictions.map((item) => [item.hour, formatEasternISO(item.timestamp, ET_FULL), item.price_p10, item.price_p50, item.price_p90, item.price_p90 - item.price_p10]),
    ]
    const csv = records.map((record) => record.join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `电价预测_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="forecast-page flex flex-col space-y-6 page-transition relative">
      <div className="page-header relative z-10">
        <div className="page-title-block">
          <h1>电价预测</h1>
          <p>未来 24 小时 RT-LMP 电价预测及 P10、P50、P90 分位值，单位 USD/MWh。</p>
        </div>
        <div className="page-actions">
          <RefreshButton onClick={loadForecast} isLoading={loading} className="btn-primary" />
          <button className="btn btn-success" onClick={exportCsv} disabled={!forecast?.predictions.length}>
            <Download className="h-4 w-4" /> 导出预测数据
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadForecast} />}
      {error && storedForecast && <p className="text-xs text-warning-700">当前请求失败，沿用上次电价结果；原生成时间 {formatEasternISO(storedForecast.timestamp, ET_FULL)}，未更新为本次预测。过期小时仍会自动隐藏。</p>}

      {loading && !forecast ? (
        <div className="metrics-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, index) => <MetricCardSkeleton key={index} />)}</div>
      ) : stats ? (
        <div className="metrics-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard title="电价峰值（P50）" value={`$${stats.peak.toFixed(2)}`} unit="/MWh" icon={<TrendingUp className="h-5 w-5 text-primary-600" />} trendValue={`预计 ${stats.peakTime} 出现`} />
          <MetricCard title="电价最低（P50）" value={`$${stats.minimum.toFixed(2)}`} unit="/MWh" icon={<TrendingDown className="h-5 w-5 text-primary-600" />} />
          <MetricCard title="电价均值（P50）" value={`$${stats.average.toFixed(2)}`} unit="/MWh" icon={<DollarSign className="h-5 w-5 text-primary-600" />} />
          <MetricCard title="平均区间宽度（P90−P10）" value={`$${stats.averageWidth.toFixed(2)}`} unit="/MWh" icon={<Activity className="h-5 w-5 text-primary-600" />} trendValue="预测不确定性参考" />
        </div>
      ) : null}

      <section className="card forecast-chart-card">
        <div className="card-header">
          <div className="card-header-icon"><DollarSign className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1"><h2 className="card-header-title">24 小时电价预测曲线</h2><p className="card-header-subtitle">仅展示电价 P10、P50、P90，单位 USD/MWh · 锚点 {forecast?.origin ? formatEasternISO(forecast.origin, ET_FULL) : '--'}</p></div>
        </div>
        {loading && !forecast ? <ChartSkeleton height={400} /> : (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={chartData} margin={{ top: 10, right: 25, left: 5, bottom: 25 }}>
              <CartesianGrid {...CHART_GRID} />
              <XAxis dataKey="time" tick={CHART_AXIS} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} angle={-30} textAnchor="end" height={55} interval="preserveStartEnd" minTickGap={22} />
              <YAxis tick={CHART_AXIS} tickLine={false} axisLine={false} tickFormatter={(value: number) => `$${value}`} width={72} domain={['auto', 'auto']} />
              <Tooltip contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} formatter={(value: number) => [`$${Number(value).toFixed(2)}/MWh`]} />
              <Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND} />
              <Line type="monotone" dataKey="P10" name="P10 下限" stroke={CHART_COLORS.lower} strokeWidth={2} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="P90" name="P90 上限" stroke={CHART_COLORS.upper} strokeWidth={2} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="P50" name="P50 中位预测" stroke={CHART_COLORS.forecast} strokeWidth={3.2} strokeLinecap="round" dot={{ r: 2.5 }} activeDot={{ r: 5 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
        <div className="mt-5"><PredictionQualityNotice quality={forecast?.input_quality} task="price" /></div>
      </section>

      <section className="card forecast-chart-card">
        <div className="card-header">
          <div className="card-header-icon"><Calendar className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1"><h2 className="card-header-title">24 小时电价历史回测</h2><p className="card-header-subtitle">历史特征重放预测，与同小时 ISO-NE 真实 RT-LMP 对比</p></div>
        </div>
        <div className="mb-4 flex flex-wrap items-center justify-end gap-3">
          <label className="page-control">
            <span>回测日期（ET）</span>
            <input aria-label="电价回测日期" type="date" value={backtestDate} min={backtestRange?.earliest} max={backtestRange?.latest} className="input-dark !w-[155px]" onChange={(event) => { void loadBacktest(event.target.value) }} />
          </label>
          <RefreshButton onClick={refreshBacktest} isLoading={backtestLoading} />
        </div>
        <p className="mb-4 text-xs text-ink-muted">
          原有日期使用冻结历史样本；较新日期按需读取 ISO-NE 与历史气象。日期上限只表示可尝试回测，若官方某小时尚未发布或历史输入不完整，会说明缺口，不会编造结果。回测使用事后气象，不等同于当时的在线预测准确率。
        </p>
        <p className="mb-3 text-xs text-ink" role="status">{backtestLoading ? `正在回测 ${backtestDate}（美国东部时间）` : backtest?.date ? `结果日期：${backtest.date}（美国东部时间）` : `所选日期：${backtestDate || '--'}（美国东部时间），尚无回测结果`}</p>
        {backtestError ? <ErrorBanner message={backtestError} onRetry={refreshBacktest} /> : backtestLoading && !backtest ? <ChartSkeleton height={320} /> : backtest && backtestChart.length ? <>
          {backtest.label_quality && <p className="mb-4 rounded border border-warning-400/25 bg-warning-500/10 px-3 py-2 text-xs text-warning-700">真实配对 {backtest.label_quality.evaluated_hours} 小时 · 排除 {backtest.label_quality.excluded_hours} 小时。{backtest.label_quality.notice}</p>}
          {backtest.metrics ? <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4"><MetricCard title="历史 MAE" value={backtest.metrics.mae_usd.toFixed(2)} unit="USD/MWh" icon={<DollarSign className="h-5 w-5 text-primary-600" />} /><MetricCard title="历史 RMSE" value={backtest.metrics.rmse_usd.toFixed(2)} unit="USD/MWh" icon={<BarChart3 className="h-5 w-5 text-primary-600" />} /><MetricCard title="历史 MAPE" value={backtest.metrics.mape_pct == null ? '--' : backtest.metrics.mape_pct.toFixed(2)} unit={backtest.metrics.mape_pct == null ? '' : '%'} icon={<Activity className="h-5 w-5 text-primary-600" />} /><MetricCard title="P10–P90 覆盖率" value={backtest.metrics.p10_p90_coverage.toFixed(1)} unit="%" icon={<TrendingUp className="h-5 w-5 text-primary-600" />} /></div> : <p className="mb-4 text-sm text-warning-700">本日暂无完整官方小时真实标签，仅展示历史特征重放预测，不计算真实误差。</p>}
          <ResponsiveContainer width="100%" height={380}>
            <LineChart data={backtestChart} margin={{ top: 10, right: 25, left: 5, bottom: 25 }}>
              <CartesianGrid {...CHART_GRID} />
              <XAxis dataKey="time" tick={CHART_AXIS} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} angle={-30} textAnchor="end" height={55} interval="preserveStartEnd" minTickGap={22} />
              <YAxis tick={CHART_AXIS} tickLine={false} axisLine={false} width={72} tickFormatter={(value: number) => `$${value}`} domain={['auto', 'auto']} />
              <Tooltip contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} formatter={(value: number) => [`$${Number(value).toFixed(2)}/MWh`]} />
              <Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND} />
              <Line type="monotone" dataKey="P10" name="P10 下限" stroke={CHART_COLORS.lower} strokeWidth={2} strokeDasharray="3 5" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="P90" name="P90 上限" stroke={CHART_COLORS.upper} strokeWidth={2} strokeDasharray="3 5" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="预测 P50" name="历史重放预测 P50" stroke={CHART_COLORS.replay} strokeWidth={3} strokeDasharray="8 5" dot={{ r: 2.5 }} activeDot={{ r: 5 }} isAnimationActive={false} />
              <Line type="monotone" dataKey="真实电价" stroke={CHART_COLORS.actual} strokeWidth={3} strokeLinecap="round" dot={{ r: 2.5 }} activeDot={{ r: 5 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
          {backtest.metric_note && <p className="mt-2 text-xs text-ink-muted">{backtest.metric_note}</p>}
        </> : <div className="py-12 text-center text-ink-muted">选择日期或点击右侧刷新按钮开始历史回测，进入页面时不自动重算</div>}
      </section>

      <section className="card">
        <div className="card-header flex-wrap">
          <div className="card-header-icon"><BarChart3 className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1"><h2 className="card-header-title">分小时电价预测</h2><p className="card-header-subtitle">P10、P50、P90 分位值与预测区间宽度</p></div>
          <div className="relative ml-auto w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} className="input-dark pl-9 pr-9" placeholder="搜索日期、时间或价格..." aria-label="搜索电价预测时间或价格" />
            {query && <button type="button" onClick={() => setQuery('')} className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded text-ink-muted hover:text-ink" aria-label="清除搜索"><X className="h-4 w-4" aria-hidden="true" /></button>}
          </div>
        </div>
        <div className="mb-2 table-result-count" aria-live="polite">匹配 {filteredRows.length} / {forecast?.predictions.length ?? 0} 个小时</div>
        <p id="price-table-scroll-hint" className="table-scroll-hint">可左右滚动查看完整明细，也可聚焦表格后使用方向键。</p>
        <div className="data-table-scroll max-h-[620px]" tabIndex={0} role="region" aria-label="分小时电价预测明细" aria-describedby="price-table-scroll-hint">
          <table className="data-table w-full min-w-[820px] text-sm">
            <thead className="sticky top-0 z-10 bg-surface-header"><tr className="border-b border-edge text-ink"><th className="px-4 py-3 text-left font-medium">时间（ET）</th><th className="px-4 py-3 text-right font-medium">P10 下限</th><th className="px-4 py-3 text-right font-medium">P50 中位</th><th className="px-4 py-3 text-right font-medium">P90 上限</th><th className="px-4 py-3 text-right font-medium">区间宽度</th><th className="px-4 py-3 text-center font-medium">时段</th></tr></thead>
            <tbody>{filteredRows.length === 0 && <tr><td colSpan={6} className="table-empty">{query ? '没有匹配结果，请调整搜索条件。' : loading ? '预测明细加载中…' : '暂无可用预测明细，请查看上方数据状态。'}</td></tr>}{filteredRows.map((item) => {
              const hour = easternHourOf(item.timestamp)
              const period = hour >= 7 && hour < 11 ? '早高峰' : hour >= 17 && hour < 22 ? '晚高峰' : hour >= 6 && hour < 23 ? '日间' : '夜间'
              return <tr key={item.timestamp} className="table-row border-b border-edge"><td className="px-4 py-3"><div className="flex items-center gap-2"><Clock className="h-4 w-4 text-ink-muted" /><span className="font-medium text-ink whitespace-nowrap tabular-nums">{formatEasternISO(item.timestamp, ET_DATE_TIME)}</span></div></td><td className="px-4 py-3 text-right tabular-nums" style={{ color: CHART_COLORS.lower }}>${item.price_p10.toFixed(2)}</td><td className="px-4 py-3 text-right font-bold tabular-nums" style={{ color: CHART_COLORS.forecast }}>${item.price_p50.toFixed(2)} <span className="text-xs font-normal text-ink-muted">/MWh</span></td><td className="px-4 py-3 text-right tabular-nums" style={{ color: CHART_COLORS.upper }}>${item.price_p90.toFixed(2)}</td><td className="px-4 py-3 text-right tabular-nums text-ink">${(item.price_p90 - item.price_p10).toFixed(2)}</td><td className="px-4 py-3 text-center"><span className="badge">{period}</span></td></tr>
            })}</tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

export default PriceForecast
