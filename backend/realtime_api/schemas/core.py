"""
智能电网负荷预测系统 - Pydantic数据模型

定义API请求/响应的数据结构和数据库模型，包含：
- 预测请求/响应模型
- 气象数据模型
- 性能监控模型
- 数据库实体模型

作者: 毕业设计项目
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, model_validator, field_validator


# ========================================
# 基础数据模型
# ========================================

class TimestampMixin(BaseModel):
    """时间戳混合类"""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None


class LocationMixin(BaseModel):
    """地理位置混合类"""
    location: str = Field(..., max_length=100, description="地理位置名称")
    latitude: float = Field(default=42.36, ge=-90, le=90, description="纬度")
    longitude: float = Field(default=-71.06, ge=-180, le=180, description="经度")

    @field_validator('location')
    @classmethod
    def validate_location(cls, v):
        if not v or not v.strip():
            raise ValueError('位置名称不能为空')
        return v.strip()


# ========================================
# 气象数据模型 (数据库相关)
# ========================================

class WeatherDataBase(BaseModel):
    """气象数据基础模型"""
    timestamp: datetime
    location: str = Field(..., max_length=100)
    temperature_2m: Optional[float] = Field(None, description="2米高度温度(℃)")
    dew_point_2m: Optional[float] = Field(None, description="2米高度露点温度(℃)")
    relative_humidity_2m: Optional[float] = Field(
        None, ge=0, le=100, description="2米高度相对湿度(%)")
    wind_speed_10m: Optional[float] = Field(None, description="10米高度风速(m/s)")
    wind_direction_10m: Optional[float] = Field(
        None, ge=0, le=360, description="10米高度风向(度)")
    wind_gusts_10m: Optional[float] = Field(None, description="10米高度阵风(m/s)")
    cloud_cover: Optional[float] = Field(
        None, ge=0, le=100, description="云覆盖率(%)")
    shortwave_radiation: Optional[float] = Field(None, description="短波辐射(W/m²)")
    direct_radiation: Optional[float] = Field(None, description="直接辐射(W/m²)")
    diffuse_radiation: Optional[float] = Field(None, description="散射辐射(W/m²)")
    data_quality_score: float = Field(default=0.95, ge=0, le=1, description="数据质量评分")
    is_validated: bool = Field(default=False, description="是否已验证")
    data_source: str = Field(default='openmeteo', max_length=50, description="数据源")
    latitude: float = Field(default=42.36, ge=-90, le=90)
    longitude: float = Field(default=-71.06, ge=-180, le=180)


class WeatherDataCreate(WeatherDataBase):
    """创建气象数据请求模型"""
    pass


class WeatherDataResponse(WeatherDataBase, TimestampMixin):
    """气象数据响应模型"""
    id: int = Field(..., description="记录ID")

    class Config:
        from_attributes = True


class WeatherQueryRequest(BaseModel):
    """气象数据查询请求"""
    location: str = Field(..., max_length=100, description="位置名称")
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime = Field(..., description="结束时间")
    min_quality_score: float = Field(default=0.8, ge=0, le=1, description="最小质量评分")

    @model_validator(mode='before')
    @classmethod
    def validate_time_range(cls, values):
        start_time = values.get('start_time')
        end_time = values.get('end_time')
        if start_time and end_time:
            if start_time >= end_time:
                raise ValueError('开始时间必须早于结束时间')
            if (end_time - start_time).days > 365:
                raise ValueError('查询时间范围不能超过1年')
        return values


# ========================================
# API 请求/响应中的数据点模型
# ========================================

class WeatherDataPoint(BaseModel):
    """预测请求中的气象数据点"""
    timestamp: datetime = Field(..., description="时间戳")
    temperature_2m: float = Field(..., ge=-60, le=60, description="2米高度温度(℃)")
    dew_point_2m: float = Field(..., ge=-60, le=60, description="2米高度露点温度(℃)")
    relative_humidity_2m: Optional[float] = Field(None, ge=0, le=100, description="相对湿度(%)")
    wind_speed_10m: Optional[float] = Field(None, ge=0, description="10米高度风速(m/s)")
    wind_direction_10m: Optional[float] = Field(None, ge=0, le=360, description="10米高度风向(度)")
    surface_pressure: Optional[float] = Field(None, ge=300, le=1100, description="地面气压(hPa)")
    cloud_cover: Optional[float] = Field(None, ge=0, le=100, description="云覆盖率(%)")
    shortwave_radiation: Optional[float] = Field(None, ge=0, description="短波辐射(W/m²)")

    @model_validator(mode="after")
    def check_dew_point(self):
        """物理约束：露点温度不应高于气温"""
        if self.dew_point_2m > self.temperature_2m:
            raise ValueError(
                f"露点温度 ({self.dew_point_2m}℃) 不能高于气温 ({self.temperature_2m}℃)"
            )
        return self


class HistoricalLoadPoint(BaseModel):
    """预测请求中的历史负载数据点"""
    timestamp: datetime = Field(..., description="时间戳")
    system_load: float = Field(..., description="系统负荷(MW)")


# ========================================
# 负荷预测 API 模型
# ========================================

class HourlyPrediction(BaseModel):
    """每小时负荷预测数据"""
    hour: int = Field(..., ge=0, le=23, description="小时 (0-23)")
    timestamp: str = Field(..., description="预测时间戳")
    load_forecast_mw: float = Field(..., description="负荷预测 (MW)")
    pv_estimation_mw: Optional[float] = Field(None, description="光伏预测 (MW)，不可用时为空")
    net_load_mw: Optional[float] = Field(None, description="净负荷 (MW)，光伏不可用时为空")
    # 电价预测 (TF v2 模型输出, 2026-09; 旧引擎时为 None)
    price_p10: Optional[float] = Field(None, description="电价预测 P10 (USD/MWh)")
    price_p50: Optional[float] = Field(None, description="电价预测 P50 (USD/MWh)")
    price_p90: Optional[float] = Field(None, description="电价预测 P90 (USD/MWh)")


class ModelInfoResponse(BaseModel):
    """模型信息响应"""
    name: str = Field(..., description="模型名称")
    weight: float = Field(..., description="集成权重")
    num_params: int = Field(..., description="参数数量")
    loaded: bool = Field(..., description="是否已加载")


class TFLoadPriceFeatureInput(BaseModel):
    """TF v2 的完整在线特征窗口；字段名称和顺序由后端严格校验。"""
    past: List[Dict[str, Any]] = Field(..., min_length=168, max_length=168)
    future: List[Dict[str, Any]] = Field(..., min_length=24, max_length=24)


class TFPVFeatureInput(BaseModel):
    """TF PV 的完整在线特征窗口。"""
    past: List[Dict[str, Any]] = Field(..., min_length=96, max_length=96)
    future: List[Dict[str, Any]] = Field(..., min_length=24, max_length=24)


class LoadPredictionRequest(BaseModel):
    """负荷预测请求模型"""
    weather_data: Optional[List[WeatherDataPoint]] = Field(
        None, description="气象数据列表(可选，不提供则自动从API获取)")
    historical_load: Optional[List[HistoricalLoadPoint]] = Field(
        None, description="历史负载数据列表(可选)")
    tf_load_price_features: Optional[TFLoadPriceFeatureInput] = Field(
        None,
        description="TF v2 实时特征：过去168小时15特征 + 未来24小时13特征",
    )
    tf_pv_features: Optional[TFPVFeatureInput] = Field(
        None,
        description="TF PV 实时特征：过去96小时12特征 + 未来24小时7特征",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "weather_data": [],
                "historical_load": []
            }
        }


class LoadPredictionResponse(BaseModel):
    """负荷预测响应模型 (API)"""
    status: str = Field(..., description="请求状态")
    predictions: List[HourlyPrediction] = Field(..., description="24小时预测数据")
    model_info: List[ModelInfoResponse] = Field(..., description="模型信息")
    ensemble_weights: Dict[str, float] = Field(..., description="集成权重")
    inference_time_ms: float = Field(..., description="推理耗时(毫秒)")
    data_source: str = Field(..., description="数据来源")
    timestamp: str = Field(..., description="响应时间戳")
    engine: Optional[str] = Field(None, description="TensorFlow 负荷模型引擎 (tf_v2/tf_split_v1)")
    pv_engine: Optional[str] = Field(None, description="TensorFlow 光伏引擎 (tf_pv)")
    origin: Optional[str] = Field(None, description="预测锚点（America/New_York 整点）")
    input_quality: Optional[Dict[str, Any]] = Field(
        None, description="在线输入质量、部分采样与日前特征补值信息"
    )


# ========================================
# 电价预测 API 模型 (TensorFlow, 2026-09)
# ========================================

class HourlyPricePoint(BaseModel):
    """每小时电价预测点"""
    hour: int = Field(..., ge=0, le=23, description="小时 (0-23)")
    timestamp: str = Field(..., description="预测时间戳")
    price_p10: float = Field(..., description="电价预测 P10 (USD/MWh)")
    price_p50: float = Field(..., description="电价预测 P50 (USD/MWh)")
    price_p90: float = Field(..., description="电价预测 P90 (USD/MWh)")
    load_forecast_mw: Optional[float] = Field(None, description="同窗口负荷预测 (MW)")


class PriceForecastResponse(BaseModel):
    """电价预测响应 (24h, p10/p50/p90)"""
    status: str = Field(..., description="请求状态")
    model: str = Field(default="tf_split_v1", description="模型标识")
    model_name: str = Field(default="TF Split v1 (独立负荷 + 独立电价分位)", description="模型名称")
    predictions: List[HourlyPricePoint] = Field(..., description="24小时电价预测")
    origin: Optional[str] = Field(None, description="预测锚点时间")
    inference_time_ms: float = Field(..., description="推理耗时(毫秒)")
    data_source: str = Field(..., description="数据来源")
    timestamp: str = Field(..., description="响应时间戳")
    input_quality: Optional[Dict[str, Any]] = None


class BatchPredictionRequest(BaseModel):
    """批量负荷预测请求"""
    requests: List[LoadPredictionRequest] = Field(
        ..., min_length=1, max_length=10, description="预测请求列表(最多10个)")

    class Config:
        json_schema_extra = {
            "example": {
                "requests": [
                    {"weather_data": [], "historical_load": []}
                ]
            }
        }


class BatchPredictionResponse(BaseModel):
    """批量负荷预测响应"""
    status: str = Field(..., description="处理状态")
    results: List[LoadPredictionResponse] = Field(..., description="预测结果列表")
    total_time_ms: float = Field(..., description="总耗时(毫秒)")
    timestamp: str = Field(..., description="响应时间戳")


# ========================================
# 负荷预测 数据库模型
# ========================================

class LoadPredictionBase(BaseModel):
    """负荷预测基础模型 (数据库)"""
    prediction_timestamp: datetime = Field(..., description="预测生成时间")
    target_timestamp: datetime = Field(..., description="预测目标时间")
    load_forecast_mw: float = Field(..., gt=0, description="负荷预测值(MW)")
    pv_estimation_mw: Optional[float] = Field(None, ge=0, description="光伏发电估算(MW)")
    net_load_mw: Optional[float] = Field(None, description="净负荷(MW)")
    confidence_lower_mw: Optional[float] = Field(None, description="置信下限(MW)")
    confidence_upper_mw: Optional[float] = Field(None, description="置信上限(MW)")
    model_type: str = Field(default='ensemble', max_length=50, description="模型类型")
    model_weights: Optional[Dict[str, Any]] = Field(None, description="模型权重配置")
    inference_time_ms: Optional[float] = Field(None, ge=0, description="推理时间(毫秒)")
    cache_hit: bool = Field(default=False, description="是否缓存命中")
    data_source: Optional[str] = Field(None, max_length=50, description="数据源")

    @field_validator('confidence_lower_mw')
    @classmethod
    def validate_confidence_lower(cls, v, info):
        if v is not None and 'load_forecast_mw' in info.data:
            if v >= info.data['load_forecast_mw']:
                raise ValueError('置信下限不能大于等于预测值')
        return v

    @field_validator('confidence_upper_mw')
    @classmethod
    def validate_confidence_upper(cls, v, info):
        if v is not None and 'load_forecast_mw' in info.data:
            if v <= info.data['load_forecast_mw']:
                raise ValueError('置信上限不能小于等于预测值')
        return v


class LoadPredictionCreate(LoadPredictionBase):
    """创建负荷预测请求模型 (数据库)"""
    pass


class LoadPredictionDBResponse(LoadPredictionBase, TimestampMixin):
    """负荷预测数据库响应模型"""
    id: int = Field(..., description="预测记录ID")
    prediction_id: str = Field(..., description="预测批次ID")

    class Config:
        from_attributes = True


class PredictionQueryRequest(BaseModel):
    """预测查询请求"""
    start_time: datetime = Field(..., description="查询开始时间")
    end_time: datetime = Field(..., description="查询结束时间")
    model_type: Optional[str] = Field(None, description="模型类型过滤")
    limit: int = Field(default=100, ge=1, le=1000, description="返回结果数量")

    @model_validator(mode='before')
    @classmethod
    def validate_query_params(cls, values):
        start_time = values.get('start_time')
        end_time = values.get('end_time')
        limit = values.get('limit')

        if start_time and end_time:
            if start_time >= end_time:
                raise ValueError('开始时间必须早于结束时间')
            if (end_time - start_time).days > 30:
                raise ValueError('查询时间范围不能超过30天')

        if limit and (limit < 1 or limit > 1000):
            raise ValueError('返回结果数量必须在1-1000之间')

        return values


# ========================================
# 模型性能模型
# ========================================

class ModelPerformanceBase(BaseModel):
    """模型性能基础模型"""
    model_name: str = Field(..., max_length=100, description="模型名称")
    model_version: Optional[str] = Field(None, max_length=50, description="模型版本")
    total_inferences: int = Field(default=0, ge=0, description="总推理次数")
    successful_inferences: int = Field(default=0, ge=0, description="成功推理次数")
    failed_inferences: int = Field(default=0, ge=0, description="失败推理次数")
    average_inference_time_ms: Optional[float] = Field(None, ge=0, description="平均推理时间(毫秒)")
    mae: Optional[float] = Field(None, ge=0, description="平均绝对误差")
    rmse: Optional[float] = Field(None, ge=0, description="均方根误差")
    mape: Optional[float] = Field(None, ge=0, le=1, description="平均绝对百分比误差")
    gpu_memory_used_mb: Optional[float] = Field(None, ge=0, description="GPU显存使用(MB)")
    cpu_utilization_percent: Optional[float] = Field(
        None, ge=0, le=100, description="CPU使用率(%)")
    batch_size: int = Field(default=1, ge=1, description="批处理大小")
    device: str = Field(default='cuda', max_length=20, description="运行设备")

    @field_validator('mape')
    @classmethod
    def validate_mape(cls, v):
        if v is not None and (v < 0 or v > 1):
            raise ValueError('MAPE必须在0-1之间')
        return v


class ModelPerformanceCreate(ModelPerformanceBase):
    """创建模型性能记录"""
    pass


class ModelPerformanceResponse(ModelPerformanceBase, TimestampMixin):
    """模型性能响应"""
    id: int = Field(..., description="记录ID")

    class Config:
        from_attributes = True


# ========================================
# API日志模型
# ========================================

class APILogBase(BaseModel):
    """API日志基础模型"""
    request_id: str = Field(..., description="请求ID")
    endpoint: str = Field(..., max_length=200, description="API端点")
    method: str = Field(..., max_length=10, description="HTTP方法")
    status_code: Optional[int] = Field(None, description="HTTP状态码")
    response_time_ms: Optional[float] = Field(None, ge=0, description="响应时间(毫秒)")
    request_size_bytes: Optional[int] = Field(None, ge=0, description="请求大小(字节)")
    response_size_bytes: Optional[int] = Field(None, ge=0, description="响应大小(字节)")
    client_ip: Optional[str] = Field(None, description="客户端IP")
    user_agent: Optional[str] = Field(None, max_length=500, description="User-Agent")
    error_message: Optional[str] = Field(None, description="错误信息")

    @field_validator('method')
    @classmethod
    def validate_method(cls, v):
        allowed_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']
        if v not in allowed_methods:
            raise ValueError(f'HTTP方法必须是以下之一: {allowed_methods}')
        return v


class APILogResponse(APILogBase, TimestampMixin):
    """API日志响应"""
    id: int = Field(..., description="日志ID")

    class Config:
        from_attributes = True


# ========================================
# 系统监控模型
# ========================================

class SystemMetricsBase(BaseModel):
    """系统监控指标基础模型"""
    timestamp: datetime = Field(default_factory=datetime.now)
    cpu_percent: Optional[float] = Field(None, ge=0, le=100, description="CPU使用率(%)")
    cpu_count: Optional[int] = Field(None, ge=1, description="CPU核心数")
    memory_percent: Optional[float] = Field(None, ge=0, le=100, description="内存使用率(%)")
    memory_used_gb: Optional[float] = Field(None, ge=0, description="内存使用量(GB)")
    memory_available_gb: Optional[float] = Field(None, ge=0, description="可用内存(GB)")
    gpu_available: bool = Field(default=False, description="GPU是否可用")
    gpu_memory_used_mb: Optional[float] = Field(None, ge=0, description="GPU显存使用(MB)")
    gpu_memory_total_mb: Optional[float] = Field(None, ge=0, description="GPU显存总量(MB)")
    gpu_utilization_percent: Optional[float] = Field(
        None, ge=0, le=100, description="GPU使用率(%)")
    gpu_temperature_c: Optional[float] = Field(None, ge=0, description="GPU温度(℃)")
    network_bytes_sent: Optional[int] = Field(None, ge=0, description="网络发送字节数")
    network_bytes_recv: Optional[int] = Field(None, ge=0, description="网络接收字节数")
    disk_usage_percent: Optional[float] = Field(None, ge=0, le=100, description="磁盘使用率(%)")
    process_count: Optional[int] = Field(None, ge=0, description="进程数量")
    active_connections: Optional[int] = Field(None, ge=0, description="活跃连接数")


class SystemMetricsResponse(SystemMetricsBase, TimestampMixin):
    """系统监控指标响应"""
    id: int = Field(..., description="记录ID")

    class Config:
        from_attributes = True


# ========================================
# 缓存性能模型
# ========================================

class CachePerformanceBase(BaseModel):
    """缓存性能基础模型"""
    timestamp: datetime = Field(default_factory=datetime.now)
    cache_hits: int = Field(default=0, ge=0, description="缓存命中次数")
    cache_misses: int = Field(default=0, ge=0, description="缓存未命中次数")
    cache_hit_ratio: Optional[float] = Field(None, ge=0, le=1, description="缓存命中率")
    cache_memory_used_mb: Optional[float] = Field(None, ge=0, description="缓存内存使用(MB)")
    cache_keys_count: Optional[int] = Field(None, ge=0, description="缓存键数量")
    avg_cache_hit_time_ms: Optional[float] = Field(None, ge=0, description="平均缓存命中时间(毫秒)")
    avg_cache_miss_time_ms: Optional[float] = Field(None, ge=0, description="平均缓存未命中时间(毫秒)")

    @field_validator('cache_hit_ratio')
    @classmethod
    def validate_hit_ratio(cls, v, info):
        if v is not None:
            return v
        # 自动计算命中率
        hits = info.data.get('cache_hits', 0) if info.data else 0
        misses = info.data.get('cache_misses', 0) if info.data else 0
        total = hits + misses
        if total > 0:
            return hits / total
        return 0.0


class CachePerformanceResponse(CachePerformanceBase, TimestampMixin):
    """缓存性能响应"""
    id: int = Field(..., description="记录ID")
    actual_hit_ratio: float = Field(..., description="实际命中率")

    class Config:
        from_attributes = True


# ========================================
# 性能预警模型
# ========================================

class PerformanceAlertBase(BaseModel):
    """性能预警基础模型"""
    timestamp: datetime = Field(default_factory=datetime.now)
    alert_type: str = Field(..., description="预警类型")
    metric_name: str = Field(..., max_length=100, description="指标名称")
    current_value: Optional[float] = Field(None, description="当前值")
    threshold: Optional[float] = Field(None, description="阈值")
    message: str = Field(default='', description="预警消息")
    severity: int = Field(default=3, ge=1, le=5, description="严重程度(1-5)")
    resolved: bool = Field(default=False, description="是否已解决")
    resolved_at: Optional[datetime] = Field(None, description="解决时间")
    resolved_by: Optional[str] = Field(None, max_length=100, description="解决人")

    @field_validator('alert_type')
    @classmethod
    def validate_alert_type(cls, v):
        allowed_types = ['critical', 'warning', 'info', 'error']
        if v not in allowed_types:
            raise ValueError(f'预警类型必须是以下之一: {allowed_types}')
        return v


class PerformanceAlertResponse(PerformanceAlertBase):
    """性能预警响应"""
    id: int = Field(..., description="预警ID")

    class Config:
        from_attributes = True


# ========================================
# 综合响应模型
# ========================================

class HealthCheckResponse(BaseModel):
    """系统健康检查响应"""
    status: str = Field(..., description="系统状态")
    timestamp: datetime = Field(..., description="检查时间")
    components: Dict[str, Any] = Field(..., description="各组件状态")
    uptime: float = Field(..., description="运行时间(秒)")
    version: str = Field(default="1.0.0", description="系统版本")


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(None, description="错误代码")
    details: Optional[Dict[str, Any]] = Field(None, description="详细信息")
    timestamp: datetime = Field(default_factory=datetime.now)


class SuccessResponse(BaseModel):
    """成功响应模型"""
    success: bool = Field(default=True)
    message: str = Field(..., description="成功消息")
    data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = Field(None, description="返回数据")
    timestamp: datetime = Field(default_factory=datetime.now)


# ========================================
# 气象与系统 API 响应模型
# ========================================

class WeatherStationData(BaseModel):
    """气象站点数据"""
    name: str = Field(..., description="站点名称")
    latitude: float = Field(..., description="纬度")
    longitude: float = Field(..., description="经度")
    temperature_2m: float = Field(..., description="温度 (°C)")
    dew_point_2m: float = Field(..., description="露点温度 (°C)")
    relative_humidity_2m: Optional[float] = Field(None, description="相对湿度 (%)")
    wind_speed_10m: Optional[float] = Field(None, description="风速 (m/s)")
    cloud_cover: Optional[float] = Field(None, description="云量 (%)")
    shortwave_radiation: Optional[float] = Field(None, description="短波辐射 (W/m²)")


class WeatherResponse(BaseModel):
    """气象数据响应"""
    status: str = Field(..., description="请求状态")
    timestamp: str = Field(..., description="响应时间")
    stations: List[WeatherStationData] = Field(..., description="站点数据列表")
    regional_average: Dict[str, float] = Field(..., description="区域平均值")


class SystemStatusResponse(BaseModel):
    """系统状态响应"""
    status: str = Field(..., description="系统状态")
    models_loaded: int = Field(..., description="已加载模型数量")
    models_total: int = Field(4, description="模型总数")
    device: str = Field(..., description="运行设备")
    total_inferences: int = Field(..., description="总推理次数")
    average_inference_time_ms: float = Field(..., description="平均推理时间")
    ensemble_weights: Dict[str, float] = Field(..., description="集成权重")
    model_details: List[Dict[str, Any]] = Field(default_factory=list, description="当前生产模型明细")
    uptime_seconds: float = Field(..., description="运行时间 (秒)")
    memory_usage_mb: Optional[float] = Field(None, description="内存使用 (MB)")
    timestamp: str = Field(..., description="响应时间")


# ========================================
# 导出
# ========================================

__all__ = [
    'TimestampMixin',
    'LocationMixin',
    # 气象数据
    'WeatherDataBase', 'WeatherDataCreate', 'WeatherDataResponse', 'WeatherQueryRequest',
    # API 数据点
    'WeatherDataPoint', 'HistoricalLoadPoint',
    # 负荷预测 API
    'HourlyPrediction', 'ModelInfoResponse', 'TFLoadPriceFeatureInput', 'TFPVFeatureInput',
    'LoadPredictionRequest', 'LoadPredictionResponse',
    # 电价预测 API
    'HourlyPricePoint', 'PriceForecastResponse',
    'BatchPredictionRequest', 'BatchPredictionResponse',
    # 负荷预测 数据库
    'LoadPredictionBase', 'LoadPredictionCreate', 'LoadPredictionDBResponse',
    'PredictionQueryRequest',
    # 模型性能
    'ModelPerformanceBase', 'ModelPerformanceCreate', 'ModelPerformanceResponse',
    # API日志
    'APILogBase', 'APILogResponse',
    # 系统监控
    'SystemMetricsBase', 'SystemMetricsResponse',
    # 缓存性能
    'CachePerformanceBase', 'CachePerformanceResponse',
    # 性能预警
    'PerformanceAlertBase', 'PerformanceAlertResponse',
    # 综合响应
    'HealthCheckResponse', 'ErrorResponse', 'SuccessResponse',
    # 气象与系统响应
    'WeatherStationData', 'WeatherResponse', 'SystemStatusResponse',
]
