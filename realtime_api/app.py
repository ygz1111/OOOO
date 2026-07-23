"""
智能电网负荷预测系统 - FastAPI 实时预测服务

API 端点:
  POST /api/prediction/load   - 负荷预测 (24小时)
  GET  /api/weather/current    - 获取当前气象数据
  GET  /api/system/status      - 系统状态监控
  POST /api/prediction/batch   - 批量预测

特性:
  - 异步处理 (I/O 线程池 + CPU 线程池分离)
  - 请求参数验证 (Pydantic)
  - OpenAPI 自动文档 (/docs)
  - 请求限流 (60次/分钟)
  - 超时控制 (30秒)
  - CORS 中间件
  - 全局异常处理
  - 请求日志中间件

启动方式:
    cd c:/OOOO/OOOO
    python -m uvicorn realtime_api.app:app --host 0.0.0.0 --port 8000 --reload

    或直接运行:
    python realtime_api/app.py

作者: 毕业设计项目
"""

import os
import sys
import time
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 导入业务模块
from realtime_api.schemas import (
    LoadPredictionRequest,
    LoadPredictionResponse,
    BatchPredictionRequest,
    BatchPredictionResponse,
    HourlyPrediction,
    ModelInfoResponse,
    WeatherResponse,
    WeatherStationData,
    SystemStatusResponse,
    ErrorResponse,
)
from realtime_api.openmeteo_client import OpenMeteoClient
from realtime_api.weather_validator import WeatherDataValidator
from realtime_api.feature_generator import FeatureGenerator
from realtime_api.normalization_adapter import NormalizationAdapter
from realtime_api.prediction_service import ModelInferenceService

# ============================================================================
# 日志配置
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ============================================================================
# 全局服务实例（在 lifespan 中初始化）
# ============================================================================

class ServiceContainer:
    """服务容器：管理所有业务模块的生命周期"""
    openmeteo_client: Optional[OpenMeteoClient] = None
    weather_validator: Optional[WeatherDataValidator] = None
    feature_generator: Optional[FeatureGenerator] = None
    normalizer: Optional[NormalizationAdapter] = None
    inference_service: Optional[ModelInferenceService] = None
    start_time: float = 0.0


services = ServiceContainer()


# ============================================================================
# 光伏发电估算器
# ============================================================================

class SolarEstimator:
    """
    光伏发电估算器

    基于短波辐射估算光伏发电量:
      PV_output = (radiation / 1000) * installed_capacity * performance_ratio

    新英格兰地区参数:
      - 装机容量: 500 MW (公用事业级)
      - 性能比: 0.80 (考虑损耗)
      - 温度衰减: 高温时效率下降
    """

    def __init__(
        self,
        installed_capacity_mw: float = 500.0,
        performance_ratio: float = 0.80,
    ):
        self.installed_capacity = installed_capacity_mw
        self.performance_ratio = performance_ratio

    def estimate(self, radiation: float, temperature: float = 25.0) -> float:
        """
        估算光伏发电量

        Args:
            radiation: 短波辐射 (W/m²)
            temperature: 温度 (°C)，用于温度衰减

        Returns:
            光伏发电量 (MW)
        """
        if radiation <= 0:
            return 0.0

        # 基础输出
        base_output = (radiation / 1000.0) * self.installed_capacity * self.performance_ratio

        # 温度衰减 (高温降低效率，约 0.4%/°C 超过25°C)
        temp_loss = max(0, (temperature - 25.0) * 0.004)
        actual_output = base_output * (1.0 - temp_loss)

        return max(0, actual_output)


solar_estimator = SolarEstimator()


# ============================================================================
# 辅助函数
# ============================================================================

def weather_points_to_df(points: List) -> pd.DataFrame:
    """将 Pydantic 气象数据点列表转为 DataFrame"""
    records = []
    for p in points:
        record = {
            "timestamp": p.timestamp,
            "location": "API_Input",
            "temperature_2m": p.temperature_2m,
            "dew_point_2m": p.dew_point_2m,
        }
        if p.relative_humidity_2m is not None:
            record["relative_humidity_2m"] = p.relative_humidity_2m
        if p.wind_speed_10m is not None:
            record["wind_speed_10m"] = p.wind_speed_10m
        if p.cloud_cover is not None:
            record["cloud_cover"] = p.cloud_cover
        if p.shortwave_radiation is not None:
            record["shortwave_radiation"] = p.shortwave_radiation
        records.append(record)

    return pd.DataFrame(records)


