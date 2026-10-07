import React from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { LoadOverviewData } from '../types'
import { ChartSkeleton, EmptyState } from './Skeleton'
import PredictionQualityNotice from './PredictionQualityNotice'
import { useForecastClock } from '../hooks/useForecastClock'
import { TrendingUp, Clock, Gauge, RefreshCw } from 'lucide-react'
import { formatEastern, formatEasternISO, easternHourOffset, parseEasternISO, ET_DATE_TIME } from '../utils/time'
import { CHART_COLORS, CHART_AXIS, CHART_GRID } from '../utils/chartTheme'
import { ChartSeriesLegend } from './ChartLegend'

interface LoadForecastChartProps {
  /** 24h 负荷预测总览（历史回测验证 + 未来预测 + 当前实际） */
  data: LoadOverviewData | null
  /** 仅在首次加载（无数据）时为 true，触发骨架屏 */
  isLoading?: boolean
  /** 刷新中保留曲线，在图例栏显示同步提示 */
  isRefreshing?: boolean
  height?: number
  /** 历史回看小时数（24/12/6），前端切片真实生效 */
  historyHours?: number
  /** 是否显示光伏曲线；负荷独立预测页关闭，总览页可继续显示 */
  showSolar?: boolean
}

// 时间 → 相对当前的小时偏移（负=过去，0=现在，正=未来）
const hourOffset = (iso: string, nowMs: number): number =>
  easternHourOffset(iso, nowMs)

