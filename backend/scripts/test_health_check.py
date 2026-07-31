#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from realtime_api.health_check import get_health_check_service

print("Testing health check service...")

health_service = get_health_check_service()

# 快速测试组件检查
import asyncio

async def test_health():
    db_health = await health_service.check_database_health()
    print(f"Database: {db_health.status} - {db_health.message}")
    
    system_health = health_service.check_system_resources()
    print(f"System: {system_health.status} - {system_health.message}")
    
    gpu_health = health_service.check_gpu_health()
    print(f"GPU: {gpu_health.status} - {gpu_health.message}")

asyncio.run(test_health())
print("Health check service is working!")