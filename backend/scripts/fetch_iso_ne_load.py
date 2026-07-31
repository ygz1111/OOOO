#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 ISO New England 拉取实际系统负荷（真实"实际值"，用于预测准确性闭环）

数据源：ISO-NE Web Services API v1.1
  端点：GET /hourlysystemload/day/{YYYYMMDD}
  认证：HTTP Basic（用户名 = API key，密码留空）
  注册：https://www.iso-ne.com/isoexpress/login?p_p_id=58...create_account

行为：
  1. 拉取指定日期（默认昨天）每小时实际系统负荷
  2. 写入 actual_load_data 表（data_source='iso_ne'，INSERT IGNORE 幂等）
  3. 回填 load_predictions.actual_load_mw（与 target_timestamp 匹配）
  4. 配置 ISO_NE_API_KEY 后即可启用；未配置时给出注册指引

用法：
  export ISO_NE_API_KEY=你的key          # 或写入 .env
  cd backend && python scripts/fetch_iso_ne_load.py [YYYYMMDD]
"""
import os
import sys
import argparse
import logging
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BACKEND_DIR, "..", ".env"))

sys.path.insert(0, BACKEND_DIR)
from realtime_api.crud import ActualLoadDataCRUD, LoadPredictionsCRUD
from realtime_api.database import db_manager

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch_iso_ne")

API_BASE = "https://webservices.iso-ne.com/api/v1.1"
REGISTER_URL = (
    "https://www.iso-ne.com/isoexpress/login?p_p_id=58&p_p_lifecycle=0"
    "&p_p_state=normal&p_p_mode=view&saveLastPath=0&_58_struts_action="
    "%2Flogin%2Fcreate_account"
)


def fetch_hourly_system_load(day: date, api_key: str) -> list:
    """拉取某天的小时级实际系统负荷，返回 [(datetime, MW), ...]"""
    url = f"{API_BASE}/hourlysystemload/day/{day.strftime('%Y%m%d')}?format=json"
    resp = requests.get(
        url,
        auth=(api_key, ""),  # ISO-NE: username=key, password 空
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    # 容错解析：兼容不同字段命名
    loads = data
    for key in ("HourlySystemLoads", "hourly_system_loads", "data"):
        if isinstance(data, dict) and key in data:
            loads = data[key]
            break
    items = loads
    if isinstance(loads, dict):
        for key in ("HourlySystemLoad", "hourly_system_load", "items"):
            if key in loads:
                items = loads[key]
                break

    result = []
    for it in items:
        begin = it.get("BeginDate") or it.get("begin_date") or it.get("timestamp")
        mw = it.get("Mw") or it.get("mw") or it.get("value")
        if begin is None or mw is None:
            continue
        ts = datetime.fromisoformat(begin.replace("Z", "+00:00"))
        result.append((ts, float(mw)))
    return result


async def persist(rows, region: str = "NewEngland"):
    """写入 actual_load_data + 回填 load_predictions.actual_load_mw"""
    await db_manager.initialize()
    inserted = 0
    for ts, mw in rows:
        try:
            rid = await ActualLoadDataCRUD.insert_actual_load(
                timestamp=ts, actual_load_mw=mw, region=region, data_source="iso_ne"
            )
            if rid:
                inserted += 1
        except Exception as e:
            logger.warning(f"写入失败 {ts}: {e}")

    # 回填 load_predictions（按 target_timestamp 匹配，仅填补仍为 NULL 的）
    backfilled = 0
    for ts, mw in rows:
        try:
            sql = """
                UPDATE load_predictions
                SET actual_load_mw = %s
                WHERE target_timestamp = %s AND actual_load_mw IS NULL
            """
            cur = await db_manager.execute_sql(sql, (mw, ts))
            backfilled += 0  # execute_sql 返回行集而非 rowcount；数量从日志看
        except Exception as e:
            logger.warning(f"回填失败 {ts}: {e}")
    logger.info(f"插入 actual_load_data: {inserted} 条；回填语句已执行")
    return inserted


def main():
    parser = argparse.ArgumentParser(description="拉取 ISO-NE 实际负荷")
    parser.add_argument("day", nargs="?", default=None, help="日期 YYYYMMDD（默认昨天）")
    args = parser.parse_args()

    api_key = os.getenv("ISO_NE_API_KEY", "").strip()
    if not api_key:
        print(
            "\n❌ 未配置 ISO_NE_API_KEY。\n"
            f"   免费注册 API key: {REGISTER_URL}\n"
            "   然后在 .env 中设置 ISO_NE_API_KEY=你的key\n"
        )
        sys.exit(1)

    day = datetime.strptime(args.day, "%Y%m%d").date() if args.day \
        else date.today() - timedelta(days=1)

    logger.info(f"拉取 {day} 的 ISO-NE 实际负荷...")
    rows = fetch_hourly_system_load(day, api_key)
    logger.info(f"获取到 {len(rows)} 条小时数据")

    import asyncio
    inserted = asyncio.run(persist(rows))
    logger.info(f"完成：写入 {inserted} 条（其余为已存在跳过）")


if __name__ == "__main__":
    main()
