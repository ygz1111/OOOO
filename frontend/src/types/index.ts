export interface WeatherData {
  timestamp: string
  temperature_2m: number
  dew_point_2m: number
  relative_humidity_2m?: number
  wind_speed_10m?: number
  cloud_cover?: number
  shortwave_radiation?: number
}

export interface HourlyPrediction {
  hour: number
  timestamp: string
  load_forecast_mw: number
  pv_estimation_mw: number | null
  net_load_mw: number | null
  /** 电价预测 (USD/MWh)，仅 TensorFlow 引擎输出时有值 */
  price_p10?: number | null
  price_p50?: number | null
  price_p90?: number | null
}

export interface ModelInfo {
  name: string
  weight: number
  num_params: number
  loaded: boolean
}

export interface LoadPredictionResponse {
  status: string
  predictions: HourlyPrediction[]
  model_info: ModelInfo[]
  ensemble_weights: Record<string, number>
  inference_time_ms: number
  data_source: string
  timestamp: string
  /** 当前生产负荷模型引擎：TensorFlow tf_split_v1 */
  engine?: string
  /** TensorFlow 光伏引擎 */
  pv_engine?: string
  /** 预测锚点（America/New_York 整点） */
  origin?: string | null
  /** 在线输入质量以及日前特征补值记录 */
  input_quality?: LoadInputQuality | null
}

export interface LoadInputQuality {
  refresh_in_progress?: boolean
  time_basis?: 'hour_end'
  notice?: string
  coverage_hours?: number
  forecast_start?: string | null
  forecast_end?: string | null
  estimated_inputs?: Array<{ field: string; target_time: string; source_time: string; method: string }>
  components?: Record<string, { status: 'fresh' | 'estimated_inputs' | 'cached' | 'unavailable'; observed_through?: string | null; generated_at?: string; notice?: string; reason?: string; input_status?: 'fresh' | 'estimated_inputs' }>
  origin_lag_hours: number
  day_ahead_imputed: Array<{
    field: string
    target_time: string
    source_time: string
    method: 'same_hour_persistence'
  }>
  partial_pv_hours: Array<{ time: string; samples_per_zone: number }>
  partial_load_hours?: Array<{ time: string; samples_per_zone: number }>
  rt_lmp_derived_hours?: Array<{ time: string; samples_per_hour: number }>
  pv_minimum_samples_per_zone: number
}

// ========================================
// 电价预测 (TensorFlow)
// ========================================

export interface HourlyPricePoint {
  hour: number
  timestamp: string
  price_p10: number
  price_p50: number
  price_p90: number
  load_forecast_mw?: number | null
}

export interface PriceForecastResponse {
  input_quality?: LoadInputQuality | null
  status: string
  model?: string
  model_name?: string
  predictions: HourlyPricePoint[]
  origin?: string | null
  inference_time_ms: number
  data_source?: string
  timestamp: string
}

/** TensorFlow 电价历史回测：预测分位数与真实 ISO-NE RT-LMP 的逐小时配对。 */
export interface PriceBacktestPoint extends HourlyPricePoint {
  price_actual: number | null
  /** P50 预测 − 真实 RT-LMP；正值表示预测偏高。 */
  error_p50: number | null
  actual_source?: string
  actual_status?: 'observed' | 'input_only' | 'missing'
  samples_per_hour?: number | null
  label_notice?: string
}

export interface PriceBacktestMetrics {
  count: number
  mae_usd: number
  rmse_usd: number
  mape_pct: number | null
  median_ae_usd: number
  bias_usd: number
  p10_p90_coverage: number
}

export interface PriceBacktestData {
  available_date_range: { earliest: string; latest: string }
  date: string | null
  origin?: string | null
  model?: string
  data_source?: string
  inference_time_ms?: number
  points: PriceBacktestPoint[]
  metrics: PriceBacktestMetrics | null
  metric_note?: string
  label_quality?: {
    evaluated_hours: number
    excluded_hours: number
    official_hourly_hours: number
    input_only_hours: number
    missing_hours: number
    notice: string
  }
}

