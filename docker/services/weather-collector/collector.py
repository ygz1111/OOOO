"""
气象数据采集服务

定时从 Open-Meteo API 采集气象数据，经验证后写入 PostgreSQL。
同时提供 Redis 缓存和健康检查端点。

启动方式:
    python collector.py

环境变量:
    OPEN_METEO_API_URL, POSTGRES_HOST, REDIS_HOST, etc.
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timedelta

# 项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
import uvicorn

from realtime_api.openmeteo_client import OpenMeteoClient
from realtime_api.weather_validator import WeatherDataValidator

# ============================================================================
# 日志配置
# ============================================================================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("weather-collector")

# ============================================================================
# 配置
# ============================================================================
COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL", "300"))  # 5分钟
PAST_DAYS = int(os.getenv("PAST_DAYS", "7"))
FORECAST_DAYS = int(os.getenv("FORECAST_DAYS", "2"))

# ============================================================================
# FastAPI 健康检查端点
# ============================================================================
app = FastAPI(title="Weather Collector", docs_url="/docs")

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "weather-collector",
        "timestamp": datetime.now().isoformat(),
        "last_collect": getattr(health, "_last_collect", None),
    }

@app.get("/metrics")
async def metrics():
    """Prometheus 指标"""
    return {
        "collect_count": getattr(metrics, "_count", 0),
        "collect_errors": getattr(metrics, "_errors", 0),
    }


# ============================================================================
# 采集循环
# ============================================================================
def collect_weather_data():
    """采集气象数据并写入数据库"""
    logger.info("开始采集气象数据...")

    try:
        client = OpenMeteoClient(
            past_days=PAST_DAYS,
            forecast_days=FORECAST_DAYS,
        )
        validator = WeatherDataValidator()

        # 获取数据
        weather_df, quality_reports = client.fetch_weather_data()
        logger.info(f"获取到 {len(weather_df)} 条气象数据")

        # 验证
        clean_df, report, flags = validator.validate(weather_df)
        logger.info(f"验证完成: {report.total_checked} 条, {report.anomaly_count} 异常")

        # TODO: 写入 PostgreSQL
        # TODO: 缓存到 Redis

        health._last_collect = datetime.now().isoformat()
        metrics._count = getattr(metrics, "_count", 0) + 1
        logger.info("采集完成")

    except Exception as e:
        logger.error(f"采集失败: {e}", exc_info=True)
        metrics._errors = getattr(metrics, "_errors", 0) + 1


def collect_loop():
    """定时采集循环"""
    logger.info(f"气象采集服务启动, 间隔 {COLLECT_INTERVAL}秒")

    # 首次立即采集
    collect_weather_data()

    while True:
        time.sleep(COLLECT_INTERVAL)
        collect_weather_data()


# ============================================================================
# 启动
# ============================================================================
def start():
    """启动采集服务和健康检查"""
    # 后台线程运行采集循环
    collect_thread = threading.Thread(target=collect_loop, daemon=True)
    collect_thread.start()

    # 主线程运行 FastAPI 健康检查
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9090,
        log_level="info",
    )


if __name__ == "__main__":
    start()