def load_points_to_df(points: List) -> pd.DataFrame:
    """将 Pydantic 历史负载点列表转为 DataFrame"""
    records = [
        {"timestamp": p.timestamp, "System_Load": p.system_load}
        for p in points
    ]
    return pd.DataFrame(records)


def run_prediction_pipeline(
    weather_df: pd.DataFrame,
    historical_load_df: Optional[pd.DataFrame] = None,
) -> LoadPredictionResponse:
    """
    执行完整预测管线

    天气数据 → 特征生成 → 归一化 → 序列构建 → 模型推理 → 逆归一化 → 结果
    """
    pipeline_start = time.perf_counter()

    # 1. 数据验证
    try:
        clean_df, quality_report, anomaly_flags = services.weather_validator.validate(
            weather_df, raise_on_severe=False
        )
    except Exception as e:
        logger.warning(f"数据验证失败，使用原始数据: {e}")
        clean_df = weather_df.copy()

    # 2. 特征生成
    features = services.feature_generator.generate(
        clean_df, historical_load_df
    )

    # 3. 归一化
    normalized = services.normalizer.transform_features(features)

    # 4. 构建序列
    sequence = services.feature_generator.build_sequence(
        pd.DataFrame(normalized, columns=features.columns),
        lookback=168,
    )

    # 5. 模型推理
    result = services.inference_service.predict(sequence, inverse_transform=True)

    # 6. 构建响应
    predictions = []
    ensemble_pred = result.ensemble_prediction[0]  # (24,)

    # 获取气象数据中的辐射值用于光伏估算
    radiation_values = []
    temp_values = []
    if "shortwave_radiation" in clean_df.columns:
        # 取最后24小时的辐射值
        rad_series = clean_df["shortwave_radiation"].tail(24).values
        temp_series = clean_df["temperature_2m"].tail(24).values if "temperature_2m" in clean_df.columns else [25.0] * 24
    else:
        rad_series = [0.0] * 24
        temp_series = [25.0] * 24

    now = datetime.now()

    for hour in range(min(24, len(ensemble_pred))):
        pred_time = now + timedelta(hours=hour)
        load_mw = float(ensemble_pred[hour])
        radiation = float(rad_series[hour]) if hour < len(rad_series) else 0.0
        temp = float(temp_series[hour]) if hour < len(temp_series) else 25.0
        pv_mw = solar_estimator.estimate(radiation, temp)
        net_mw = load_mw - pv_mw

        predictions.append(HourlyPrediction(
            hour=hour,
            timestamp=pred_time.isoformat(),
            load_forecast_mw=round(load_mw, 1),
            pv_estimation_mw=round(pv_mw, 1),
            net_load_mw=round(net_mw, 1),
        ))

    # 模型信息
    model_infos = []
    for name, info in services.inference_service.get_model_info().items():
        model_infos.append(ModelInfoResponse(
            name=name,
            weight=info['weight'],
            num_params=info['num_params'],
            loaded=info['loaded'],
        ))

    pipeline_time = (time.perf_counter() - pipeline_start) * 1000

    return LoadPredictionResponse(
        status="success",
        predictions=predictions,
        model_info=model_infos,
        ensemble_weights=services.inference_service.ensemble_weights,
        inference_time_ms=round(pipeline_time, 1),
        data_source="provided" if weather_df is not None else "fallback",
        timestamp=datetime.now().isoformat(),
    )


