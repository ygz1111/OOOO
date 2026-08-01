# -*- coding: utf-8 -*-
"""
ISO-NE 实际负荷拉取（可复用模块）

被以下位置共用：
  - scripts/fetch_iso_ne_load.py（手动拉取）
  - realtime_api/tasks/background.py（后台定时自动拉取）

认证：ISO Express 注册邮箱 + 密码（HTTP Basic Auth）
端点：/fiveminutesystemload/day/{YYYYMMDD}（5 分钟真实系统负荷）
转换：5 分钟 LoadMw 按小时平均 → 整点时间戳（东部时区 naive，与预测对齐）
"""
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

ISO_NE_BASE = "https://webservices.iso-ne.com/api/v1.1"


def fetch_hourly_actual_load(day: date, username: str, password: str) -> list:
    """拉取某天的小时级实际系统负荷 → [(整点 datetime, 小时平均 MW), ...]

    Args:
        day: 目标日期（支持当天/历史日期；当天返回已发生小时的数据）
        username: ISO Express 注册邮箱
        password: ISO Express 密码

    Returns:
        按时间升序的 [(naive 东部整点时间, 平均 MW)] 列表
    """
    url = f"{ISO_NE_BASE}/fiveminutesystemload/day/{day.strftime('%Y%m%d')}"
    resp = requests.get(
        url, auth=(username, password), timeout=30,
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()

    loads = data.get("FiveMinSystemLoads", {})
    items = loads.get("FiveMinSystemLoad", [])

    east = ZoneInfo("America/New_York")
    hourly = {}
    for it in items:
        begin = it.get("BeginDate")
        mw = it.get("LoadMw")
        if begin is None or mw is None:
            continue
        # 带偏移时间戳 → 东部墙钟 naive（与预测 target_timestamp 对齐）
        ts = datetime.fromisoformat(begin)
        if ts.tzinfo is not None:
            ts = ts.astimezone(east).replace(tzinfo=None)
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        hourly.setdefault(hour_key, []).append(float(mw))

    rows = [
        (hour, sum(v) / len(v)) for hour, v in sorted(hourly.items())
    ]
    return rows


def get_credentials() -> tuple:
    """从环境变量读取 ISO Express 凭据（未配置返回 (None, None)）"""
    import os
    username = os.getenv("ISO_NE_USERNAME", "").strip()
    password = os.getenv("ISO_NE_PASSWORD", "").strip()
    if username and password:
        return username, password
    return None, None


async def persist_actual_load(rows, data_source: str = "iso_ne",
                              region: str = "NewEngland") -> dict:
    """写入 actual_load_data + 回填 load_predictions.actual_load_mw（幂等）

    Returns:
        {"inserted": int, "backfilled": int}
    """
    from realtime_api.crud import ActualLoadDataCRUD
    from realtime_api.database import db_manager

    await db_manager.initialize()
    inserted = 0
    for ts, mw in rows:
        try:
            rid = await ActualLoadDataCRUD.insert_actual_load(
                timestamp=ts, actual_load_mw=mw, region=region, data_source=data_source
            )
            if rid:
                inserted += 1
        except Exception as e:
            logger.warning(f"写入失败 {ts}: {e}")

    backfilled = 0
    for ts, mw in rows:
        try:
            await db_manager.execute_sql(
                """UPDATE load_predictions SET actual_load_mw = %s
                   WHERE target_timestamp = %s AND actual_load_mw IS NULL""",
                (mw, ts),
            )
            backfilled += 1
        except Exception as e:
            logger.warning(f"回填失败 {ts}: {e}")
    logger.info(f"实际负荷入库: 写入 {inserted} 条, 回填 {backfilled} 条")
    return {"inserted": inserted, "backfilled": backfilled}


async def sync_actual_load_for_days(days) -> dict:
    """拉取并入库指定日期列表的实际负荷（供后台任务/手动调用）

    Args:
        days: date 列表
    """
    username, password = get_credentials()
    if not username:
        logger.info("未配置 ISO_NE_USERNAME/PASSWORD，跳过实际负荷同步")
        return {"inserted": 0, "backfilled": 0, "days": 0}

    import asyncio
    total = {"inserted": 0, "backfilled": 0, "days": 0}
    for day in days:
        try:
            # requests.get 是同步阻塞，放入线程池避免卡住事件循环
            rows = await asyncio.to_thread(
                fetch_hourly_actual_load, day, username, password
            )
            if not rows:
                logger.info(f"  {day}: 无数据（当天可能尚未产生）")
                continue
            r = await persist_actual_load(rows)
            total["inserted"] += r["inserted"]
            total["backfilled"] += r["backfilled"]
            total["days"] += 1
        except Exception as e:
            logger.warning(f"  {day} 同步失败: {e}")
    return total
