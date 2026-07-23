"""
模型推理服务

独立的模型推理微服务，提供 HTTP API 供其他服务调用。
加载4个PyTorch模型，提供加权集成预测。

启动方式:
    python inference_server.py

端点:
    POST /predict      - 批量推理
    GET  /health       - 健康检查
    GET  /model-info   - 模型信息
    GET  /metrics       - Prometheus 指标
"""

import os
import sys
import time
import logging
import numpy as np
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from realtime_api.prediction_service import ModelInferenceService
from realtime_api.normalization_adapter import NormalizationAdapter

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("model-inference")

# ============================================================================
# 全局实例
# ============================================================================
inference_service: Optional[ModelInferenceService] = None
normalizer: Optional[NormalizationAdapter] = None

# ============================================================================
# 数据模型
# ============================================================================
class PredictRequest(BaseModel):
    """推理请求"""
    features: list  # (batch, seq_len, 38) 展平
    batch_size: int = 1
    seq_len: int = 168
    n_features: int = 38
    inverse_transform: bool = True


class PredictResponse(BaseModel):
    """推理响应"""
    status: str
    ensemble_prediction: list
    individual_predictions: dict
    inference_time_ms: float
    timestamp: str


# ============================================================================
# FastAPI 应用
# ============================================================================
app = FastAPI(
    title="模型推理服务",
    description="4模型集成推理引擎",
    version="1.0.0",
)


@app.on_event("startup")
async def startup():
    """加载模型"""
    global inference_service, normalizer

    logger.info("=" * 60)
    logger.info("模型推理服务启动中...")
    logger.info("=" * 60)

    # 加载归一化器
    normalizer = NormalizationAdapter()

    # 加载模型
    model_dir = os.getenv("MODEL_DIR", "/app/outputs")
    inference_service = ModelInferenceService()
    inference_service.load_models()

    logger.info(f"✅ 模型加载完成: {len(inference_service.models)} 个")
    logger.info(f"   设备: {inference_service.device}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    """释放资源"""
    global inference_service
    if inference_service:
        inference_service.release()
    logger.info("模型资源已释放")


@app.get("/health")
async def health():
    """健康检查"""
    ready = inference_service is not None and inference_service.is_ready()
    return {
        "status": "healthy" if ready else "starting",
        "service": "model-inference",
        "models_loaded": len(inference_service.models) if inference_service else 0,
        "device": inference_service.device if inference_service else "unknown",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/model-info")
async def model_info():
    """模型信息"""
    if not inference_service or not inference_service.is_ready():
        raise HTTPException(status_code=503, detail="模型未就绪")
    return inference_service.get_model_info()


@app.get("/metrics")
async def metrics():
    """Prometheus 指标"""
    if inference_service:
        stats = inference_service.get_performance_stats()
        return stats
    return {"error": "service not ready"}


@app.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """推理端点"""
    if not inference_service or not inference_service.is_ready():
        raise HTTPException(status_code=503, detail="模型未就绪")

    try:
        # 重塑输入
        arr = np.array(request.features, dtype=np.float32)
        X = arr.reshape(request.batch_size, request.seq_len, request.n_features)

        # 推理
        result = inference_service.predict(
            X,
            inverse_transform=request.inverse_transform,
        )

        return PredictResponse(
            status="success",
            ensemble_prediction=result.ensemble_prediction.flatten().tolist(),
            individual_predictions={
                name: pred.flatten().tolist()
                for name, pred in result.individual_predictions.items()
            },
            inference_time_ms=result.inference_time_ms,
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"推理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 启动
# ============================================================================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8500,
        workers=1,
        log_level="info",
    )