export interface WeatherStationData {
  name: string
  latitude: number
  longitude: number
  temperature_2m: number
  dew_point_2m: number
  relative_humidity_2m?: number
  wind_speed_10m?: number
  cloud_cover?: number
  shortwave_radiation?: number
}

export interface WeatherResponse {
  status: string
  timestamp: string
  stations: WeatherStationData[]
  regional_average: Partial<WeatherData>
}

export interface SystemStatus {
  status: 'healthy' | 'degraded' | 'error'
  models_loaded: number
  models_total?: number
  device: string
  total_inferences: number
  average_inference_time_ms: number
  ensemble_weights: Record<string, number>
  model_details?: Array<{
    id: string
    name: string
    task: string
    architecture: string
    framework: string
    loaded: boolean
  }>
  uptime_seconds: number
  memory_usage_mb?: number
  timestamp: string
}

export interface MetricCardProps {
  title: string
  value: string | number | React.ReactNode
  unit?: string
  trend?: 'up' | 'down' | 'stable'
  trendValue?: string
  icon?: React.ReactNode
  className?: string
}

// ========================================
// 历史分析相关类型
// ========================================

/** 后端通用响应包装 */
export interface ApiResponse<T = any> {
  status: string
  message: string
  data: T
  timestamp: string
}

/** 历史预测记录 (数据库行) */
export interface PredictionRecord {
  id: number
  prediction_id: string
  prediction_timestamp: string
  target_timestamp: string
  load_forecast_mw: number
  pv_estimation_mw: number | null
  net_load_mw: number | null
  confidence_lower_mw: number | null
  confidence_upper_mw: number | null
  model_type: string
  model_weights: Record<string, number> | null
  inference_time_ms: number | null
  cache_hit: boolean
  data_source: string | null
  created_at: string
  actual_load_mw?: number | null
}

export interface OnlineErrorMetrics {
  count: number
  mae: number | null
  rmse: number | null
  mape: number | null
  bias: number | null
  r2: number | null
}

export interface LeadTimeInputQualityMetrics extends OnlineErrorMetrics {
  quality: 'complete' | 'estimated' | 'unknown'
  label: string
}

export interface LeadTimeAccuracyGroup extends OnlineErrorMetrics {
  key: '1_6' | '7_12' | '13_24'
  label: string
  min_hour: number
  max_hour: number
  input_quality: LeadTimeInputQualityMetrics[]
}

/** 准确性统计 */
export interface AccuracyStats {
  count: number
  mape: number | null
  rmse: number | null
  mae: number | null
  r2: number | null
  best_model?: string
  worst_model?: string
  /** 当前统计实际使用的 TensorFlow 生产模型。 */
  model_type?: string
  /** 在线误差统计窗口（小时）。 */
  window_hours?: number
  metric_scope?: 'latest_snapshot_per_target'
  metric_note?: string
  /** 按原始生成时间计算；每组内同一目标小时仅保留最早的在线预测。 */
  lead_time_groups?: LeadTimeAccuracyGroup[]
  lead_time_scope?: 'earliest_snapshot_per_target_within_lead_group'
  lead_time_note?: string
  lead_time_excluded?: {
    invalid_timestamp: number
    ambiguous_timestamp: number
    noncausal: number
    outside_24_hours: number
    invalid_values: number
  }
}

/** 模型对比项 */
export interface ModelComparisonItem {
  model_name: string
  count: number
  mape: number | null
  rmse: number | null
  mae: number | null
  avg_inference_time_ms: number | null
  metric_count?: number
  comparison_scope?: 'common_targets' | 'single_model_window'
  comparison_note?: string
  lifecycle?: 'active' | 'archived'
  accuracy_score?: number
}

/** 时间趋势数据点 */
export interface TrendDataPoint {
  time_label: string
  predicted_load: number | null
  actual_load?: number | null
  error?: number | null
  mape?: number | null
  prediction_count?: number
  paired_count?: number
}

