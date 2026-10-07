import React, { useCallback, useMemo, useState } from 'react'
import { Activity, BarChart3, Clock, Download, Gauge, Search, Sun, Sunrise, Target, X, Zap } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import apiService from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import { createForecastResource, useForecastResource } from '../hooks/useForecastResource'
import MetricCard from '../components/MetricCard'
import PredictionQualityNotice from '../components/PredictionQualityNotice'
import { useForecastClock } from '../hooks/useForecastClock'
import { forecastIntervalOpen } from '../utils/time'
import { ChartSkeleton, ErrorBanner, MetricCardSkeleton } from '../components/Skeleton'
import { RefreshButton } from '../components/ui/MicroInteractions'
import { formatEasternISO, ET_DATE_TIME, ET_FULL } from '../utils/time'
import { CHART_AXIS, CHART_COLORS, CHART_GRID, CHART_LEGEND } from '../utils/chartTheme'
import ChartLegend from '../components/ChartLegend'

const solarResource = createForecastResource(
  forceRefresh => apiService.getSolarGeneration(forceRefresh),
  data => data.input_quality, 'pv', '光伏预测加载失败',
)
const modelInfoResource = createForecastResource(
  () => apiService.getSolarModelInfo(), () => null, 'pv', '光伏模型信息加载失败',
)

