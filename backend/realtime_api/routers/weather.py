"""
智能电网负荷预测系统 - 气象路由

端点:
  GET /api/weather/current - 获取当前气象数据
  GET /api/weather/history - 历史气象数据查询

从 app.py 中抽取。

作者: 毕业设计项目
"""

import asyncio
import logging
from datetime import timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from realtime_api.schemas import (
    WeatherResponse,
    WeatherStationData,
    SuccessResponse,
)
from realtime_api.crud import WeatherDataCRUD
from realtime_api.services.container import services, eastern_now, eastern_now_hour

logger = logging.getLogger(__name__)

router = APIRouter(tags=["气象"])


# ============================================================================
# GET /api/weather/current — 获取当前气象数据
# ============================================================================

@router.get(
    "/api/weather/current",
    response_model=WeatherResponse,
    summary="获取当前气象数据",
    description="获取新英格兰地区6个气象站点的实时气象数据",
)
async def get_current_weather(
    force_refresh: bool = Query(False, description="强制刷新，绕过缓存直接请求气象API"),
):
    """获取当前气象数据（同时异步写入数据库）"""
    try:
        weather_df, quality_reports = await asyncio.to_thread(
            services.openmeteo_client.fetch_weather_data,
            None,  # locations
            force_refresh,  # force_refresh
        )

        # 构建站点数据
        stations = []
        now = eastern_now()
        now_ts = pd.Timestamp(now)
        for location in services.openmeteo_client.locations:
            loc_data = weather_df[weather_df["location"] == location.name].copy()
            if len(loc_data) > 0:
                loc_data["timestamp"] = pd.to_datetime(loc_data["timestamp"])
                time_diffs = (loc_data["timestamp"] - now_ts).abs()
                nearest_idx = time_diffs.idxmin()
                latest = loc_data.loc[nearest_idx]
                actual_ts = loc_data.loc[nearest_idx, "timestamp"]
                logger.debug(
                    f"  {location.name}: 选中时间 {actual_ts} "
                    f"(距 now {time_diffs.loc[nearest_idx].total_seconds()/3600:.1f}h)"
                )
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

        # 异步写入数据库（非阻塞）
        async def _persist_weather():
            saved_count = 0
            for station in stations:
                try:
                    await WeatherDataCRUD.insert_weather_data(
                        timestamp=now,
                        location=station.name,
                        temperature_2m=station.temperature_2m,
                        dew_point_2m=station.dew_point_2m,
                        relative_humidity_2m=station.relative_humidity_2m,
                        wind_speed_10m=station.wind_speed_10m,
                        cloud_cover=station.cloud_cover,
                        shortwave_radiation=station.shortwave_radiation,
                        data_quality_score=0.95,
                        is_validated=True,
                        data_source='openmeteo',
                        latitude=station.latitude,
                        longitude=station.longitude,
                    )
                    saved_count += 1
                except Exception as e:
                    logger.warning(f"气象数据入库失败 ({station.name}): {e}")
            if saved_count:
                logger.info(f"气象数据已入库 {saved_count}/{len(stations)} 个站点")

        asyncio.create_task(_persist_weather())

        # 区域平均
        regional_avg = {}
        param_cols = ["temperature_2m", "dew_point_2m", "relative_humidity_2m",
                      "wind_speed_10m", "cloud_cover", "shortwave_radiation"]
        for col in param_cols:
            if col in weather_df.columns:
                regional_avg[col] = round(float(weather_df[col].mean()), 1)

        return WeatherResponse(
            status="success",
            timestamp=now.isoformat(),
            stations=stations,
            regional_average=regional_avg,
        )

    except Exception as e:
        logger.error(f"获取气象数据失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"获取气象数据失败: {e}",
        )


# ============================================================================
# GET /api/weather/history — 历史气象数据查询
# ============================================================================

@router.get(
    "/api/weather/history",
    response_model=SuccessResponse,
    summary="历史气象数据查询",
    description="查询历史气象数据，支持按位置和时间范围过滤",
)
async def get_weather_history(
    location: Optional[str] = None,
    hours: int = 24,
    limit: int = 100,
):
    """历史气象数据查询API"""
    try:
        end_time = eastern_now_hour()
        start_time = end_time - timedelta(hours=hours)

        limit = max(1, min(limit, 1000))
        hours = max(1, min(hours, 720))  # 最多30天

        if location:
            weather_data = await WeatherDataCRUD.get_weather_by_location_and_time(
                location=location,
                start_time=start_time,
                end_time=end_time
            )
        else:
            weather_data = await WeatherDataCRUD.get_latest_weather_data(
                location="Boston",
                limit=limit
            )

        logger.info(f"查询到 {len(weather_data)} 条历史气象记录")

        return SuccessResponse(
            message=f"成功获取历史气象数据，共{len(weather_data)}条记录",
            data=weather_data
        )

    except Exception as e:
        logger.error(f"历史气象查询失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"查询历史气象数据失败: {str(e)}"
        )
