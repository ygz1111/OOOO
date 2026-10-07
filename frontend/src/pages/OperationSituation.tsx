import ChartLegend from '../components/ChartLegend'
import { CHART_COLORS, CHART_GRID, CHART_LEGEND } from '../utils/chartTheme'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Activity, AlertTriangle, BatteryCharging, BarChart3, BrainCircuit, Play, Sun, Target, TrendingDown, TrendingUp, Zap } from 'lucide-react'
import apiService from '../services/api'
import type { FeatureSensitivity } from '../types'
import MetricCard from '../components/MetricCard'
import { EmptyState, ErrorBanner, Spinner } from '../components/Skeleton'
import { RefreshButton } from '../components/ui/MicroInteractions'
import PredictionQualityNotice from '../components/PredictionQualityNotice'
import { useForecastClock } from '../hooks/useForecastClock'
import { forecastIntervalOpen } from '../utils/time'
import { useAuth } from '../contexts/AuthContext'
import { createForecastResource, useForecastResource } from '../hooks/useForecastResource'

const tooltipStyle = { background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: '4px' }
const tooltipItemStyle = { color: 'var(--text)' }
const tooltipLabelStyle = { color: 'var(--text)' }

const situationResource = createForecastResource(
  async () => (await apiService.getOperationSituation()).data,
  data => {
    const quality = data.input_quality
    // 综合运行态势需同时等到负荷与光伏可用；重试策略复用现有资源调度器。
    const degraded = [quality?.components?.load, quality?.components?.pv]
      .find(component => component?.status === 'unavailable' || component?.status === 'cached')
    return degraded ? { ...quality, components: { load: degraded } } : quality
  }, 'load', '加载运行态势失败',
)
const createDiagnosticsResource = (days: number) => createForecastResource(
  async () => {
    const data = (await apiService.getHourlyErrorDiagnostics(days)).data
    if (data.days !== days) throw new Error(`返回的误差样本范围与所选 ${days} 天不一致，请重试`)
    return data
  },
  () => null, 'diagnostics', '加载误差诊断失败',
)
const diagnosticsResources = new Map<number, ReturnType<typeof createDiagnosticsResource>>()
const getDiagnosticsResource = (days: number) => {
  let resource = diagnosticsResources.get(days)
  if (!resource) {
    resource = createDiagnosticsResource(days)
    diagnosticsResources.set(days, resource)
  }
  return resource
}

interface HeatmapView {
  dates: string[]
  values: Map<string, { hour: number; date: string; error_mw: number }>
  maxAbsError: number
}

// 热力图网格（最多 720 个单元格）。提取为 memo 组件：
// situation/诊断数据到达触发页面重渲染时，只要 heatmap 引用不变就跳过重渲染，
// 避免每次都对全部单元格做颜色/标题计算造成首屏卡顿。
const ErrorHeatmapGrid = React.memo(({ heatmap }: { heatmap: HeatmapView }) => (
  <div className="min-w-[760px]" style={{ display: 'grid', gridTemplateColumns: `72px repeat(24, minmax(22px, 1fr))`, gap: 3 }}>
    <div />
    {Array.from({ length: 24 }, (_, hour) => <div key={hour} className="text-[10px] text-ink-muted text-center">{String(hour).padStart(2, '0')}</div>)}
    {heatmap.dates.map(date => <React.Fragment key={date}><div className="text-xs text-ink-muted pr-2 self-center">{date.slice(5)}</div>{Array.from({ length: 24 }, (_, hour) => { const point = heatmap.values.get(`${date}-${hour}`); const ratio = point ? Math.min(1, Math.abs(point.error_mw) / heatmap.maxAbsError) : 0; const color = !point ? 'var(--surface-muted)' : point.error_mw >= 0 ? `rgba(var(--chart-error-rgb),${0.18 + ratio * 0.72})` : `rgba(var(--chart-forecast-rgb),${0.18 + ratio * 0.72})`; return <div key={hour} title={point ? `${date} ${String(hour).padStart(2, '0')}:00：${point.error_mw > 0 ? '高估' : '低估'} ${Math.abs(point.error_mw).toFixed(1)} MW` : '无已回填样本'} className="h-6 rounded-sm " style={{ background: color, border: '1px solid var(--surface)' }} /> })}</React.Fragment>)}
  </div>
))