const SolarGeneration: React.FC = () => {
  const { token } = useAuth()
  const { data: solar, loading, error, refresh: refreshSolar } = useForecastResource(solarResource, token ?? '')
  const { data: modelInfo, error: modelInfoError, refresh: refreshModelInfo } = useForecastResource(modelInfoResource, token ?? '')
  const [query, setQuery] = useState('')
  const now = useForecastClock()

  const loadSolar = useCallback(() => Promise.all([refreshSolar(), refreshModelInfo()]), [refreshSolar, refreshModelInfo])

  const rows = useMemo(() => (solar?.hourly_pv_mw ?? []).map((value, index) => ({
    index,
    timestamp: solar?.timestamps[index] ?? '',
    pv: value,
    efficiency: solar?.hourly_efficiency?.[index] ?? null,
    uncertainty: solar?.hourly_uncertainty_mw?.[index] ?? null,
  })).filter(row => !solar?.input_quality?.time_basis || forecastIntervalOpen(row.timestamp, now, 'hour_start')), [solar, now])

  const filteredRows = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return rows
    return rows.filter((item) => formatEasternISO(item.timestamp, ET_DATE_TIME).toLowerCase().includes(normalized)
      || item.pv.toFixed(1).includes(normalized))
  }, [query, rows])

  const stats = useMemo(() => {
    if (!rows.length) return null
    const positive = rows.filter((item) => item.pv > 0)
    const peak = Math.max(...rows.map((item) => item.pv))
    const peakRow = rows.find((item) => item.pv === peak)
    return {
      total: rows.reduce((sum, item) => sum + item.pv, 0),
      peak,
      average: positive.length ? positive.reduce((sum, item) => sum + item.pv, 0) / positive.length : 0,
      capacityFactor: (solar?.capacity_factor ?? 0) * 100,
      generatingHours: positive.length,
      peakTime: peakRow?.timestamp ? formatEasternISO(peakRow.timestamp, ET_DATE_TIME) : '--',
    }
  }, [rows, solar])

  const chartData = useMemo(() => rows.map((item) => ({
    time: formatEasternISO(item.timestamp, ET_DATE_TIME),
    '光伏预测': item.pv,
  })), [rows])

  const backtestRows = useMemo(
    () => solar?.historical?.pairs ?? [],
    [solar?.historical?.pairs],
  )
  const backtestMetrics = solar?.historical?.metrics
  const backtestData = useMemo(() => backtestRows.map((item) => ({
    time: formatEasternISO(item.target_time, ET_DATE_TIME),
    'ISO-NE BTM估算': item.historical_actual,
    '模型回测预测': item.historical_forecast,
  })), [backtestRows])

  const exportCsv = () => {
    if (!rows.length) return
    const records = [
      ['小时', '时间戳(ET)', '光伏预测(MW)', '不确定性(MW)', '模型效率(%)', '光照状态'],
      ...rows.map((item) => {
        return [item.index, formatEasternISO(item.timestamp, ET_FULL), item.pv, item.uncertainty ?? '', item.efficiency ?? '', item.pv > 0 ? '有发电' : '无发电']
      }),
    ]
    const csv = records.map((record) => record.join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `光伏预测_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  const service = modelInfo?.service_status

  return (
    <div className="forecast-page space-y-6 page-transition relative">
      <div className="page-header relative z-10">
        <div className="page-title-block">
          <h1>光伏预测</h1>
          <p>未来 24 小时区域光伏出力预测，与 ISO-NE 官方 BTM 估算值进行历史校核。</p>
        </div>
        <div className="page-actions">
          <RefreshButton onClick={loadSolar} isLoading={loading} className="btn-primary" />
          <button className="btn btn-success" onClick={exportCsv} disabled={!rows.length}>
            <Download className="h-4 w-4" /> 导出预测数据
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadSolar} />}
      {error && solar && <p className="text-xs text-warning-700">当前请求失败，沿用上次光伏结果；原生成时间 {formatEasternISO(solar.timestamp, ET_FULL)}，未更新为本次预测。过期小时仍会自动隐藏。</p>}

      {loading && !solar ? (
        <div className="metrics-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">{Array.from({ length: 5 }).map((_, index) => <MetricCardSkeleton key={index} />)}</div>
      ) : stats ? (
        <div className="metrics-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard title="24h 总发电量" value={stats.total.toFixed(1)} unit="MWh" icon={<Zap className="h-5 w-5 text-primary-600" />} />
          <MetricCard title="峰值功率" value={stats.peak.toFixed(1)} unit="MW" icon={<Sun className="h-5 w-5 text-primary-600" />} trendValue={`预计 ${stats.peakTime} 出现`} />
          <MetricCard title="发电时段均值" value={stats.average.toFixed(1)} unit="MW" icon={<BarChart3 className="h-5 w-5 text-primary-600" />} />
          <MetricCard title="容量因子" value={stats.capacityFactor.toFixed(1)} unit="%" icon={<Gauge className="h-5 w-5 text-primary-600" />} />
          <MetricCard title="有效发电时长" value={stats.generatingHours} unit="小时" icon={<Sunrise className="h-5 w-5 text-primary-600" />} />
        </div>
      ) : null}

      <section className="card forecast-chart-card">
        <div className="card-header">
          <div className="card-header-icon"><Sun className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1"><h2 className="card-header-title">24 小时光伏预测曲线</h2><p className="card-header-subtitle">仅展示光伏发电功率，单位 MW · 生成时间 {solar?.timestamp ? formatEasternISO(solar.timestamp, ET_FULL) : '--'}</p></div>
        </div>
        {loading && !solar ? <ChartSkeleton height={380} /> : (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={chartData} margin={{ top: 10, right: 25, left: 5, bottom: 25 }}>
              <CartesianGrid {...CHART_GRID} />
              <XAxis dataKey="time" tick={CHART_AXIS} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} angle={-30} textAnchor="end" height={55} interval="preserveStartEnd" minTickGap={22} />
              <YAxis tick={CHART_AXIS} tickLine={false} axisLine={false} width={66} tickFormatter={(value: number) => `${value}`} domain={[0, 'auto']} />
              <Tooltip contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} formatter={(value: number) => [`${Number(value).toFixed(1)} MW`, '光伏预测']} />
              <Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND} />
              <Area type="monotone" dataKey="光伏预测" stroke={CHART_COLORS.solar} strokeWidth={3.2} strokeLinecap="round" fill={CHART_COLORS.solar} fillOpacity={0.06} dot={{ r: 2.5, fill: CHART_COLORS.solar }} activeDot={{ r: 5 }} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
        <div className="mt-5"><PredictionQualityNotice quality={solar?.input_quality} task="pv" /></div>
      </section>

      <section className="card forecast-chart-card">
        <div className="card-header">
          <div className="card-header-icon"><Target className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1">
            <h2 className="card-header-title">过去 24 小时光伏历史回测</h2>
            <p className="card-header-subtitle">历史特征重放预测，与同小时 ISO-NE 官方 BTM 估算出力对比</p>
          </div>
        </div>

        {backtestMetrics && (
          <div className="mb-5 grid grid-cols-2 gap-x-5 gap-y-4 border-b border-edge pb-5 lg:grid-cols-4">
            <div className="min-w-0">
              <p className="text-xs text-ink-muted">历史 24h MAE</p>
              <p className="mt-1 tabular-nums text-xl font-bold text-ink">{backtestMetrics.mae_mw.toFixed(1)} <span className="text-xs font-normal text-ink-muted">MW</span></p>
            </div>
            <div className="min-w-0">
              <p className="text-xs text-ink-muted">历史 24h RMSE</p>
              <p className="mt-1 tabular-nums text-xl font-bold text-ink">{backtestMetrics.rmse_mw.toFixed(1)} <span className="text-xs font-normal text-ink-muted">MW</span></p>
            </div>
            <div className="min-w-0" title="夜间和低出力时段的百分比误差不稳定；当前后端口径仅统计 ISO-NE BTM 官方估算值大于 500 MW 的时段">
              <p className="text-xs text-ink-muted">历史 24h MAPE（有出力时段）</p>
              <p className="mt-1 tabular-nums text-xl font-bold text-ink">{backtestMetrics.mape == null ? '--' : `${backtestMetrics.mape.toFixed(2)}%`}</p>
            </div>
            <div className="min-w-0">
              <p className="text-xs text-ink-muted">有效对比点</p>
              <p className="mt-1 tabular-nums text-xl font-bold text-ink">{backtestMetrics.count} <span className="text-xs font-normal text-ink-muted">小时</span></p>
              <p className="mt-1 text-[11px] text-ink-muted">MAPE 使用 {backtestMetrics.daylight_count} 个 &gt;500 MW 有效出力点</p>
            </div>
          </div>
        )}

        {loading && !solar ? <ChartSkeleton height={360} /> : backtestData.length ? (
          <ResponsiveContainer width="100%" height={380}>
            <LineChart data={backtestData} margin={{ top: 10, right: 25, left: 5, bottom: 30 }}>
              <CartesianGrid {...CHART_GRID} />
              <XAxis dataKey="time" tick={CHART_AXIS} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} angle={-30} textAnchor="end" height={65} interval="preserveStartEnd" minTickGap={22} />
              <YAxis tick={CHART_AXIS} tickLine={false} axisLine={false} width={66} domain={[0, 'auto']} />
              <Tooltip contentStyle={{ background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 4 }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} formatter={(value: number, name: string) => [`${Number(value).toFixed(1)} MW`, name]} />
              <Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND} />
              <Line type="monotone" dataKey="模型回测预测" stroke={CHART_COLORS.replay} strokeWidth={3} strokeDasharray="8 5" dot={{ r: 2.5, fill: CHART_COLORS.replay }} activeDot={{ r: 5 }} isAnimationActive={false} />
              <Line type="monotone" dataKey="ISO-NE BTM估算" stroke={CHART_COLORS.actual} strokeWidth={3} strokeLinecap="round" dot={{ r: 2.5, fill: CHART_COLORS.actual }} activeDot={{ r: 5 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex min-h-[260px] items-center justify-center rounded border border-dashed border-edge bg-surface-muted px-6 text-center">
            <div><Target className="mx-auto mb-3 h-9 w-9 text-ink-muted" /><p className="font-medium text-ink">暂无光伏回测数据</p><p className="mt-1 text-sm text-ink-muted">{solar?.historical?.note ?? '等待 ISO-NE 官方历史数据与模型回测结果'}</p></div>
          </div>
        )}
        {solar?.historical?.note && backtestData.length > 0 && (
          <p className="mt-3 rounded border border-edge bg-surface-muted px-4 py-3 text-xs leading-5 text-ink-muted">口径说明：{solar.historical.note}</p>
        )}
      </section>

      <section className="card">
        <div className="card-header flex-wrap">
          <div className="card-header-icon"><BarChart3 className="h-5 w-5 text-primary-600" /></div>
          <div className="min-w-0 flex-1"><h2 className="card-header-title">详细光伏预测数据</h2><p className="card-header-subtitle">逐小时发电功率、能量与光照状态</p></div>
          <div className="relative ml-auto w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} className="input-dark pl-9 pr-9" placeholder="搜索日期、时间或发电量..." aria-label="搜索光伏预测时间或发电量" />
            {query && <button type="button" onClick={() => setQuery('')} className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded text-ink-muted hover:text-ink" aria-label="清除搜索"><X className="h-4 w-4" aria-hidden="true" /></button>}
          </div>
        </div>
        <div className="mb-2 table-result-count" aria-live="polite">匹配 {filteredRows.length} / {rows.length} 个小时</div>
        <p id="solar-table-scroll-hint" className="table-scroll-hint">可左右滚动查看完整明细，也可聚焦表格后使用方向键。</p>
        <div className="data-table-scroll max-h-[620px]" tabIndex={0} role="region" aria-label="分小时光伏预测明细" aria-describedby="solar-table-scroll-hint">
          <table className="data-table w-full min-w-[780px] text-sm">
            <thead className="sticky top-0 z-10 bg-surface-header"><tr className="border-b border-edge text-ink"><th className="px-4 py-3 text-left font-medium">时间（ET）</th><th className="px-4 py-3 text-right font-medium">光伏功率</th><th className="px-4 py-3 text-right font-medium">小时发电量</th><th className="px-4 py-3 text-right font-medium">相对峰值</th><th className="px-4 py-3 text-right font-medium">预测不确定性</th><th className="px-4 py-3 text-center font-medium">光照状态</th></tr></thead>
            <tbody>{filteredRows.length === 0 && <tr><td colSpan={6} className="table-empty">{query ? '没有匹配结果，请调整搜索条件。' : loading ? '预测明细加载中…' : '暂无可用预测明细，请查看上方数据状态。'}</td></tr>}{filteredRows.map((item) => {
              const generating = item.pv > 0
              const ratio = stats?.peak ? (item.pv / stats.peak) * 100 : 0
              return <tr key={`${item.timestamp}-${item.index}`} className="table-row border-b border-edge"><td className="px-4 py-3"><div className="flex items-center gap-2"><Clock className="h-4 w-4 text-ink-muted" /><span className="font-medium text-ink whitespace-nowrap tabular-nums">{formatEasternISO(item.timestamp, ET_DATE_TIME)}</span></div></td><td className="px-4 py-3 text-right font-bold tabular-nums" style={{ color: CHART_COLORS.solar }}>{item.pv.toFixed(1)} <span className="text-xs font-normal text-ink-muted">MW</span></td><td className="px-4 py-3 text-right tabular-nums text-ink">{item.pv.toFixed(1)} MWh</td><td className="px-4 py-3 text-right tabular-nums text-ink">{ratio.toFixed(1)}%</td><td className="px-4 py-3 text-right tabular-nums text-ink">{item.uncertainty == null ? '—' : `±${item.uncertainty.toFixed(1)} MW`}</td><td className="px-4 py-3 text-center"><span className="badge">{generating ? '有发电' : '无发电'}</span></td></tr>
            })}</tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-header"><div className="card-header-icon"><Activity className="h-5 w-5 text-primary-600" /></div><div className="min-w-0 flex-1"><h2 className="card-header-title">模型运行信息</h2><p className="card-header-subtitle">当前光伏预测服务的实际配置</p></div></div>
        {modelInfoError && <p className="mb-3 text-xs text-warning-700">模型说明暂不可用：{modelInfoError}，将自动重试。</p>}
        <div className="grid grid-cols-2 gap-x-5 gap-y-4 md:grid-cols-4"><div className="min-w-0"><p className="text-xs text-ink-muted">加载状态</p><p className="mt-2 font-semibold text-success-700">{service ? service.loaded ? '已加载' : '未加载' : '待确认'}</p></div><div className="min-w-0"><p className="text-xs text-ink-muted">输入窗口</p><p className="mt-2 font-semibold text-ink">{service?.lookback ?? solar?.lookback_hours ?? 96} 小时</p></div><div className="min-w-0"><p className="text-xs text-ink-muted">预测长度</p><p className="mt-2 font-semibold text-ink">{service?.horizon ?? solar?.horizon_hours ?? 24} 小时</p></div><div className="min-w-0"><p className="text-xs text-ink-muted">推理耗时</p><p className="mt-2 font-semibold text-ink">{solar?.inference_time_ms?.toFixed(1) ?? '--'} ms</p></div></div>
      </section>
    </div>
  )
}

export default SolarGeneration
