"""
特征工程服务

接收气象数据，生成38维特征并归一化，
提供 HTTP API 供 API Gateway 调用。

端点:
    POST /generate     - 生成特征
    GET  /health       - 健康检查
    GET  /metrics       - 指标
"""

import os
import sys
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from realtime_api.feature_generator import FeatureGenerator
from realtime_api.normalization_adapter import NormalizationAdapter
from realtime_api.weather_validator import WeatherDataValidator

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("feature-engine")

# ============================================================================
# 全局实例
# ============================================================================
feature_gen: Optional[FeatureGenerator] = None
normalizer: Optional[NormalizationAdapter] = None
validator: Optional[WeatherDataValidator] = None

# ============================================================================
# 数据模型
# ============================================================================
class WeatherDataItem(BaseModel):
    timestamp: str
    temperature_2m: float
    dew_point_2m: float
    relative_humidity_2m: Optional[float] = None
    wind_speed_10m: Optional[float] = None
    cloud_cover: Optional[float] = None
    shortwave_radiation: Optional[float] = None

class FeatureRequest(BaseModel):
    weather_data: list
    historical_load: Optional[list] = None

class FeatureResponse(BaseModel):
    status: str
    features: list
    sequence: list  # (1, 168, 38)
    n_features: int
    timestamp: str

# ============================================================================
# FastAPI
# ============================================================================
app = FastAPI(title="特征工程服务", version="1.0.0")

@app.on_event("startup")
async def startup():
    global feature_gen, normalizer, validator
    logger.info("特征工程服务启动...")
    feature_gen = FeatureGenerator()
    normalizer = NormalizationAdapter()
    validator = WeatherDataValidator()
    logger.info("✅ 初始化完成")

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "feature-engine",
        "timestamp": datetime.now().isoformat(),
    }

@app.post("/generate", response_model=FeatureResponse)
async def generate_features(request: FeatureRequest):
    """生成特征"""
    try:
        df = pd.DataFrame(request.weather_data)
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        # 验证
        clean_df, _, _ = validator.validate(df)

        # 特征生成
        features = feature_gen.generate(clean_df)

        # 归一化
        normalized = normalizer.transform_features(features)

        # 序列
        seq_df = pd.DataFrame(normalized, columns=features.columns)
        sequence = feature_gen.build_sequence(seq_df, lookback=168)

        return FeatureResponse(
            status="success",
            features=normalized.tolist(),
            sequence=sequence.tolist(),
            n_features=normalized.shape[1],
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"特征生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8600, log_level="info")
