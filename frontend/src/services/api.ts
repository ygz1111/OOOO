import axios from 'axios'
import {
  LoadPredictionResponse,
  WeatherResponse,
  SystemStatus,
  WeatherData,
  ApiResponse,
  PredictionRecord,
  AccuracyStats,
  ModelComparisonItem,
  TrendDataPoint,
  ErrorDistribution,
  DriftDetection,
  DataQualityStats,
  SolarGenerationResponse,
  SolarModelInfoResponse,
  WindGenerationResponse,
  PowerCurveResponse
} from '../types'
import { LoginRequest, RegisterRequest, TokenResponse } from '../types/auth'

const API_BASE_URL = '/api'

class ApiService {
  private api = axios.create({
    baseURL: API_BASE_URL,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json'
    }
  })

  private authToken: string | null = null
  private onUnauthorized: (() => void) | null = null

  /**
   * 设置认证令牌（由 AuthContext 调用）
   */
  setAuthToken(token: string | null) {
    this.authToken = token
  }

  /**
   * 设置 401 未授权回调（由 AuthContext 调用，用于自动登出）
   */
  setOnUnauthorized(callback: (() => void) | null) {
    this.onUnauthorized = callback
  }

  /**
   * 统一请求封装：自动附加 Authorization 头，统一错误处理
   */
  private async request<T>(
    config: import('axios').AxiosRequestConfig
  ): Promise<T> {
    try {
      // 自动附加认证头
      if (this.authToken) {
        config.headers = {
          ...config.headers,
          Authorization: `Bearer ${this.authToken}`
        }
      }

      const response = await this.api.request<T>(config)
      return response.data
    } catch (error) {
      if (axios.isAxiosError(error)) {
        // 401 未授权 - 触发自动登出
        if (error.response?.status === 401 && this.onUnauthorized) {
          this.onUnauthorized()
        }

        // 统一提取后端错误消息
        const errData = error.response?.data
        let errMsg: string

        if (Array.isArray(errData?.detail)) {
          // FastAPI 422 Pydantic 验证错误: detail 是数组 [{loc, msg, type}, ...]
          errMsg = errData.detail
            .map((e: any) => e?.msg || JSON.stringify(e))
            .join('; ')
        } else if (typeof errData?.detail === 'string') {
          // 标准 HTTPException: detail 是字符串
          errMsg = errData.detail
        } else if (errData?.detail?.message) {
          // 自定义 ErrorHandler 包装格式: detail.message
          errMsg = errData.detail.message
        } else if (errData?.message) {
          // 其他格式: {message: "..."}
          errMsg = errData.message
        } else if (typeof errData === 'string') {
          errMsg = errData
        } else {
          errMsg = `请求失败 (HTTP ${error.response?.status || '未知'})`
        }

        throw new Error(errMsg)
      }
      throw error
    }
  }

  private async get<T>(url: string, params?: Record<string, any>): Promise<T> {
    return this.request<T>({ method: 'GET', url, params })
  }

  private async post<T>(url: string, data?: any, params?: Record<string, any>): Promise<T> {
    return this.request<T>({ method: 'POST', url, data, params })
  }

  // ===========================================================================
  // 认证授权 API
  // ===========================================================================

  /** 用户登录 */
  async login(credentials: LoginRequest): Promise<TokenResponse> {
    return this.post<TokenResponse>('/auth/login', credentials)
  }

  /** 用户注册 */
  async register(data: RegisterRequest): Promise<void> {
    await this.post('/auth/register', data)
  }

  /** 用户登出 */
  async logout(): Promise<void> {
    await this.post('/auth/logout')
  }

  /** 获取当前用户资料 */
  async getUserProfile(): Promise<any> {
    return this.get('/auth/me')
  }

  /** 修改密码 */
  async changePassword(oldPassword: string, newPassword: string): Promise<void> {
    await this.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword
    })
  }

  // ===========================================================================
  // 负荷预测 API
  // ===========================================================================

  /** 负荷预测 */
  async predictLoad(weatherData?: WeatherData[], historicalLoad?: any[], forceRefresh?: boolean): Promise<LoadPredictionResponse> {
    const requestBody: any = {}

    if (weatherData && weatherData.length > 0) {
      requestBody.weather_data = weatherData.map(data => ({
        timestamp: data.timestamp,
        temperature_2m: data.temperature_2m,
        dew_point_2m: data.dew_point_2m,
        relative_humidity_2m: data.relative_humidity_2m,
        wind_speed_10m: data.wind_speed_10m,
        cloud_cover: data.cloud_cover,
        shortwave_radiation: data.shortwave_radiation
      }))
    }

    if (historicalLoad && historicalLoad.length > 0) {
      requestBody.historical_load = historicalLoad
    }

    const params = forceRefresh ? { force_refresh: true } : undefined
    return this.post<LoadPredictionResponse>('/prediction/load', requestBody, params)
  }

  /** 获取当前气象数据 */
  async getCurrentWeather(forceRefresh?: boolean): Promise<WeatherResponse> {
    const params = forceRefresh ? { force_refresh: true } : undefined
    return this.get<WeatherResponse>('/weather/current', params)
  }

  /** 获取系统状态 */
  async getSystemStatus(): Promise<SystemStatus> {
    return this.get<SystemStatus>('/system/status')
  }

  /** 批量预测 */
  async batchPredict(requests: Array<{weather_data?: WeatherData[], historical_load?: any[]}>): Promise<any> {
    return this.post('/prediction/batch', { requests })
  }

  // ===========================================================================
  // 光伏发电 ML 预测 API
  // ===========================================================================

  /** 光伏发电 ML 预测 (4 模型集成) */
  async getSolarGeneration(forceRefresh?: boolean): Promise<SolarGenerationResponse> {
    const params = forceRefresh ? { force_refresh: true } : undefined
    return this.get<SolarGenerationResponse>('/solar-generation', params)
  }

  /** 光伏 ML 模型信息 */
  async getSolarModelInfo(): Promise<SolarModelInfoResponse> {
    return this.get<SolarModelInfoResponse>('/solar-generation/model-info')
  }

  /** 风电预测 */
  async getWindGeneration(): Promise<WindGenerationResponse> {
    return this.get<WindGenerationResponse>('/wind-generation')
  }

  /** 风电功率曲线 */
  async getWindPowerCurve(): Promise<PowerCurveResponse> {
    return this.get<PowerCurveResponse>('/wind-generation/power-curve')
  }

  /** 健康检查（公开端点） */
  async getHealth(): Promise<any> {
    return this.get('/health')
  }

  // ===========================================================================
  // 历史分析 API
  // ===========================================================================

  /** 获取历史预测记录 */
  async getPredictionHistory(params?: {
    startTime?: string
    endTime?: string
    modelType?: string
    limit?: number
  }): Promise<ApiResponse<PredictionRecord[]>> {
    const query: Record<string, any> = { limit: params?.limit ?? 100 }
    if (params?.startTime) query.start_time = params.startTime
    if (params?.endTime) query.end_time = params.endTime
    if (params?.modelType) query.model_type = params.modelType

    return this.get<ApiResponse<PredictionRecord[]>>('/prediction/history', query)
  }

  /** 获取预测准确性统计 */
  async getAccuracyStats(): Promise<ApiResponse<AccuracyStats>> {
    return this.get<ApiResponse<AccuracyStats>>('/analytics/accuracy/stats')
  }

  /** 获取最近预测记录 (含实际值对比) */
  async getRecentPredictions(limit: number = 50): Promise<ApiResponse<any[]>> {
    return this.get<ApiResponse<any[]>>('/analytics/accuracy/recent', { limit })
  }

  /** 检查模型漂移 */
  async checkModelDrift(): Promise<ApiResponse<DriftDetection>> {
    return this.get<ApiResponse<DriftDetection>>('/analytics/drift/check')
  }

  /** 获取数据质量统计 */
  async getDataQualityStats(): Promise<ApiResponse<DataQualityStats>> {
    return this.get<ApiResponse<DataQualityStats>>('/analytics/quality/stats')
  }

  /** 多模型预测对比 */
  async compareModels(hours: number = 24): Promise<ApiResponse<Record<string, ModelComparisonItem>>> {
    return this.get<ApiResponse<Record<string, ModelComparisonItem>>>('/analytics/comparison/models', { hours })
  }

  /** 时间维度趋势分析 */
  async analyzeTemporalTrends(
    timeWindow: 'hourly' | 'daily' | 'weekly' = 'daily',
    days: number = 7
  ): Promise<ApiResponse<{ trends: TrendDataPoint[]; summary: any }>> {
    return this.get<ApiResponse<{ trends: TrendDataPoint[]; summary: any }>>('/analytics/temporal/trends', {
      time_window: timeWindow,
      days
    })
  }

  /** 预测误差分布分析 */
  async analyzeErrorDistribution(days: number = 7): Promise<ApiResponse<ErrorDistribution>> {
    return this.get<ApiResponse<ErrorDistribution>>('/analytics/error/distribution', { days })
  }

  /** 负荷特性模式分析 */
  async analyzeLoadPatterns(days: number = 14): Promise<ApiResponse<any>> {
    return this.get<ApiResponse<any>>('/analytics/patterns/load', { days })
  }

  /** 生成综合分析报告 */
  async generateComprehensiveReport(days: number = 7): Promise<ApiResponse<any>> {
    return this.get<ApiResponse<any>>('/analytics/report/comprehensive', { days })
  }

  /** 获取仪表板综合指标 */
  async getDashboardMetrics(hours: number = 24): Promise<ApiResponse<any>> {
    return this.get<ApiResponse<any>>('/analytics/dashboard/metrics', { hours })
  }
}

export const apiService = new ApiService()
export default apiService