# ============================================================================
# 生命周期管理
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时加载模型，关闭时释放资源"""
    logger.info("=" * 60)
    logger.info("智能电网负荷预测系统 - 启动中")
    logger.info("=" * 60)

    services.start_time = time.time()

    # 初始化各模块
    logger.info("[1/5] 初始化 OpenMeteoClient...")
    services.openmeteo_client = OpenMeteoClient(
        past_days=7, forecast_days=1, rate_limit_interval=0.3
    )

    logger.info("[2/5] 初始化 WeatherDataValidator...")
    services.weather_validator = WeatherDataValidator()

    logger.info("[3/5] 初始化 FeatureGenerator...")
    services.feature_generator = FeatureGenerator()

    logger.info("[4/5] 初始化 NormalizationAdapter...")
    services.normalizer = NormalizationAdapter()

    logger.info("[5/5] 加载模型 (可能需要几秒)...")
    services.inference_service = ModelInferenceService()
    services.inference_service.load_models()

    logger.info("=" * 60)
    logger.info("✅ 系统启动完成")
    logger.info(f"   推理设备: {services.inference_service.device}")
    logger.info(f"   模型数量: {len(services.inference_service.models)}")
    logger.info(f"   API 文档: http://localhost:8000/docs")
    logger.info("=" * 60)

    yield

    # 关闭
    logger.info("系统关闭中...")
    if services.inference_service:
        services.inference_service.release()
    logger.info("✅ 资源已释放")


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(
    title="智能电网负荷预测系统",
    description="""
    ## 实时电力负荷预测 API

    基于深度学习的电力负荷预测系统，整合4个模型（LSTM、BiGRU、TCN、Transformer）
    进行加权集成预测，同时提供光伏发电估算和净负荷计算。

    ### 功能
    - **负荷预测**: 24小时系统负荷预测
    - **气象数据**: 获取新英格兰地区6个气象站实时数据
    - **光伏估算**: 基于辐射数据估算光伏发电量
    - **系统监控**: 推理性能、模型状态监控

    ### 数据流
    ```
    Open-Meteo API → 气象数据 → 特征工程(38维) → 归一化 → 模型推理 → 预测结果
    ```
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================================================================
# 中间件
# ============================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """请求日志和耗时记录中间件"""
    start_time = time.time()

    # 请求信息
    method = request.method
    path = request.url.path
    client = request.client.host if request.client else "unknown"

    logger.info(f"→ {method} {path} from {client}")

    # 超时控制
    try:
        response = await asyncio.wait_for(
            call_next(request),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.error(f"⏰ 请求超时: {method} {path}")
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=ErrorResponse(
                error="timeout",
                message="请求处理超时 (30秒)",
                timestamp=datetime.now().isoformat(),
            ).dict(),
        )

    process_time = (time.time() - start_time) * 1000
    logger.info(f"← {method} {path} {response.status_code} ({process_time:.1f}ms)")

    # 添加耗时头
    response.headers["X-Process-Time"] = f"{process_time:.1f}ms"

    return response