const HourlyDiagnosticsPanel: React.FC<{ scope: string }> = ({ scope }) => {
  const [days, setDays] = useState(7)
  // 各样本范围独立缓存与 loading/error，旧请求只能更新它自己的资源。
  const { data: diagnostics, loading: diagnosticsLoading, error: diagnosticsError, refresh: loadDiagnostics } = useForecastResource(getDiagnosticsResource(days), scope)
  const errorBars = useMemo(() => diagnostics?.hourly.map(item => ({
    ...item, label: `${String(item.hour).padStart(2, '0')}:00`,
  })) ?? [], [diagnostics])
  const heatmap = useMemo(() => {
    const entries = diagnostics?.heatmap ?? []
    const dates = [...new Set(entries.map(entry => entry.date))].sort()
    const values = new Map(entries.map(entry => [`${entry.date}-${entry.hour}`, entry]))
    const maxAbsError = Math.max(1, ...entries.map(entry => Math.abs(entry.error_mw)))
    return { dates, values, maxAbsError }
  }, [diagnostics])
  return (
      <div className="card min-w-0 relative z-10"><div className="card-header flex-wrap"><div className="card-header-icon bg-surface-muted"><Target className="w-5 h-5 text-primary-600"/></div><div className="min-w-0 flex-1"><h2 className="card-header-title">分小时误差热力图与偏差诊断</h2><p className="card-header-subtitle">基于已回填 ISO-NE 实际负荷的历史预测记录</p></div></div><div className="data-toolbar mb-4"><label className="page-control"><span>样本范围</span><select aria-label="误差诊断样本范围" value={days} onChange={event => setDays(Number(event.target.value))} className="select-dark !py-1.5"><option value={7}>最近 7 天</option><option value={14}>最近 14 天</option><option value={30}>最近 30 天</option></select></label><div className="data-toolbar-group"><RefreshButton onClick={loadDiagnostics} isLoading={diagnosticsLoading}/></div></div>
        {diagnosticsError && <ErrorBanner message={diagnosticsError} onRetry={loadDiagnostics}/> }
        {!diagnostics ? (diagnosticsError ? null : <Spinner size="lg"/>) : diagnostics.sample_count > 0 ? <><ResponsiveContainer width="100%" height={260}><BarChart data={errorBars}><CartesianGrid {...CHART_GRID}/><XAxis dataKey="label" stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><YAxis stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><Tooltip contentStyle={tooltipStyle} itemStyle={tooltipItemStyle} labelStyle={tooltipLabelStyle} formatter={(value: number) => [`${Number(value).toFixed(1)} MW`, '平均绝对误差']}/><Bar dataKey="mae_mw" name="平均绝对误差" radius={[4,4,0,0]} isAnimationActive={false}>{errorBars.map(entry => <Cell key={entry.hour} fill={entry.mae_mw != null && entry.mae_mw > 0 ? CHART_COLORS.error : CHART_COLORS.grid}/>)}</Bar></BarChart></ResponsiveContainer>
          <div className="mt-6"><h3 id="error-heatmap-title" className="text-sm font-medium text-ink mb-3">日期 × 小时误差热力图 <span className="text-ink-muted font-normal">（蓝色：低估；红色：高估；颜色越深，偏差越大）</span></h3><div className="data-table-scroll" role="region" aria-labelledby="error-heatmap-title" tabIndex={0}><ErrorHeatmapGrid heatmap={heatmap} /></div></div>
          <div className="mt-4 rounded bg-surface-muted border border-edge p-4 text-sm"><p className="text-ink">{diagnostics.insight}</p><p className="text-ink-muted mt-2">{diagnostics.method_note}</p></div></> : <EmptyState icon={<Target className="w-10 h-10"/>} title="暂无可诊断的误差样本" description="等待 ISO-NE 实际负荷回填后，将自动计算分小时误差。"/>}
      </div>
  )
}