/** 误差分布统计 */
export interface ErrorDistribution {
  mean_error: number
  std_error: number
  min_error: number
  max_error: number
  max_absolute_error?: number
  percentiles: {
    p25: number
    p50: number
    p75: number
    p95: number
  }
  histogram: Array<{ bin: string; count: number }>
  bias: 'over_predict' | 'under_predict' | 'balanced'
  sample_count?: number
  error_definition?: 'forecast_minus_actual'
}

/** 模型漂移检测结果 */
export interface DriftDetection {
  drift_detected: boolean
  drift_score: number
  threshold: number
  recent_mape: number | null
  baseline_mape: number | null
  drift_direction?: 'degraded' | 'improved' | 'stable' | 'insufficient_data'
  change_percent?: number | null
  sample_count?: number
  recommendation?: string
}

/** 数据质量统计 */
export interface DataQualityStats {
  total_records: number
  valid_records: number
  invalid_records: number
  avg_quality_score: number
  issues: Array<{ type: string; count: number; description: string }>
}

// ========================================
// 光伏发电 ML 预测相关类型
// ========================================

/** 光伏 ML 模型信息 */
export interface SolarModelInfo {
  weight: number
  num_params: number
  loaded: boolean
  config: Record<string, any>
}

export interface SolarBacktestPair {
  target_time: string
  historical_actual: number
  historical_forecast: number
  error_mw: number
  absolute_error_mw: number
  percentage_error: number | null
}

export interface SolarBacktestMetrics {
  count: number
  daylight_count: number
  mae_mw: number
  rmse_mw: number
  mape: number | null
}

export interface SolarBacktestResult {
  pairs: SolarBacktestPair[]
  metrics: SolarBacktestMetrics | null
  data_source: string
  note: string
}

/** 光伏发电预测响应 (ML 模型) */
export interface SolarGenerationResponse {
  input_quality?: LoadInputQuality | null
  status: string
  model_type: 'tf_pv_v2'
  hourly_pv_mw: number[]
  hourly_pv_kw?: number[]
  hourly_efficiency?: number[]
  hourly_uncertainty_mw?: number[]
  timestamps: string[]
  total_mwh: number
  peak_mw: number
  capacity_factor: number
  model_info?: Record<string, SolarModelInfo>
  ensemble_weights?: Record<string, number>
  inference_time_ms?: number
  device?: string
  feature_count?: number
  lookback_hours?: number
  horizon_hours?: number
  panel_type?: string
  data_source?: string
  origin?: string | null
  historical?: SolarBacktestResult
  timestamp: string
}

/** 光伏 ML 模型信息响应 */
export interface SolarModelInfoResponse {
  status: string
  model_info?: Record<string, SolarModelInfo>
  service_status?: {
    loaded: boolean
    device: string
    model_count: number
    total_inferences: number
    average_inference_time_ms: number
    ensemble_weights: Record<string, number>
    feature_count: number
    lookback: number
    horizon: number
    capacity_mw?: number | null
  }
  training_metrics?: {
    training_date: string
    device: string
    gpu_name: string
    tensorflow_version?: string
    data_shapes: Record<string, number[]>
    results: Record<string, { metrics: Record<string, number> }>
    city_metrics: Record<string, Record<string, number>>
  }
  message?: string
  fallback?: string
  timestamp: string
}

// ========================================
// 预测 vs 实际负荷对比
// ========================================

export interface PredictionVsActualPair {
  target_timestamp: string
  load_forecast_mw: number
  actual_load_mw: number
  absolute_error_mw: number
  percentage_error: number | null
}

export interface PredictionVsActualResponse {
  status: string
  data: {
    pairs: PredictionVsActualPair[]
    summary: {
      count: number
      mae_mw: number
      rmse_mw: number
      mape: number | null
      data_source: string
      note: string
    } | null
  }
}

// ========================================
// 24h 负荷预测总览（历史回测验证 + 未来预测）
// ========================================

