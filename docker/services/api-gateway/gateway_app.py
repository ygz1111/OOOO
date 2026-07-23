"""
API Gateway - 智能电网负荷预测系统

整合气象采集、特征工程、模型推理和净负荷计算，
提供统一的对外 API。

通过 HTTP 调用下游微服务:
  - weather-collector:9090  (气象数据)
  - feature-engine:8600     (特征工程)
  - model-inference:8500    (模型推理)

启动方式:
    python gateway_app.py
"""

import os
import sys
import time
import logging
import asyncio
import httpx
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from realtime_api.schemas import (
    LoadPredictionRequest,
    WeatherDataPoint,
    HourlyPrediction,
)
from realtime_api.pv_estimator import PVGenerationEstimator
from realtime_api.net_load_calculator import NetLoadCalculator

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("api-gateway")

# ============================================================================
# 微服务地址
# ============================================================================
WEATHER_SERVICE = os.getenv("WEATHER_SERVICE_URL", "http://weather-collector:9090")
FEATURE_SERVICE = os.getenv("FEATURE_SERVICE_URL", "http://feature-engine:8600")
INFERENCE_SERVICE = os.getenv("INFERENCE_SERVICE_URL", "http://model-inference:8500")

# ============================================================================
# 光伏和净负荷计算器
# ============================================================================
pv_estimator = PVGenerationEstimator()
net_load_calc = NetLoadCalculator()

# 服务启动时间
START_TIME = time.time()

# ============================================================================
# 中间件 + 异常
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("智能电网负荷预测系统 - API Gateway 启动")
    logger.info(f"  气象服务: {WEATHER_SERVICE}")
    logger.info(f"  特征服务: {FEATURE_SERVICE}")
    logger.info(f"  推理服务: {INFERENCE_SERVICE}")
    logger.info("=" * 60)
    yield
    logger.info("API Gateway 关闭")


app = FastAPI(
    title="智能电网负荷预测系统 API",
    description="""
    ## 实时电力负荷预测 API Gateway

    整合气象采集、特征工程、模型推理和净负荷计算，
    提供24小时负荷预测 + 光伏估算 + 净负荷 + 调度建议。
    """,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求日志 + 超时
@app.middleware("http")
async def request_middleware(request: Request, call_next):
    start = time.time()
    method, path = request.method, request.url.path
    client = request.client.host if request.client else "unknown"
    logger.info(f"→ {method} {path} from {client}")
    try:
        response = await asyncio.wait_for(call_next(request), timeout=30.0)
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"error": "timeout"})
    elapsed = (time.time() - start) * 1000
    response.headers["X-Process-Time"] = f"{elapsed:.1f}ms"
    logger.info(f"← {method} {path} {response.status_code} ({elapsed:.1f}ms)")
    return response


@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={
        "status": "error",
        "message": str(exc),
        "timestamp": datetime.now().isoformat(),
    })


