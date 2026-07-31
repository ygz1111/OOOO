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
  pv_estimation_mw: number
  wind_estimation_mw?: number
  net_load_mw: number
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
  device: string
  total_inferences: number
  average_inference_time_ms: number
  ensemble_weights: Record<string, number>
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

export interface ChartDataPoint {
  timestamp: string
  [key: string]: string | number
}

export interface ForecastMetrics {
  mape: number
  rmse: number
  mae: number
  r2: number
}

export interface TimeRange {
  start: string
  end: string
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
  wind_estimation_mw?: number | null
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

/** 准确性统计 */
export interface AccuracyStats {
  count: number
  mape: number | null
  rmse: number | null
  mae: number | null
  r2: number | null
  best_model?: string
  worst_model?: string
}

/** 模型对比项 */
export interface ModelComparisonItem {
  model_name: string
  count: number
  mape: number | null
  rmse: number | null
  mae: number | null
  avg_inference_time_ms: number | null
  accuracy_score?: number
}

/** 时间趋势数据点 */
export interface TrendDataPoint {
  time_label: string
  predicted_load: number
  actual_load?: number
  error?: number
  mape?: number
}

/** 误差分布统计 */
export interface ErrorDistribution {
  mean_error: number
  std_error: number
  min_error: number
  max_error: number
  percentiles: {
    p25: number
    p50: number
    p75: number
    p95: number
  }
  histogram: Array<{ bin: string; count: number }>
  bias: 'over_predict' | 'under_predict' | 'balanced'
}

/** 模型漂移检测结果 */
export interface DriftDetection {
  drift_detected: boolean
  drift_score: number
  threshold: number
  recent_mape: number | null
  baseline_mape: number | null
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

/** 光伏发电预测响应 (ML 模型) */
export interface SolarGenerationResponse {
  status: string
  model_type: 'ml_ensemble' | 'physical'
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
  }
  training_metrics?: {
    training_date: string
    device: string
    gpu_name: string
    torch_version: string
    data_shapes: Record<string, number[]>
    results: Record<string, { metrics: Record<string, number> }>
    city_metrics: Record<string, Record<string, number>>
  }
  message?: string
  fallback?: string
  timestamp: string
}