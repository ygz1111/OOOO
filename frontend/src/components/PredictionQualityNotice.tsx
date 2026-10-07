import type { LoadInputQuality } from '../types'
import { formatEasternISO, ET_DATE_TIME } from '../utils/time'

const labels: Record<string, string> = { load: '负荷', price: '电价', pv: '光伏' }
const states = { fresh: '本次预测', estimated_inputs: '含估计输入', cached: '沿用此前预测', unavailable: '暂不可用' }
type QualityTone = 'ready' | 'preparing' | 'caution' | 'unavailable'
type ComponentQuality = NonNullable<LoadInputQuality['components']>[string]

export default function PredictionQualityNotice({ quality, task }: { quality?: LoadInputQuality | null; task?: string }) {
  if (!quality) return null
  const components = Object.entries(quality.components ?? {}).filter(([name]) => !task || task === name)
  // Keep the same feature scope as the existing prediction services: load and
  // price share market inputs; PV uses its own observation and estimate records.
  const estimates = (quality.estimated_inputs ?? []).filter(value => !task || (value.field === 'pv_mw') === (task === 'pv'))
  const dayAhead = task === 'pv' ? [] : quality.day_ahead_imputed ?? []
  const derivedPrices = task === 'pv' ? [] : quality.rt_lmp_derived_hours ?? []
  const partialPV = !task || task === 'pv' ? quality.partial_pv_hours ?? [] : []
  const partialLoad = task === 'pv' ? [] : quality.partial_load_hours ?? []
  const hasEstimatedInputs = !!(estimates.length || dayAhead.length || derivedPrices.length || partialPV.length || partialLoad.length)
  const toneFor = (value: ComponentQuality): QualityTone => {
    if (value.status === 'cached' || value.status === 'estimated_inputs') return 'caution'
    if (value.status === 'unavailable') return quality.refresh_in_progress && !value.reason ? 'preparing' : 'unavailable'
    return 'ready'
  }
  const tones = components.map(([, value]) => toneFor(value))
  const tone: QualityTone = tones.includes('unavailable') ? 'unavailable'
    : hasEstimatedInputs || tones.includes('caution') ? 'caution'
      : quality.refresh_in_progress ? 'preparing' : 'ready'

  return <div className="quality-status-panel mb-3" data-tone={tone} role="status">
    <div className="quality-status-header">
      <span>{quality.refresh_in_progress ? '数据更新中' : '数据状态'}</span>
      {quality.notice && <p>{quality.notice}</p>}
    </div>
    {!!components.length && <div className="quality-component-list">
      {components.map(([name, value]) => <div key={name} className="quality-component-row" data-tone={toneFor(value)}>
        <div className="quality-component-title">
          <span>{labels[name] ?? name}</span>
          <span>{states[value.status]}</span>
          {value.status === 'cached' && value.input_status === 'estimated_inputs' && <span>原预测含估计输入</span>}
        </div>
        {value.generated_at && <p className="quality-component-meta">
          {value.status === 'cached' ? '原预测生成于' : '生成于'} <time dateTime={value.generated_at}>{formatEasternISO(value.generated_at, ET_DATE_TIME)}（ET）</time>
        </p>}
        {value.notice && <p className="quality-component-meta">{value.notice}</p>}
        {value.reason && <p className="quality-component-meta">原因：{value.reason}</p>}
      </div>)}
    </div>}
    {hasEstimatedInputs && <div className="quality-summary" data-tone="caution">
      {!!estimates.length && <p>{estimates.length} 项缺失输入采用昨日同小时观测补齐；估计值不计作实测。</p>}
      {!!dayAhead.length && <p>{dayAhead.length} 项未发布的日前输入采用同小时历史值补齐。</p>}
      {!!derivedPrices.length && <p>{derivedPrices.length} 个小时电价输入来自五分钟聚合，不作为官方小时实测计算误差。</p>}
      {!!(partialPV.length || partialLoad.length) && <p>
        {partialLoad.length ? `负荷 ${partialLoad.length} 个小时` : ''}
        {partialLoad.length && partialPV.length ? '、' : ''}
        {partialPV.length ? `光伏 ${partialPV.length} 个小时` : ''}
        采样不足12次；不作为完整实测计算误差。
      </p>}
    </div>}
    <details className="quality-details">
      <summary>数据来源与时间说明</summary>
      <div>
        {components.map(([name, value]) => value.observed_through && <p key={name}>
          {labels[name] ?? name}观测截至 {formatEasternISO(value.observed_through, ET_DATE_TIME)}（ET）。
        </p>)}
        {quality.coverage_hours != null && <p>本次返回 {quality.coverage_hours} 个小时区间，按整点对齐；过期区间不再显示。</p>}
        {quality.forecast_start && quality.forecast_end && <p>区间结束时间：{formatEasternISO(quality.forecast_start, ET_DATE_TIME)} 至 {formatEasternISO(quality.forecast_end, ET_DATE_TIME)}（ET）。</p>}
        <p>时间统一使用美国东部时区（America/New_York）；预测与实测按对应小时区间比较。</p>
        {!!estimates.length && <p>昨日同小时补值属于降级输入，尚未验证该方式的预测精度。</p>}
        {estimates.map((value, index) => <p key={`${value.field}-${value.target_time}-${index}`}>
          {value.field}：目标 {formatEasternISO(value.target_time, ET_DATE_TIME)}，来源 {formatEasternISO(value.source_time, ET_DATE_TIME)}（ET）。
        </p>)}
        {!!derivedPrices.length && <p>五分钟聚合保留采样数与来源，仅用于预测输入；真实误差统计使用官方小时实测。</p>}
      </div>
    </details>
  </div>
}