const OperationSituationPage: React.FC = () => {
  const { token } = useAuth()
  const scope = token ?? ''
  const { data: cachedSituation, loading, error, refresh: loadSituation } = useForecastResource(situationResource, scope)
  const now = useForecastClock()
  // Derived summaries must expire with their rows; never keep yesterday's peak as today's.
  const situation = cachedSituation?.hourly.every(row => forecastIntervalOpen(row.timestamp, now, 'hour_end')) ? cachedSituation : null
  const expiredRefresh = useRef<string | null>(null)
  useEffect(() => {
    if (!cachedSituation || situation) return
    const expiredHour = cachedSituation.hourly.find(row => !forecastIntervalOpen(row.timestamp, now, 'hour_end'))?.timestamp
    if (!expiredHour) return
    const key = `${scope}:${expiredHour}`
    if (expiredRefresh.current === key) return
    // 整点已结束的目标小时需立即更新，而不必等到上次请求后 5 分钟。
    // 以目标小时限一次；上游仍返回旧窗口时由原有重试/轮询继续处理。
    expiredRefresh.current = key
    void loadSituation()
  }, [cachedSituation, situation, now, scope, loadSituation])
  const [sensitivity, setSensitivity] = useState<FeatureSensitivity | null>(null)
  const [sensitivityLoading, setSensitivityLoading] = useState(false)
  const [sensitivityRequested, setSensitivityRequested] = useState(false)
  const [sensitivityError, setSensitivityError] = useState<string | null>(null)
  const sensitivityPending = useRef<Promise<void> | null>(null)

  const loadSensitivity = useCallback(() => {
    if (sensitivityPending.current) return sensitivityPending.current
    setSensitivityRequested(true)
    setSensitivityLoading(true)
    const task = Promise.resolve().then(async () => {
      try {
        const response = await apiService.getFeatureSensitivity()
        setSensitivity(response.data)
        setSensitivityError(null)
      } catch (cause) {
        setSensitivityError(cause instanceof Error ? cause.message : '加载特征敏感度失败')
      }
    }).finally(() => {
      sensitivityPending.current = null
      setSensitivityLoading(false)
    })
    sensitivityPending.current = task
    return task
  }, [])

  return (
    <div className="space-y-6 animate-fade-in relative">
      <div className="page-header flex flex-wrap items-start justify-between gap-4 relative z-10">
        <div className="min-w-0">
          <h1>运行分析</h1>
          <p>负荷、光伏出力、净负荷及历史预测误差分析。</p>
        </div>
        <div className="page-actions">
          <RefreshButton onClick={loadSituation} isLoading={loading} className="btn-primary" />
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={loadSituation} />}
      <PredictionQualityNotice quality={cachedSituation?.input_quality} />
      {((!cachedSituation && !error) || loading) && !situation ? <Spinner size="lg" /> : situation ? <>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5 gap-4 relative z-10">
          <MetricCard title="新能源平均占比" value={situation.renewable.average_share_percent?.toFixed(1) ?? '—'} unit="%" icon={<Sun className="w-5 h-5 text-primary-600" />} trend="up" trendValue={`最高 ${situation.renewable.highest_share_time}`} />
          <MetricCard title="电网最大净负荷" value={situation.supply_demand.maximum_net_load_mw?.toFixed(0) ?? '—'} unit="MW" icon={<Zap className="w-5 h-5 text-primary-600" />} trend="stable" trendValue={situation.supply_demand.maximum_net_load_time} />
          <MetricCard title="负荷峰谷差" value={situation.peak_valley.spread_mw?.toFixed(0) ?? '—'} unit="MW" icon={<TrendingUp className="w-5 h-5 text-primary-600" />} trend="up" trendValue={`${situation.peak_valley.peak_time} 峰值`} />
          <MetricCard title="净负荷最大爬坡" value={situation.supply_demand.maximum_net_load_ramp_mw?.toFixed(0) ?? '—'} unit="MW/h" icon={<Activity className="w-5 h-5 text-primary-600" />} trend="stable" trendValue={situation.supply_demand.ramp_time} />
          <MetricCard title="预测区间光伏电量" value={situation.renewable.total_energy_mwh?.toFixed(0) ?? '—'} unit="MWh" icon={<BatteryCharging className="w-5 h-5 text-primary-600" />} trend="stable" trendValue={`负荷覆盖 ${situation.data_scope.horizon_hours} 小时，光伏配对 ${situation.data_scope.pv_coverage_hours ?? '—'} 小时`} />
        </div>

        <div className="card min-w-0 relative z-10">
          <div className="card-header">
            <div className="card-header-icon bg-surface-muted"><BarChart3 className="w-5 h-5 text-primary-600" /></div>
            <div className="min-w-0 flex-1"><h2 className="card-header-title text-base font-bold text-ink">负荷与光伏预测曲线</h2><p className="card-header-subtitle">按同一目标小时展示负荷、光伏出力和净负荷</p></div>
          </div>
          <ResponsiveContainer width="100%" height={360}>
            <ComposedChart data={situation.hourly} margin={{ top: 10, right: 24, left: 0, bottom: 0 }}>
              <CartesianGrid {...CHART_GRID}/><XAxis dataKey="time_label" stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><YAxis stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><Tooltip contentStyle={tooltipStyle} itemStyle={tooltipItemStyle} labelStyle={tooltipLabelStyle} formatter={(value: number, name) => [`${Number(value).toFixed(1)} MW`, name]} /><Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND}/>
              <Area type="monotone" dataKey="load_mw" name="预测负荷" stroke={CHART_COLORS.forecast} fill={CHART_COLORS.forecast} fillOpacity={0.05} strokeWidth={3.2} isAnimationActive={false}/>
              <Line type="monotone" dataKey="renewable_mw" name="新能源出力" stroke={CHART_COLORS.solar} strokeWidth={3.2} dot={false} isAnimationActive={false}/>
              <Line type="monotone" dataKey="net_load_mw" name="净负荷" stroke={CHART_COLORS.actual} strokeWidth={3} strokeDasharray="8 4" dot={false} isAnimationActive={false}/>
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 relative z-10">
          <div className="card"><div className="card-header"><div className="card-header-icon bg-surface-muted"><Sun className="w-5 h-5 text-primary-600" /></div><div className="min-w-0 flex-1"><h2 className="card-header-title">光伏出力与贡献</h2><p className="card-header-subtitle">光伏预测出力及其占负荷比例</p></div></div>
            <ResponsiveContainer width="100%" height={340}><AreaChart data={situation.hourly}><CartesianGrid {...CHART_GRID}/><XAxis dataKey="time_label" stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><YAxis stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><Tooltip contentStyle={tooltipStyle} itemStyle={tooltipItemStyle} labelStyle={tooltipLabelStyle}/><Legend content={<ChartLegend />} wrapperStyle={CHART_LEGEND}/><Area type="monotone" dataKey="pv_mw" name="光伏" stroke={CHART_COLORS.solar} strokeWidth={3.2} fill={CHART_COLORS.solar} fillOpacity={0.06} isAnimationActive={false}/></AreaChart></ResponsiveContainer>
            <div className="grid grid-cols-2 gap-3 mt-3 text-sm"><div className="bg-surface-muted rounded p-3"><span className="text-ink-muted">最高占比</span><p className="text-success-700 font-bold text-lg">{situation.renewable.highest_share_percent?.toFixed(1) ?? '—'}%</p></div><div className="bg-surface-muted rounded p-3"><span className="text-ink-muted">发生时段</span><p className="text-ink font-bold text-lg">{situation.renewable.highest_share_time}</p></div></div>
          </div>
          <div className="card"><div className="card-header"><div className="card-header-icon bg-surface-muted"><TrendingDown className="w-5 h-5 text-primary-600" /></div><div className="min-w-0 flex-1"><h2 className="card-header-title">峰谷与供需分析</h2><p className="card-header-subtitle">新能源后的常规电源/储能承担需求</p></div></div>
            <div className="grid grid-cols-2 gap-3 mb-5">{[
              ['负荷峰值', situation.peak_valley.peak_load_mw, 'MW', situation.peak_valley.peak_time], ['负荷谷值', situation.peak_valley.valley_load_mw, 'MW', situation.peak_valley.valley_time], ['峰时新能源削减', situation.peak_valley.renewable_peak_reduction_mw, 'MW', '峰值时段'], ['最大净负荷', situation.peak_valley.peak_net_load_mw, 'MW', situation.peak_valley.peak_net_load_time],
            ].map(([label, value, unit, sub]) => <div key={String(label)} className="bg-surface-muted border border-edge rounded p-3"><p className="text-ink-muted text-xs">{label}</p><p className="text-ink font-bold text-xl">{value == null ? '—' : Number(value).toFixed(0)} <span className="text-xs text-ink-muted">{unit}</span></p><p className="text-primary-700 text-xs mt-1">{sub}</p></div>)}</div>
            <div className="rounded border border-edge bg-surface-muted p-4 text-sm text-ink leading-relaxed"><span className="text-ink font-medium">口径说明：</span>{situation.supply_demand.interpretation}</div>
          </div>
        </div>

        <div className="card min-w-0 relative z-10"><div className="card-header flex-wrap"><div className="card-header-icon bg-surface-muted"><AlertTriangle className="w-5 h-5 text-primary-600" /></div><div className="min-w-0 flex-1"><h2 className="card-header-title">运行风险提示</h2><p className="card-header-subtitle">按预测负荷、净负荷爬坡与新能源贡献生成的规则型提示</p></div></div>
          {situation.risks.length ? <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{situation.risks.map((risk, index) => <div key={`${risk.time}-${index}`} className={`rounded border p-3 flex gap-3 ${risk.level === 'warning' ? 'border-warning-500/30 bg-warning-500/5' : 'border-primary-500/30 bg-primary-500/5'}`}><AlertTriangle className={`w-5 h-5 shrink-0 ${risk.level === 'warning' ? 'text-warning-700' : 'text-primary-700'}`}/><div><span className="text-ink text-sm font-medium">{risk.time}</span><p className="text-ink text-sm mt-1">{risk.message}</p></div></div>)}</div> : <EmptyState icon={<Activity className="w-10 h-10"/>} title="当前未发现显著运行风险" />}
        </div>
        <p className="text-xs text-ink-muted px-3">数据范围：{situation.data_scope.region}，预测窗口 {situation.data_scope.horizon_hours} 小时。{situation.data_scope.renewable_note}</p>
        </> : !loading && <EmptyState icon={<Activity className="w-10 h-10"/>} title="正在更新预测区间" description="已结束的区间已隐藏，等待新的有效预测；可点击刷新重试。"/>}

      {/* 核心快照首次完成后再启动诊断；此后独立轮询，不随预测准备重查历史。 */}
      {(cachedSituation || error) && <HourlyDiagnosticsPanel scope={scope} />}

      <div className="card min-w-0 relative z-10"><div className="card-header flex-wrap"><div className="card-header-icon bg-surface-muted"><BrainCircuit className="w-5 h-5 text-primary-600"/></div><div className="min-w-0 flex-1"><h2 className="card-header-title">负荷预测特征敏感度</h2><p className="card-header-subtitle">比较输入特征变化对预测结果的影响，点击后计算</p></div><div className="data-toolbar-group sm:ml-auto">{sensitivityRequested ? <RefreshButton onClick={loadSensitivity} isLoading={sensitivityLoading}/> : <button type="button" onClick={loadSensitivity} className="btn btn-primary !py-1.5 !text-sm"><Play className="w-4 h-4"/>开始分析</button>}</div></div>
        {sensitivityError ? <ErrorBanner message={sensitivityError} onRetry={loadSensitivity}/> : sensitivityLoading && !sensitivity ? <Spinner size="lg"/> : sensitivity ? <><ResponsiveContainer width="100%" height={280}><BarChart data={sensitivity.ranking} layout="vertical" margin={{ left: 40, right: 24 }}><CartesianGrid {...CHART_GRID} horizontal={false} vertical/><XAxis type="number" stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><YAxis type="category" dataKey="feature_group" width={105} stroke={CHART_COLORS.axis} fontSize={12} tickLine={false} axisLine={false}/><Tooltip contentStyle={tooltipStyle} itemStyle={tooltipItemStyle} labelStyle={tooltipLabelStyle} formatter={(value: number, _name, item) => [`${Number(value).toFixed(2)} MW`, `特征数 ${item.payload.feature_count}`]}/><Bar dataKey="mean_absolute_impact_mw" name="平均绝对影响" fill={CHART_COLORS.forecast} radius={[0,4,4,0]} isAnimationActive={false}/></BarChart></ResponsiveContainer><div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm"><div className="rounded bg-surface-muted border border-edge p-4 text-ink"><span className="text-primary-700 font-medium">方法：</span>{sensitivity.method_note}</div><div className="rounded bg-surface-muted border border-edge p-4 text-ink"><span className="text-ink font-medium">边界：</span>{sensitivity.data_note}</div></div></> : <EmptyState icon={<BrainCircuit className="w-10 h-10"/>} title="特征敏感度尚未计算" description="点击“开始分析”后执行 5 次模型推理；不会训练或修改模型。"/>}
      </div>
    </div>
  )
}

export default OperationSituationPage