const ChartTooltip: React.FC<any> = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null

  const p = payload[0]?.payload
  const timeStr = p?.timeLabel ?? `${label}h`

  return (
    <div className="chart-tooltip min-w-[200px]">
      <div className="flex items-center gap-2 mb-2.5 pb-2 border-b border-dark-700">
        <Clock className="w-3.5 h-3.5 text-primary-600" aria-hidden="true" />
        <p className="text-dark-200 text-xs font-bold tracking-wide font-mono">{timeStr}</p>
      </div>
      {p?.isCurrentTime && (
        <div className="mb-2.5 rounded-md border border-rose-400/30 bg-rose-500/10 px-2 py-1 text-[10px] font-medium text-danger-600">
          当前时刻 · 相邻整点预测线性插值
        </div>
      )}
      <div className="space-y-2">
        {payload.map((entry: any, index: number) => (
          <div key={index} className="flex items-center justify-between gap-5 text-xs">
            <span className="flex items-center gap-2 font-medium" style={{ color: entry.color }}>
              <span className="w-2 h-2 rounded-full shadow-sm" style={{ background: entry.color }} />
              {entry.name}
            </span>
            <span className="font-mono font-bold text-dark-200 tabular-nums">
              {entry.value != null ? `${Number(entry.value).toFixed(1)} MW` : '--'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

interface ChartPoint {
  x: number
  hour: number
  timeLabel: string
  实际负荷: number | null
  历史预测: number | null
  未来预测: number | null
  光伏预测: number | null
  isCurrentTime?: boolean
}

const interpolate = (start: number, end: number, ratio: number): number =>
  start + (end - start) * ratio

const interpolateOptional = (
  start: number | null | undefined,
  end: number | null | undefined,
  ratio: number,
): number | null => {
  if (start == null || end == null) return null
  return interpolate(start, end, ratio)
}

const ForecastPointDot: React.FC<any> = ({ cx, cy, payload, stroke }) => {
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return null
  const isCurrentTime = Boolean(payload?.isCurrentTime)
  return (
    <circle
      cx={cx}
      cy={cy}
      r={isCurrentTime ? 6 : 3}
      fill={stroke}
      stroke={isCurrentTime ? CHART_COLORS.error : 'none'}
      strokeWidth={isCurrentTime ? 3 : 0}
    />
  )
}

const SolarPointDot: React.FC<any> = ({ cx, cy, payload, stroke }) => {
  if (!payload?.isCurrentTime || !Number.isFinite(cx) || !Number.isFinite(cy)) return null
  return <circle cx={cx} cy={cy} r={6} fill={stroke} stroke={CHART_COLORS.error} strokeWidth={3} />
}

interface ForecastBoundaryLabelProps {
  viewBox?: { x?: number; y?: number }
}

const ForecastBoundaryLabel: React.FC<ForecastBoundaryLabelProps> = ({ viewBox }) => {
  const x = Number(viewBox?.x ?? 0)
  const y = Number(viewBox?.y ?? 0) + 14
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect
        x={-76}
        y={-13}
        width={152}
        height={26}
        rx={3}
        fill="var(--surface-raised)"
        stroke={CHART_COLORS.reference}
        strokeWidth={1}
        opacity={0.98}
      />
      <text
        x={0}
        y={4}
        textAnchor="middle"
        fill={CHART_COLORS.actual}
        fontSize={12}
        fontWeight={700}
      >
        历史回测 ｜ 未来预测
      </text>
    </g>
  )
}

const LoadForecastChart: React.FC<LoadForecastChartProps> = ({
  data,
  isLoading = false,
  isRefreshing = false,
  height = 460,
  historyHours = 24,
  showSolar = true,
}) => {
  const clockMs = useForecastClock()

  // ── 骨架屏/空态 ──
  if (isLoading && !data) {
    return <ChartSkeleton />
  }
  if (!data) {
    return (
      <div className="flex items-center justify-center py-16">
        <EmptyState icon={<TrendingUp className="w-12 h-12 text-ink-muted" />} title="暂无预测数据" />
      </div>
    )
  }

  const hist = data.historical?.pairs ?? []
  const future = (data.future?.predictions ?? []).filter(row => data.input_quality?.time_basis !== 'hour_end' || parseEasternISO(row.target_time).getTime() > clockMs)
  if (!hist.length && !future.length) {
    const preparing = data.input_quality?.refresh_in_progress
    return <div className="w-full">
      <PredictionQualityNotice quality={data.input_quality} task={showSolar ? undefined : 'load'} />
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-dark-300" role="status">
        {preparing && <TrendingUp className="h-6 w-6 animate-pulse text-primary-600" aria-hidden="true" />}
        <p>{preparing ? '正在准备首次预测数据，完成后自动显示' : '负荷预测暂不可用，系统会自动重试'}</p>
        <p className="text-xs text-dark-400">无需反复刷新；{showSolar ? '负荷、电价和光伏' : '负荷'}的状态及原因见上方。</p>
      </div>
    </div>
  }
  const metrics = data.historical?.metrics
  const referenceMs = parseEasternISO(data.current?.time ?? data.generated_at).getTime()

  // ── 合并数据 ──
  const histFiltered = hist.filter((p) => hourOffset(p.target_time, referenceMs) >= -(historyHours - 1))
  const histCount = Math.max(histFiltered.length, 1)
  const futureCount = Math.max(future.length, 1)
  const FUT_SPACING = 1
  const HIST_SPACING = (2 / 3) * (futureCount / histCount)
  const futureX0 = histFiltered.length * HIST_SPACING

  const baseChartData: ChartPoint[] = [
    ...histFiltered.map((p, i) => ({
      x: i * HIST_SPACING,
      hour: hourOffset(p.target_time, referenceMs),
      timeLabel: formatEasternISO(p.target_time, ET_DATE_TIME),
      实际负荷: p.historical_actual,
      历史预测: p.historical_forecast,
      未来预测: null,
      光伏预测: null,
    })),
    ...future.map((f, j) => ({
      x: futureX0 + j * FUT_SPACING,
      hour: hourOffset(f.target_time, referenceMs),
      timeLabel: formatEasternISO(f.target_time, ET_DATE_TIME),
      实际负荷: null,
      历史预测: null,
      未来预测: f.future_forecast,
      光伏预测: f.pv_forecast_mw ?? null,
    })),
  ].sort((a, b) => a.x - b.x)

  // 依据预测时间戳，把当前真实 ET 时刻投影到未来预测区域。
  // 使用连续位置而非最近整点，因此 10:30 会落在 10:00 与 11:00 两点之间。
  const realNowMs = clockMs
  const firstFutureMs = future[0]?.target_time
    ? parseEasternISO(future[0].target_time).getTime()
    : Number.NaN
  const lastFutureMs = future[future.length - 1]?.target_time
    ? parseEasternISO(future[future.length - 1].target_time).getTime()
    : Number.NaN
  const currentTimeX = Number.isFinite(firstFutureMs)
    && Number.isFinite(lastFutureMs)
    && realNowMs >= firstFutureMs
    && realNowMs <= lastFutureMs
      ? futureX0 + (realNowMs - firstFutureMs) / 3_600_000
      : null

  // 预测模型按整点输出。当前时刻位于两个整点之间时，在前后预测之间做线性插值，
  // 仅用于图表即时查看，不修改后端模型输出、数据库记录或回测指标。
  let currentPoint: ChartPoint | null = null
  if (currentTimeX != null && data.input_quality?.time_basis !== 'hour_end') {
    const timedFuture = future.map((item) => ({
      item,
      timestampMs: parseEasternISO(item.target_time).getTime(),
    }))
    const upperIndex = timedFuture.findIndex((row) => row.timestampMs >= realNowMs)
    if (upperIndex >= 0) {
      const upper = timedFuture[upperIndex]
      const lower = timedFuture[Math.max(0, upperIndex - 1)]
      const spanMs = upper.timestampMs - lower.timestampMs
      const ratio = spanMs > 0
        ? Math.min(1, Math.max(0, (realNowMs - lower.timestampMs) / spanMs))
        : 0
      currentPoint = {
        x: currentTimeX,
        hour: (realNowMs - referenceMs) / 3_600_000,
        timeLabel: formatEastern(new Date(realNowMs), ET_DATE_TIME),
        实际负荷: null,
        历史预测: null,
        未来预测: interpolate(
          lower.item.future_forecast,
          upper.item.future_forecast,
          ratio,
        ),
        光伏预测: interpolateOptional(
          lower.item.pv_forecast_mw,
          upper.item.pv_forecast_mw,
          ratio,
        ),
        isCurrentTime: true,
      }
    }
  }

  const chartData = currentPoint
    ? [...baseChartData, currentPoint].sort((a, b) => a.x - b.x)
    : baseChartData
  const xToTime = new Map<number, string>(baseChartData.map((d) => [d.x, d.timeLabel]))
  const timeTickLabel = (x: number): string => xToTime.get(Number(x)) ?? ''
  const xTicks = [-24, -18, -12, -6, 6, 12, 18, 24]
    .map((h) => baseChartData.find((d) => d.hour === h)?.x)
    .filter((x): x is number => x !== undefined)
    .concat(futureX0 > 0 ? [futureX0] : [])
    // 保持刻度从左到右排列，否则 preserveStartEnd 会把分界点当作末端，裁掉未来刻度。
    .sort((a, b) => a - b)

  const currentActual = data.current?.actual_load_mw
  const futureValues = future.map((f) => f.future_forecast)
  const futurePeak = futureValues.length ? Math.max(...futureValues) : null
  const futureTrough = futureValues.length ? Math.min(...futureValues) : null
  const originLabel = data.current?.time
    ? formatEasternISO(data.current.time, ET_DATE_TIME)
    : '--'
  const generatedLabel = formatEasternISO(data.generated_at, ET_DATE_TIME)

  return (
    <div className="relative w-full animate-fade-in" style={{ minHeight: height }} role="region"
      aria-label="24小时负荷预测与历史验证：过去24h实际负荷与历史回测预测对比，未来24h预测">
      {/* ── 折线图区域 ── */}
      <div className="flex flex-wrap justify-between items-center gap-2 mb-3">
        <ChartSeriesLegend items={[
          { label: '实测负荷（ISO-NE）', color: CHART_COLORS.actual },
          { label: '历史回测', color: CHART_COLORS.replay, dashed: true },
          { label: '未来负荷预测', color: CHART_COLORS.forecast },
          ...(showSolar ? [{ label: '光伏预测', color: CHART_COLORS.solar }] : []),
        ]} />
        <div className="flex max-w-full flex-wrap items-center gap-x-3 gap-y-2">
          <span className="chart-axis-caption">负荷：左轴（MW）{showSolar ? ' · 光伏：右轴（MW）' : ''}</span>
          {isRefreshing && (
            <span className="inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded border border-edge bg-surface-muted px-3 py-1.5 text-xs font-medium text-primary-600"
              role="status" aria-live="polite">
              <RefreshCw className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
              数据同步刷新中...
            </span>
          )}
        </div>
      </div>
      <div className="load-chart-plot" style={{ height: Math.max(380, height - 60) }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 30, right: 28, left: 5, bottom: 5 }}>
          <CartesianGrid {...CHART_GRID} />

          <XAxis
            dataKey="x"
            type="number"
            domain={[0, chartData.length ? chartData[chartData.length - 1].x : 40]}
            ticks={xTicks}
            stroke={CHART_COLORS.grid}
            tick={CHART_AXIS}
            tickLine={false}
            tickFormatter={(value: number | string) => {
              const label = timeTickLabel(Number(value))
              return label || ''
            }}
            angle={-30}
            textAnchor="end"
            height={52}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          {/* 左轴：负荷 (k MW) */}
          <YAxis
            yAxisId="load"
            stroke={CHART_COLORS.grid}
            tick={CHART_AXIS}
            tickLine={false}
            tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`}
            domain={['auto', 'auto']}
          />
          {/* 右轴：光伏发电 (MW) */}
          {showSolar && (
            <YAxis
              yAxisId="gen"
              orientation="right"
              stroke={CHART_COLORS.grid}
              tick={CHART_AXIS}
              tickLine={false}
              tickFormatter={(v: number) => `${Math.round(v)}`}
              domain={[0, 'auto']}
              width={50}
            />
          )}
          <Tooltip content={<ChartTooltip />} />
          {/* 历史回测与未来预测的窗口分界线 */}
          <ReferenceLine
            yAxisId="load"
            x={futureX0}
            stroke={CHART_COLORS.reference}
            strokeWidth={1.5}
            strokeDasharray="4 4"
            label={<ForecastBoundaryLabel />}
          />

          {currentTimeX != null && (
            <ReferenceLine
              yAxisId="load"
              x={currentTimeX}
              stroke={CHART_COLORS.reference}
              strokeWidth={2}
              strokeDasharray="7 4"
              ifOverflow="extendDomain"
            />
          )}

          {/* 实际负荷（ISO-NE 真实）- 深灰实线 */}
          <Line
            yAxisId="load"
            type="monotone"
            dataKey="实际负荷"
            stroke={CHART_COLORS.actual}
            strokeWidth={3}
            connectNulls={false}
            dot={{ r: 3, fill: CHART_COLORS.actual, strokeWidth: 0 }}
            activeDot={{ r: 6, fill: CHART_COLORS.actual, stroke: 'var(--surface-raised)', strokeWidth: 2 }}
            isAnimationActive={false}
            animationDuration={600}
          />

          {/* 历史回测预测 - 青绿色虚线 */}
          <Line
            yAxisId="load"
            type="monotone"
            dataKey="历史预测"
            stroke={CHART_COLORS.replay}
            strokeWidth={3}
            strokeDasharray="6 4"
            connectNulls={false}
            dot={{ r: 3, fill: CHART_COLORS.replay, strokeWidth: 0 }}
            activeDot={{ r: 6, fill: CHART_COLORS.replay, stroke: 'var(--surface-raised)', strokeWidth: 2 }}
            isAnimationActive={false}
            animationDuration={600}
          />

          {/* 未来预测 - 蓝色实线 */}
          <Line
            yAxisId="load"
            type="monotone"
            dataKey="未来预测"
            stroke={CHART_COLORS.forecast}
            strokeWidth={3.5}
            connectNulls={false}
            dot={<ForecastPointDot />}
            activeDot={{ r: 6, fill: CHART_COLORS.forecast, stroke: 'var(--surface-raised)', strokeWidth: 2 }}
            isAnimationActive={false}
            animationDuration={600}
          />

          {/* 未来光伏预测 - 深橙色实线 */}
          {showSolar && (
            <Line
              yAxisId="gen"
              type="monotone"
              dataKey="光伏预测"
              stroke={CHART_COLORS.solar}
              strokeWidth={3.2}
              connectNulls={false}
              dot={<SolarPointDot />}
              activeDot={{ r: 6, fill: CHART_COLORS.solar, stroke: 'var(--surface-raised)', strokeWidth: 2 }}
              isAnimationActive={false}
              animationDuration={600}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
      </div>

      {/* 独立负荷页上方已有峰谷指标，这里只补充回测误差。 */}
      <div className={`chart-summary-strip grid grid-cols-2 sm:grid-cols-3 ${showSolar ? 'xl:grid-cols-6' : ''} gap-2.5 mt-4 mb-4`}>
        {showSolar && <>
        {/* 当前实际负荷 */}
        <div className="chart-summary">
          <div className="flex items-center justify-between gap-1 mb-1">
            <span className="text-[11px] font-semibold text-dark-200">最近实测负荷</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-lg font-bold text-dark-200 font-mono tabular-nums">
              {currentActual != null ? currentActual.toFixed(0) : '--'}
            </span>
            <span className="text-xs text-dark-400 font-mono">MW</span>
          </div>
        </div>

        {/* 未来峰值 */}
        <div className="chart-summary">
          <div className="flex items-center justify-between gap-1 mb-1">
            <span className="text-[11px] font-semibold text-dark-200">未来峰值负荷</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-lg font-bold text-dark-200 font-mono tabular-nums">
              {futurePeak != null ? futurePeak.toFixed(0) : '--'}
            </span>
            <span className="text-xs text-dark-400 font-mono">MW</span>
          </div>
        </div>

        {/* 未来最低 */}
        <div className="chart-summary">
          <div className="flex items-center justify-between gap-1 mb-1">
            <span className="text-[11px] font-semibold text-dark-200">未来低谷负荷</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-lg font-bold text-dark-200 font-mono tabular-nums">
              {futureTrough != null ? futureTrough.toFixed(0) : '--'}
            </span>
            <span className="text-xs text-dark-400 font-mono">MW</span>
          </div>
        </div>

        </>}

        {/* 历史 MAE */}
        <div className="chart-summary" title="回测验证口径：使用事后历史气象回放与真实负荷重新调用模型得到的验证值；不等同于当时可获得的日前气象预报">
          <div className="text-[11px] font-medium text-dark-400 mb-1 truncate">
            历史 24h MAE
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-lg font-bold text-dark-200 font-mono tabular-nums">
              {metrics?.mae_mw != null ? metrics.mae_mw.toFixed(0) : '--'}
            </span>
            <span className="text-xs text-dark-400 font-mono">MW</span>
          </div>
        </div>

        {/* 历史 RMSE */}
        <div className="chart-summary" title="回测验证口径：使用事后历史气象回放与真实负荷重新调用模型得到的验证值；不等同于当时可获得的日前气象预报">
          <div className="text-[11px] font-medium text-dark-400 mb-1 truncate">
            历史 24h RMSE
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-lg font-bold text-dark-200 font-mono tabular-nums">
              {metrics?.rmse_mw != null ? metrics.rmse_mw.toFixed(0) : '--'}
            </span>
            <span className="text-xs text-dark-400 font-mono">MW</span>
          </div>
        </div>

        {/* 历史 MAPE */}
        <div className="chart-summary" title="回测验证口径：使用事后历史气象回放与真实负荷重新调用模型得到的验证值；不等同于当时可获得的日前气象预报">
          <div className="text-[11px] font-semibold text-dark-200 mb-1 truncate">
            历史 24h MAPE
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-lg font-bold text-dark-200 font-mono tabular-nums">
              {metrics?.mape != null ? `${metrics.mape}%` : '--'}
            </span>
          </div>
        </div>
      </div>

      <PredictionQualityNotice quality={data.input_quality} task={showSolar ? undefined : 'load'} />

      {/* 数据来源与原始生成时间 */}
      <div className="mt-2 flex flex-wrap gap-3 items-center justify-end text-xs text-dark-400 px-1">
        <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 font-mono text-[11px]">
          <span className="flex items-center gap-1.5">
            <Gauge className="w-3.5 h-3.5 text-primary-600" /> 实测截至 {originLabel}
          </span>
          <span className="text-ink-muted">生成于 {generatedLabel}</span>
        </span>
      </div>
    </div>
  )
}

export default React.memo(LoadForecastChart)
