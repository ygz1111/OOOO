import type { LoadPredictionResponse, SystemStatus } from '../types'
import { forecastIntervalOpen } from './time'

export function predictionHealth(system: SystemStatus | null, prediction: LoadPredictionResponse | null, error: string | null, now: number) {
  if (!system) return { text: '连接服务中', color: 'text-dark-400', indicator: 'status-offline' }
  if (system.status === 'error') return { text: '系统错误', color: 'text-danger-600', indicator: 'status-offline' }
  const warning = (text: string) => ({ text, color: 'text-warning-600', indicator: 'status-warning' })
  if (error) return warning('预测请求失败')
  if (!prediction) return warning('服务在线 · 预测准备中')
  const states = Object.values(prediction.input_quality?.components ?? {})
  const updating = !!prediction.input_quality?.refresh_in_progress
  const updateNotice = updating ? ' · 后台更新中' : ''
  const covered = prediction.predictions?.some(row => forecastIntervalOpen(row.timestamp, now)
    && [row.load_forecast_mw, row.price_p50, row.pv_estimation_mw].some(value => Number.isFinite(value)))
  if (!covered) return warning(updating ? '服务在线 · 预测准备中' : '预测部分或全部不可用')
  if (states.some(state => state.status === 'unavailable')) return warning('预测部分或全部不可用' + updateNotice)
  if (states.some(state => state.status === 'cached')) return warning('沿用此前预测' + updateNotice)
  if (states.some(state => state.status === 'estimated_inputs' || state.input_status === 'estimated_inputs')) return warning('预测含估计输入' + updateNotice)
  if (system.status !== 'healthy' || states.length !== 3 || states.some(state => state.status !== 'fresh')) return warning('系统降级' + updateNotice)
  return { text: updating ? '预测可用 · 后台更新中' : '系统正常', color: 'text-success-600', indicator: 'status-online' }
}
