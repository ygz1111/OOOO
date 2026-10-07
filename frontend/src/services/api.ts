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
  SolarGenerationResponse,
  SolarModelInfoResponse,
  LoadOverviewResponse,
  OperationSituation,
  HourlyErrorDiagnostics,
  FeatureSensitivity,
  DayBacktestData,
  DayBacktestRangeData,
  PriceForecastResponse,
  PriceBacktestData,
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
  private sessionVersion = 0
  private onUnauthorized: (() => void) | null = null
  private onTokenRefreshed: ((token: string) => void) | null = null
  private refreshPromise: Promise<boolean> | null = null
  // 负荷预测是 POST，但首次加载、StrictMode 校验与页面刷新可能在同一时刻
  // 请求完全相同的数据。按请求内容做单飞，避免重复 TF 推理和重复入库。
  private loadPredictionPromises = new Map<string, Promise<LoadPredictionResponse>>()
  // 重型回测在 React StrictMode/手动刷新交叠时只允许一个请求在飞行，
  // 避免同一份 Archive 气象被重复拉取，造成 Open-Meteo 限流与后端超时。
  private overviewPromise: Promise<LoadOverviewResponse> | null = null

  private static TOKEN_KEY = 'smartgrid_access_token'
  private static REFRESH_TOKEN_KEY = 'smartgrid_refresh_token'

  /**
   * 设置认证令牌（由 AuthContext 调用）
   */
  setAuthToken(token: string | null) {
    if (token !== this.authToken) {
      this.sessionVersion += 1
      this.refreshPromise = null
      this.inflight.clear()
      this.loadPredictionPromises.clear()
      this.overviewPromise = null
    }
    this.authToken = token
  }

  private assertSession(version: number) {
    if (version !== this.sessionVersion) throw new Error('登录状态已改变，请重新发起请求')
  }

  /**
   * 设置 401 未授权回调（由 AuthContext 调用，用于自动登出）
   */
  setOnUnauthorized(callback: (() => void) | null) {
    this.onUnauthorized = callback
  }

  /**
   * 设置令牌刷新回调（AuthContext 用于同步 React state）
   */
  setOnTokenRefreshed(callback: ((token: string) => void) | null) {
    this.onTokenRefreshed = callback
  }

  /**
   * 用 refresh token 换取新 access token（单飞：并发 401 只刷新一次）
   */
  private async tryRefreshToken(version: number): Promise<boolean> {
    this.assertSession(version)
    if (this.refreshPromise) return this.refreshPromise
    // 无刷新凭据时不保存已完成的 Promise，避免阻塞下次登录后的续期。
    const refreshToken =
      localStorage.getItem(ApiService.REFRESH_TOKEN_KEY) ??
      sessionStorage.getItem(ApiService.REFRESH_TOKEN_KEY)
    if (!refreshToken) return false
    const task = (async () => {
      try {
        const res = await this.api.post('/auth/refresh', { refresh_token: refreshToken })
        this.assertSession(version)
        const { access_token, refresh_token } = res.data
        if (!access_token) throw new Error('登录续期响应缺少令牌，请稍后重试')
        this.authToken = access_token
        const remember =
          localStorage.getItem(ApiService.TOKEN_KEY) != null ||
          localStorage.getItem(ApiService.REFRESH_TOKEN_KEY) != null
        if (remember) {
          localStorage.setItem(ApiService.TOKEN_KEY, access_token)
          if (refresh_token) localStorage.setItem(ApiService.REFRESH_TOKEN_KEY, refresh_token)
        } else {
          sessionStorage.setItem(ApiService.TOKEN_KEY, access_token)
          if (refresh_token) sessionStorage.setItem(ApiService.REFRESH_TOKEN_KEY, refresh_token)
        }
        this.onTokenRefreshed?.(access_token)
        return true
      } catch (error) {
        this.assertSession(version)
        // 只有明确的身份拒绝才清除凭据；断网或 5xx 留待后续重试。
        if (!axios.isAxiosError(error) || error.response?.status !== 401) throw error
        localStorage.removeItem(ApiService.TOKEN_KEY)
        localStorage.removeItem(ApiService.REFRESH_TOKEN_KEY)
        sessionStorage.removeItem(ApiService.TOKEN_KEY)
        sessionStorage.removeItem(ApiService.REFRESH_TOKEN_KEY)
        return false
      }
    })().finally(() => {
      if (this.refreshPromise === task) this.refreshPromise = null
    })
    this.refreshPromise = task
    return task
  }

  /**
   * 统一请求封装：自动附加 Authorization 头，统一错误处理。
   *
   * 2026-08 优化（并发去重）：首屏多个组件（Dashboard/LoadForecast 等）会同时
   * 请求同一 GET 端点（如 /prediction/overview）。对相同 method+url+params 的
   * 进行中 GET 请求共享同一个 Promise，避免重复请求放大后端计算压力
   * （配合后端 overview 单飞，彻底消除"并发重算 + 30s 超时 504"）。
   * 写请求（POST/PUT/DELETE）有副作用，不去重。
   */
  private inflight = new Map<string, Promise<any>>()

  private inflightKey(config: import('axios').AxiosRequestConfig): string {
    const params = config.params ? JSON.stringify(config.params) : ''
    return `${config.method}:${config.url}:${params}`
  }

  private async request<T>(
    config: import('axios').AxiosRequestConfig
  ): Promise<T> {
    const key = this.inflightKey(config)
    const isGet = (config.method ?? 'get').toUpperCase() === 'GET'

    if (isGet) {
      const pending = this.inflight.get(key)
      if (pending) {
        return pending as Promise<T>
      }
    }

    const promise = this.doRequest<T>(config).finally(() => {
      if (this.inflight.get(key) === promise) this.inflight.delete(key)
    })
    if (isGet) {
      this.inflight.set(key, promise)
    }
    return promise
  }

  private async doRequest<T>(
    config: import('axios').AxiosRequestConfig
  ): Promise<T> {
    const version = this.sessionVersion
    try {
      // 自动附加认证头
      if (this.authToken) {
        config.headers = {
          ...config.headers,
          Authorization: `Bearer ${this.authToken}`
        }
      }

      try {
        const response = await this.api.request<T>(config)
        this.assertSession(version)
        return response.data
      } catch (error) {
        this.assertSession(version)
        // 登录失败属于本次表单，不应续期或注销另一份有效会话。
        const isLoginRequest = config.url === '/auth/login' || config.url === '/auth/register'
        if (axios.isAxiosError(error) && error.response?.status === 401 && !isLoginRequest) {
          const refreshed = await this.tryRefreshToken(version)
          this.assertSession(version)
          if (refreshed) {
            config.headers = {
              ...config.headers,
              Authorization: `Bearer ${this.authToken}`
            }
            try {
              const retry = await this.api.request<T>(config)
              this.assertSession(version)
              return retry.data
            } catch (retryError) {
              this.assertSession(version)
              if (axios.isAxiosError(retryError) && retryError.response?.status === 401) this.onUnauthorized?.()
              throw retryError
            }
          }
          this.onUnauthorized?.()
        }
        throw error
      }
    } catch (error) {
      if (axios.isAxiosError(error)) {
        // 统一提取后端错误消息
        const errData = error.response?.data
        let errMsg: string

        if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
          const seconds = Math.round(Number(config.timeout ?? this.api.defaults.timeout ?? 0) / 1000)
          errMsg = seconds > 0
            ? `请求超时（等待超过 ${seconds} 秒），系统将自动重试`
            : '请求超时，系统将自动重试'
        } else if (!error.response) {
          errMsg = '网络连接中断，系统将自动重试'
        } else if (Array.isArray(errData?.detail)) {
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

  private async get<T>(url: string, params?: Record<string, any>, timeoutMs?: number): Promise<T> {
    return this.request<T>({ method: 'GET', url, params, timeout: timeoutMs })
  }

  private async post<T>(url: string, data?: any, params?: Record<string, any>, timeoutMs?: number): Promise<T> {
    return this.request<T>({ method: 'POST', url, data, params, timeout: timeoutMs })
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
    // 该端点内部会触发气象 API 拉取（冷缓存时 6 站点 + 限速约 10-20s）+ 模型推理，
    // 默认 30s 超时在冷缓存/网络慢时可能误报失败；后端中间件对该端点放宽到 120s，
    // 前端对齐到 120s（2026-08：90s → 120s）
    const requestKey = JSON.stringify({ requestBody, forceRefresh: Boolean(forceRefresh) })
    const pending = this.loadPredictionPromises.get(requestKey)
    if (pending) return pending

    const predictionPromise = this.post<LoadPredictionResponse>(
      '/prediction/load', requestBody, params, 120000
    ).finally(() => {
      if (this.loadPredictionPromises.get(requestKey) === predictionPromise) this.loadPredictionPromises.delete(requestKey)
    })
    this.loadPredictionPromises.set(requestKey, predictionPromise)
    return predictionPromise
  }

  /** 获取当前气象数据 */
  async getCurrentWeather(forceRefresh?: boolean): Promise<WeatherResponse> {
    const params = forceRefresh ? { force_refresh: true } : undefined
    return this.get<WeatherResponse>('/weather/current', params, 90000)
  }

  /** 获取系统状态 */
  async getSystemStatus(): Promise<SystemStatus> {
    return this.get<SystemStatus>('/system/status')
  }

  // ===========================================================================
  // 光伏发电 TensorFlow 预测 API
  // ===========================================================================

  /** 光伏发电预测（TensorFlow pv_v2） */
  async getSolarGeneration(forceRefresh?: boolean): Promise<SolarGenerationResponse> {
    const params = forceRefresh ? { force_refresh: true } : undefined
    // 在线响应包含 24 个逐小时光伏回测窗口，冷启动时需要多次 TF 推理。
    return this.get<SolarGenerationResponse>('/solar-generation', params, 60000)
  }

  /** 光伏 TensorFlow 模型信息 */
  async getSolarModelInfo(): Promise<SolarModelInfoResponse> {
    return this.get<SolarModelInfoResponse>('/solar-generation/model-info')
  }

  /** 电价预测 (TensorFlow, 24h p10/p50/p90, USD/MWh) */
  async getPriceForecast(forceRefresh?: boolean): Promise<PriceForecastResponse> {
    return this.get<PriceForecastResponse>('/price/forecast', forceRefresh ? { force_refresh: true } : undefined, 60000)
  }

  /** 电价预测模型信息 */
  async getPriceModelInfo(): Promise<any> {
    return this.get<any>('/price/model-info')
  }

  /** 24h 负荷预测总览（历史回测验证 + 未来预测 + 当前实际） */
  async getLoadOverview(forceRefresh?: boolean): Promise<LoadOverviewResponse> {
    if (!this.overviewPromise) {
      const task = this.get<LoadOverviewResponse>('/prediction/overview', forceRefresh ? { force_refresh: true } : undefined, 120000)
        .finally(() => { if (this.overviewPromise === task) this.overviewPromise = null })
      this.overviewPromise = task
    }
    return this.overviewPromise
  }

  /** 智能电网 24h 综合运行态势（不写入历史预测记录） */
  async getOperationSituation(): Promise<ApiResponse<OperationSituation>> {
    return this.get<ApiResponse<OperationSituation>>('/analytics/operations/situation', undefined, 120000)
  }

  /** 分小时误差热力图与后验误差诊断 */
  async getHourlyErrorDiagnostics(days: number = 7): Promise<ApiResponse<HourlyErrorDiagnostics>> {
    return this.get<ApiResponse<HourlyErrorDiagnostics>>('/analytics/diagnostics/hourly-errors', { days })
  }

  /** 当前负荷预测的特征组遮蔽敏感度（不重训模型） */
  async getFeatureSensitivity(): Promise<ApiResponse<FeatureSensitivity>> {
    return this.get<ApiResponse<FeatureSensitivity>>('/analytics/operations/feature-sensitivity', undefined, 120000)
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
  async getAccuracyStats(days: number = 7): Promise<ApiResponse<AccuracyStats>> {
    return this.get<ApiResponse<AccuracyStats>>('/analytics/accuracy/stats', { days })
  }

  /** 检查模型漂移 */
  async checkModelDrift(): Promise<ApiResponse<DriftDetection>> {
    return this.get<ApiResponse<DriftDetection>>('/analytics/drift/check')
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

  /**
   * 任意日期历史回测：选日重新调用模型与该日 ISO-NE 真实负荷对比（不重训模型）。
   * date 缺省时后端只返回可用日期范围（轻量，用于初始化日期选择器）。
   * 重型端点（24 次回测推理 + 历史气象），120s 超时。
   */
  async getDayBacktest(date?: string, forceRefresh: boolean = false): Promise<ApiResponse<DayBacktestData | DayBacktestRangeData>> {
    return this.get<ApiResponse<DayBacktestData | DayBacktestRangeData>>(
      '/analytics/backtest/date',
      date ? { date, force_refresh: forceRefresh } : undefined,
      120000
    )
  }

  /** TensorFlow 电价历史回测：缺省查询日期范围，传 date 后返回 24h 预测与真实 RT-LMP。 */
  async getPriceBacktest(date?: string): Promise<ApiResponse<PriceBacktestData>> {
    return this.get<ApiResponse<PriceBacktestData>>(
      '/price/backtest',
      date ? { date } : undefined,
      120000
    )
  }
}

export const apiService = new ApiService()
export default apiService
