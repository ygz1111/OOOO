# -*- coding: utf-8 -*-
"""手动同步最近 14 天实际负荷（含今天），用于立即补齐 overview 历史回测数据"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, '..', '.env'))

from realtime_api.utils.iso_ne import sync_actual_load_for_days
import asyncio


async def main():
    ET = ZoneInfo("America/New_York")
    today = datetime.now(ET).date()
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    print(f'同步日期: {days[0]} ~ {days[-1]}（共 {len(days)} 天，含今天）')
    result = await sync_actual_load_for_days(days)
    print(f'结果: {result}')


if __name__ == '__main__':
    asyncio.run(main())
