"""
智能电网负荷预测系统 - API 数据模型 (Pydantic Schemas)

定义所有 API 请求和响应的数据格式，
遵循 IEEE 电力系统数据交换标准。

作者: 毕业设计项目
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator


# ============================================================================
# 请求模型
# ============================================================================

class WeatherDataPoint(BaseModel):
    """单个气象数据点"""
    timestamp: datetime = Field(..., description="时间戳 (ISO 8601)")
    temperature_2m: float = Field(..., ge=-60, le=60, description="2m温度 (°C)")
    dew_point_2m: float = Field(..., ge=-60, le=50, description="2m露点温度 (°C)")
    relative_humidity_2m: Optional[float] = Field(None, ge=0, le=100, description="相对湿度 (%)")
    wind_speed_10m: Optional[float] = Field(None, ge=0, le=100, description="10m风速 (m/s)")
    cloud_cover: Optional[float] = Field(None, ge=0, le=100, description="云量 (%)")
    shortwave_radiation: Optional[float] = Field(None, ge=0, le=1500, description="短波辐射 (W/m²)")

    @validator('dew_point_2m')
    def dew_point_not_above_temp(cls, v, values):
        """露点不应高于气温"""
        if 'temperature_2m' in values and v > values['temperature_2m']:
            raise ValueError('露点温度不能高于气温')
        return v


class HistoricalLoadPoint(BaseModel):
    """历史负载数据点"""
    timestamp: datetime = Field(..., description="时间戳")
    system_load: float = Field(..., ge=0, le=50000, description="系统负荷 (MW)")


class LoadPredictionRequest(BaseModel):
    """负荷预测请求"""
    weather_data: Optional[List[WeatherDataPoint]] = Field(
        None, description="气象数据（可选，不提供则自动获取）"
    )
    historical_load: Optional[List[HistoricalLoadPoint]] = Field(
        None, description="历史负载数据（可选）"
    )
    forecast_hours: int = Field(24, ge=1, le=24, description="预测小时数")

    class Config:
        json_schema_extra = {
            "example": {
                "weather_data": [
                    {
                        "timestamp": "2025-07-23T14:00:00",
                        "temperature_2m": 28.5,
                        "dew_point_2m": 18.0,
                        "relative_humidity_2m": 65,
                        "wind_speed_10m": 5.2,
                        "cloud_cover": 30,
                        "shortwave_radiation": 650
                    }
                ],
                "forecast_hours": 24
            }
        }


class BatchPredictionItem(BaseModel):
    """批量预测中的单个请求项"""
    weather_data: List[WeatherDataPoint] = Field(..., description="气象数据")
    historical_load: Optional[List[HistoricalLoadPoint]] = Field(None)


class BatchPredictionRequest(BaseModel):
    """批量预测请求"""
    requests: List[BatchPredictionItem] = Field(
        ..., min_length=1, max_length=10, description="批量预测请求列表 (最多10个)"
    )


# ============================================================================
# 响应模型
# ============================================================================

class HourlyPrediction(BaseModel):
    """每小时预测结果"""
    hour: int = Field(..., description="预测小时 (0-23)")
    timestamp: str = Field(..., description="预测时间戳")
    load_forecast_mw: float = Field(..., description="负荷预测 (MW)")
    pv_estimation_mw: float = Field(..., description="光伏发电估算 (MW)")
    net_load_mw: float = Field(..., description="净负荷 = 负荷 - 光伏 (MW)")

    class Config:
        json_schema_extra = {
            "example": {
                "hour": 0,
                "timestamp": "2025-07-23T15:00:00",
                "load_forecast_mw": 15200.5,
                "pv_estimation_mw": 320.0,
                "net_load_mw": 14880.5
            }
        }


class ModelInfoResponse(BaseModel):
    """模型信息"""
    name: str
    weight: float
    num_params: int
    loaded: bool


class LoadPredictionResponse(BaseModel):
    """负荷预测响应"""
    status: str = Field(..., description="处理状态: success/error")
    predictions: List[HourlyPrediction] = Field(..., description="24小时预测结果")
    model_info: List[ModelInfoResponse] = Field(..., description="模型信息")
    ensemble_weights: Dict[str, float] = Field(..., description="集成权重")
    inference_time_ms: float = Field(..., description="推理耗时 (ms)")
    data_source: str = Field("api", description="数据来源: api/provided")
    timestamp: str = Field(..., description="响应生成时间")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "predictions": [
                    {
                        "hour": 0,
                        "timestamp": "2025-07-23T15:00:00",
                        "load_forecast_mw": 15200.5,
                        "pv_estimation_mw": 320.0,
                        "net_load_mw": 14880.5
                    }
                ],
                "model_info": [
                    {"name": "EnhancedLSTM", "weight": 0.35, "num_params": 2000000, "loaded": True}
                ],
                "ensemble_weights": {"EnhancedLSTM": 0.35, "BiGRU": 0.30},
                "inference_time_ms": 150.5,
                "data_source": "api",
                "timestamp": "2025-07-23T14:00:00"
            }
        }


class BatchPredictionResponse(BaseModel):
    """批量预测响应"""
    status: str
    results: List[LoadPredictionResponse]
    total_time_ms: float
    timestamp: str


class WeatherStationData(BaseModel):
    """气象站点数据"""
    name: str
    latitude: float
    longitude: float
    temperature_2m: float
    dew_point_2m: float
    relative_humidity_2m: Optional[float]
    wind_speed_10m: Optional[float]
    cloud_cover: Optional[float]
    shortwave_radiation: Optional[float]


class WeatherResponse(BaseModel):
    """当前气象数据响应"""
    status: str
    timestamp: str
    stations: List[WeatherStationData]
    regional_average: Optional[Dict[str, float]] = Field(
        None, description="区域平均气象数据"
    )


class SystemStatusResponse(BaseModel):
    """系统状态响应"""
    status: str = Field(..., description="系统状态: healthy/degraded/error")
    models_loaded: int = Field(..., description="已加载模型数")
    device: str = Field(..., description="推理设备")
    total_inferences: int = Field(..., description="总推理次数")
    average_inference_time_ms: float = Field(..., description="平均推理时间")
    ensemble_weights: Dict[str, float]
    uptime_seconds: float = Field(..., description="运行时间(秒)")
    memory_usage_mb: Optional[float] = Field(None, description="内存使用(MB)")
    timestamp: str


class ErrorResponse(BaseModel):
    """错误响应"""
    status: str = "error"
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误详情")
    timestamp: str