export interface HistoricalPair {
  target_time: string
  historical_actual: number | null
  historical_forecast: number | null
}

export interface FutureForecast {
  target_time: string
  future_forecast: number
  /** 电价预测 (USD/MWh)，仅 TensorFlow 引擎输出时有值 */
  price_p10?: number | null
  price_p50?: number | null
  price_p90?: number | null
  price_unit?: string
  /** 未来光伏发电预测 (MW)，仅未来段有值 */
  pv_forecast_mw?: number | null
}

export interface LoadOverviewData {
  generated_at: string
  current: { time: string | null; actual_load_mw: number | null }
  historical: {
    pairs: HistoricalPair[]
    metrics: { mae_mw: number; rmse_mw: number; mape: number | null } | null
    note: string
  }
  future: { predictions: FutureForecast[]; note: string }
  input_quality?: LoadInputQuality | null
  data_source?: string | null
}

export interface LoadOverviewResponse {
  status: string
  data: LoadOverviewData
}

// ========================================
// 任意日期历史回测与对比
// ========================================

export interface DayBacktestPair {
  target_time: string
  /** ISO-NE 真实负荷 (MW)；当天尚未回填的小时为 null */
  historical_actual: number | null
  historical_forecast: number
  /** 误差 = 预测 − 实际（正=高估），MW */
  error_mw: number | null
  absolute_error_mw: number | null
  percentage_error: number | null
}

export interface DayBacktestWeatherPoint {
  target_time: string
  temperature_2m: number | null
  wind_speed_10m: number | null
  cloud_cover: number | null
  shortwave_radiation: number | null
}

export interface DayBacktestData {
  date: string
  timezone: string
  available_date_range: { earliest: string | null; latest: string | null }
  pairs: DayBacktestPair[]
  metrics: { mae_mw: number; rmse_mw: number; mape: number | null } | null
  weather: DayBacktestWeatherPoint[]
  note: string
}

export interface DayBacktestRangeData {
  available_date_range: { earliest: string | null; latest: string | null }
}

// ========================================
// 智能电网综合运行态势
// ========================================
export interface OperationHourlyPoint {
  timestamp: string
  time_label: string
  load_mw: number
  pv_mw: number | null
  renewable_mw: number | null
  renewable_share_percent: number | null
  net_load_mw: number | null
}

export interface OperationSituation {
  generated_at: string
  input_quality?: LoadInputQuality | null
  data_scope: { region: string; horizon_hours: number; pv_coverage_hours?: number; renewable_note: string }
  hourly: OperationHourlyPoint[]
  renewable: {
    total_energy_mwh: number | null
    average_share_percent: number | null
    highest_share_percent: number | null
    highest_share_time: string
  }
  peak_valley: {
    peak_load_mw: number | null; peak_time: string; valley_load_mw: number | null; valley_time: string
    spread_mw: number | null; peak_net_load_mw: number | null; peak_net_load_time: string; renewable_peak_reduction_mw: number | null
  }
  supply_demand: {
    maximum_net_load_mw: number | null; maximum_net_load_time: string
    maximum_net_load_ramp_mw: number | null; ramp_time: string; interpretation: string
  }
  risks: Array<{ level: 'warning' | 'info'; time: string; message: string }>
  model: { inference_time_ms: number; data_source: string }
}

export interface HourlyErrorDiagnostic {
  hour: number; count: number; mae_mw: number | null; mape: number | null; bias_mw: number | null
}

export interface HourlyErrorDiagnostics {
  days: number; sample_count: number; hourly: HourlyErrorDiagnostic[]
  heatmap: Array<{ hour: number; date: string; error_mw: number; absolute_error_mw: number; mape: number | null }>
  insight: string; method_note: string
}

export interface FeatureSensitivity {
  generated_at: string
  horizon_hours: number
  ranking: Array<{
    feature_group: string
    mean_absolute_impact_mw: number
    peak_impact_mw: number
    directional_change_mw: number
    feature_count: number
  }>
  method_note: string
  data_note: string
}
