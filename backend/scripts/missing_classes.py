# 定义缺失的schema类
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime,date


class ModelInfoResponse(BaseModel):
    """模型信息响应"""
    model_name: str = Field(..., description="模型名称")
    model_path: str = Field(..., description="模型路径")
    loaded: bool = Field(..., description="是否已加载")
    device: str = Field(..., description="运行设备")
    last_updated: Optional[str] = Field(None, description="最后更新时间")
    performance_metrics: Optional[Dict[str, float]] = Field(None, description="性能指标")


class WeatherStationData(BaseModel):
    """气象站点数据"""
    station_id: int = Field(..., description="站点ID")
    name: str = Field(..., description="站点名称")
    latitude: float = Field(..., description="纬度")
    longitude: float = Field(..., description="经度")
    temperature: float = Field(..., description="温度 (°C)")
    humidity: float = Field(..., description="湿度 (%)")
    wind_speed: float = Field(..., description="风速 (m/s)")
    radiation: float = Field(..., description="短波辐射 (W/m²)")
    cloud_cover: float = Field(..., description="云量 (%)")
    timestamp: str = Field(..., description="数据采集时间")


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
    device: str = Field(..., description="运行设备")
    total_inferences: int = Field(..., description="总推理次数") 
    average_inference_time_ms: float = Field(..., description="平均推理时间")
    ensemble_weights: Dict[str, float] = Field(..., description="集成权重")
    uptime_seconds: float = Field(..., description="运行时间 (秒)")
    memory_usage_mb: Optional[float] = Field(None, description="内存使用 (MB)")
    timestamp: str = Field(..., description="响应时间")


# 导出类
__all__ = [
    'ModelInfoResponse',
    'WeatherStationData', 
    'WeatherResponse',
    'SystemStatusResponse'
]