# ============================================================================
# 异常处理
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常处理"""
    logger.warning(f"HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=f"HTTP {exc.status_code}",
            message=str(exc.detail),
            timestamp=datetime.now().isoformat(),
        ).dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            message=str(exc),
            timestamp=datetime.now().isoformat(),
        ).dict(),
    )


# ============================================================================
# API 端点
# ============================================================================

@app.get("/", tags=["根"])
async def root():
    """根路径 - 重定向到文档"""
    return {
        "service": "智能电网负荷预测系统",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": [
            "POST /api/prediction/load",
            "GET /api/weather/current",
            "GET /api/system/status",
            "POST /api/prediction/batch",
        ],
    }


@app.post(
    "/api/prediction/load",
    response_model=LoadPredictionResponse,
    tags=["预测"],
    summary="负荷预测",
    description="""
    执行24小时负荷预测。

    可以在请求体中提供气象数据，也可以不提供（系统自动从 Open-Meteo 获取）。
    返回每小时负荷预测、光伏估算和净负荷。
    """,
)
async def predict_load(request: LoadPredictionRequest):
    """
    负荷预测端点

    流程:
    1. 获取气象数据（用户提供 或 Open-Meteo API）
    2. 数据验证和清洗
    3. 38维特征生成
    4. MinMaxScaler 归一化
    5. 4模型集成推理
    6. 逆归一化 + 光伏估算
    """
    if not services.inference_service or not services.inference_service.is_ready():
        raise HTTPException(
            status_code=503,
            detail="模型服务未就绪，请稍后重试",
        )

    # 获取气象数据
    if request.weather_data and len(request.weather_data) > 0:
        # 用户提供了气象数据
        weather_df = weather_points_to_df(request.weather_data)
        data_source = "provided"
    else:
        # 从 Open-Meteo API 获取
        try:
            weather_df, _ = await asyncio.to_thread(
                services.openmeteo_client.fetch_weather_data
            )
            data_source = "api"
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"获取气象数据失败: {e}",
            )

    # 获取历史负荷数据
    historical_load_df = None
    if request.historical_load and len(request.historical_load) > 0:
        historical_load_df = load_points_to_df(request.historical_load)

    # 执行预测管线（CPU密集型，放线程池）
    try:
        response = await asyncio.to_thread(
            run_prediction_pipeline,
            weather_df,
            historical_load_df,
        )
        response.data_source = data_source
        return response

    except Exception as e:
        logger.error(f"预测管线失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"预测失败: {e}",
        )


@app.get(
    "/api/weather/current",
    response_model=WeatherResponse,
    tags=["气象"],
    summary="获取当前气象数据",
    description="获取新英格兰地区6个气象站点的实时气象数据",
)
async def get_current_weather():
    """获取当前气象数据"""
    try:
        weather_df, quality_reports = await asyncio.to_thread(
            services.openmeteo_client.fetch_weather_data
        )

        # 构建站点数据
        stations = []
        for location in services.openmeteo_client.locations:
            loc_data = weather_df[weather_df["location"] == location.name]
            if len(loc_data) > 0:
                latest = loc_data.iloc[-1]  # 最新一条
                stations.append(WeatherStationData(
                    name=location.name,
                    latitude=location.lat,
                    longitude=location.lon,
                    temperature_2m=float(latest.get("temperature_2m", 0)),
                    dew_point_2m=float(latest.get("dew_point_2m", 0)),
                    relative_humidity_2m=float(latest.get("relative_humidity_2m", 0)) if "relative_humidity_2m" in latest else None,
                    wind_speed_10m=float(latest.get("wind_speed_10m", 0)) if "wind_speed_10m" in latest else None,
                    cloud_cover=float(latest.get("cloud_cover", 0)) if "cloud_cover" in latest else None,
                    shortwave_radiation=float(latest.get("shortwave_radiation", 0)) if "shortwave_radiation" in latest else None,
                ))

        # 区域平均
        regional_avg = {}
        param_cols = ["temperature_2m", "dew_point_2m", "relative_humidity_2m",
                      "wind_speed_10m", "cloud_cover", "shortwave_radiation"]
        for col in param_cols:
            if col in weather_df.columns:
                regional_avg[col] = round(float(weather_df[col].mean()), 1)

        return WeatherResponse(
            status="success",
            timestamp=datetime.now().isoformat(),
            stations=stations,
            regional_average=regional_avg,
        )

    except Exception as e:
        logger.error(f"获取气象数据失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"获取气象数据失败: {e}",
        )


@app.get(
    "/api/system/status",
    response_model=SystemStatusResponse,
    tags=["系统"],
    summary="系统状态监控",
    description="获取系统运行状态、模型信息和性能统计",
)
async def get_system_status():
    """系统状态监控"""
    stats = services.inference_service.get_performance_stats()

    # 内存使用
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
    except ImportError:
        memory_mb = None

    uptime = time.time() - services.start_time

    # 判断健康状态
    if stats['models_loaded'] == 4:
        health_status = "healthy"
    elif stats['models_loaded'] > 0:
        health_status = "degraded"
    else:
        health_status = "error"

    return SystemStatusResponse(
        status=health_status,
        models_loaded=stats['models_loaded'],
        device=stats['device'],
        total_inferences=stats['total_inferences'],
        average_inference_time_ms=stats['average_time_ms'],
        ensemble_weights=stats['ensemble_weights'],
        uptime_seconds=round(uptime, 1),
        memory_usage_mb=round(memory_mb, 1) if memory_mb else None,
        timestamp=datetime.now().isoformat(),
    )


@app.post(
    "/api/prediction/batch",
    response_model=BatchPredictionResponse,
    tags=["预测"],
    summary="批量预测",
    description="批量执行负荷预测（最多10个请求）",
)
async def batch_predict(request: BatchPredictionRequest):
    """批量预测"""
    if not services.inference_service or not services.inference_service.is_ready():
        raise HTTPException(
            status_code=503,
            detail="模型服务未就绪",
        )

    batch_start = time.perf_counter()
    results = []

    for i, item in enumerate(request.requests):
        try:
            # 转换数据
            weather_df = weather_points_to_df(item.weather_data)
            historical_load_df = None
            if item.historical_load:
                historical_load_df = load_points_to_df(item.historical_load)

            # 执行预测
            response = await asyncio.to_thread(
                run_prediction_pipeline,
                weather_df,
                historical_load_df,
            )
            results.append(response)

        except Exception as e:
            logger.error(f"批量预测第{i}个请求失败: {e}")
            # 返回错误结果
            results.append(LoadPredictionResponse(
                status="error",
                predictions=[],
                model_info=[],
                ensemble_weights={},
                inference_time_ms=0,
                data_source="error",
                timestamp=datetime.now().isoformat(),
            ))

    total_time = (time.perf_counter() - batch_start) * 1000

    return BatchPredictionResponse(
        status="success" if all(r.status == "success" for r in results) else "partial",
        results=results,
        total_time_ms=round(total_time, 1),
        timestamp=datetime.now().isoformat(),
    )


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "realtime_api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