# ============================================================================
# 辅助函数
# ============================================================================
async def call_service(url: str, method: str = "GET", **kwargs) -> dict:
    """调用下游微服务"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        if method == "GET":
            resp = await client.get(url, **kwargs)
        else:
            resp = await client.post(url, **kwargs)
        resp.raise_for_status()
        return resp.json()


# ============================================================================
# API 端点
# ============================================================================

@app.get("/")
async def root():
    return {
        "service": "智能电网负荷预测系统",
        "version": "2.0.0",
        "docs": "/docs",
        "endpoints": [
            "POST /api/prediction/load",
            "GET  /api/weather/current",
            "GET  /api/system/status",
            "POST /api/prediction/batch",
            "GET  /api/netload/analyze",
        ],
    }


@app.get("/api/system/status")
async def system_status():
    """系统状态 - 检查所有微服务"""
    services = {}
    checks = {
        "weather-collector": f"{WEATHER_SERVICE}/health",
        "feature-engine": f"{FEATURE_SERVICE}/health",
        "model-inference": f"{INFERENCE_SERVICE}/health",
    }

    for name, url in checks.items():
        try:
            data = await call_service(url)
            services[name] = data
        except Exception as e:
            services[name] = {"status": "error", "error": str(e)}

    all_healthy = all(
        s.get("status") == "healthy" for s in services.values()
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": services,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/prediction/load")
async def predict_load(request: LoadPredictionRequest):
    """
    负荷预测 - 完整管线

    1. 获取/使用气象数据
    2. 调用特征工程服务
    3. 调用推理服务
    4. 光伏估算 + 净负荷计算
    """
    pipeline_start = time.perf_counter()

    # 1. 气象数据
    if request.weather_data and len(request.weather_data) > 0:
        weather_data = [p.model_dump(mode='json') for p in request.weather_data]
        data_source = "provided"
    else:
        # 从气象服务获取
        try:
            weather_resp = await call_service(f"{WEATHER_SERVICE}/weather/latest")
            weather_data = weather_resp.get("data", [])
            data_source = "api"
        except Exception as e:
            raise HTTPException(502, f"获取气象数据失败: {e}")

    # 2. 特征工程
    try:
        feat_resp = await call_service(
            f"{FEATURE_SERVICE}/generate",
            method="POST",
            json={
                "weather_data": weather_data,
                "historical_load": None,
            },
        )
        sequence = feat_resp["sequence"]
        n_features = feat_resp["n_features"]
    except Exception as e:
        raise HTTPException(502, f"特征生成失败: {e}")

    # 3. 模型推理
    try:
        inf_resp = await call_service(
            f"{INFERENCE_SERVICE}/predict",
            method="POST",
            json={
                "features": sequence[0] if len(sequence) > 0 else [],
                "batch_size": 1,
                "seq_len": 168,
                "n_features": n_features,
                "inverse_transform": True,
            },
        )
        predictions = inf_resp["ensemble_prediction"]
    except Exception as e:
        raise HTTPException(502, f"推理失败: {e}")

    # 4. 光伏估算
    weather_df = pd.DataFrame(weather_data)
    if "shortwave_radiation" not in weather_df.columns:
        weather_df["shortwave_radiation"] = 0
    if "cloud_cover" not in weather_df.columns:
        weather_df["cloud_cover"] = 0
    if "temperature_2m" not in weather_df.columns:
        weather_df["temperature_2m"] = 20

    pv_result = pv_estimator.estimate_24h(weather_df)
    pv_values = pv_result.hourly_generation_mw

    # 5. 净负荷计算
    load_array = np.array(predictions[:24])
    pv_array = np.array(pv_values[:24])
    net_result = net_load_calc.calculate(load_array, pv_array)

    # 6. 构建响应
    hourly = []
    now = datetime.now()
    for i in range(min(24, len(predictions))):
        hourly.append({
            "hour": i,
            "timestamp": (now + timedelta(hours=i)).isoformat(),
            "load_forecast_mw": round(float(load_array[i]) if i < len(load_array) else 0, 1),
            "pv_estimation_mw": round(float(pv_array[i]) if i < len(pv_array) else 0, 1),
            "net_load_mw": round(float(net_result.hourly[i].adjusted_net_load_mw), 1),
            "storage_charge_mw": round(float(net_result.hourly[i].storage_charge_mw), 1),
            "storage_discharge_mw": round(float(net_result.hourly[i].storage_discharge_mw), 1),
            "soc_percent": round(float(net_result.hourly[i].soc_percent), 1),
            "is_peak": net_result.hourly[i].is_peak,
            "is_valley": net_result.hourly[i].is_valley,
        })

    pipeline_time = (time.perf_counter() - pipeline_start) * 1000

    return {
        "status": "success",
        "predictions": hourly,
        "summary": {
            "total_load_mwh": round(net_result.total_net_load_mwh, 1),
            "total_pv_mwh": round(float(pv_array.sum()), 1),
            "peak_load_mw": round(net_result.peak_load_mw, 1),
            "valley_load_mw": round(net_result.valley_load_mw, 1),
            "total_generation_cost_usd": round(net_result.total_generation_cost_usd, 1),
            "storage_revenue_usd": round(net_result.storage_revenue_usd, 1),
            "total_curtailed_mwh": round(net_result.total_curtailed_mwh, 1),
        },
        "dispatch_actions": net_result.dispatch_actions,
        "model_info": inf_resp.get("individual_predictions", {}),
        "inference_time_ms": inf_resp.get("inference_time_ms", 0),
        "pipeline_time_ms": round(pipeline_time, 1),
        "data_source": data_source,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/weather/current")
async def get_weather():
    """获取当前气象数据"""
    try:
        data = await call_service(f"{WEATHER_SERVICE}/weather/latest")
        return data
    except Exception as e:
        raise HTTPException(502, f"获取气象数据失败: {e}")


@app.post("/api/prediction/batch")
async def batch_predict(request: dict):
    """批量预测"""
    items = request.get("requests", [])
    results = []

    for item in items[:10]:  # 最多10个
        try:
            req = LoadPredictionRequest(**item)
            # 复用单次预测逻辑（简化版）
            result = await predict_load(req)
            results.append(result)
        except Exception as e:
            results.append({"status": "error", "error": str(e)})

    return {
        "status": "success",
        "results": results,
        "total_time_ms": 0,
        "timestamp": datetime.now().isoformat(),
    }


# ============================================================================
# 启动
# ============================================================================
if __name__ == "__main__":
    uvicorn.run(
        "gateway_app:app",
        host="0.0.0.0",
        port=8000,
        workers=int(os.getenv("WORKERS", "2")),
        log_level="info",
    )
