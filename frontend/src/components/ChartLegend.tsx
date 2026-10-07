import type { CSSProperties } from 'react'

interface SeriesItem {
  label: string
  color: string
  dashed?: boolean
  strokeDasharray?: CSSProperties['strokeDasharray']
}

export function ChartSeriesLegend({ items }: { items: SeriesItem[] }) {
  return <div className="chart-series-legend" aria-label="图例">
    {items.map(({ label, color, dashed, strokeDasharray }) => <span key={label} className="chart-series-key">
      <svg width="28" height="12" viewBox="0 0 28 12" aria-hidden="true">
        <line x1="1" y1="6" x2="27" y2="6" stroke={color} strokeWidth="3" strokeDasharray={strokeDasharray ?? (dashed ? '6 4' : undefined)} />
      </svg>
      <span>{label}</span>
    </span>)}
  </div>
}

/** Recharts 图例适配：沿用每条曲线自身的颜色和线型。 */
export default function ChartLegend({ payload }: {
  payload?: Array<{ value?: string; color?: string; payload?: { strokeDasharray?: CSSProperties['strokeDasharray'] } }>
}) {
  return <ChartSeriesLegend items={(payload ?? []).map(item => ({
    label: item.value ?? '', color: item.color ?? 'var(--chart-actual)', strokeDasharray: item.payload?.strokeDasharray,
  }))} />
}
