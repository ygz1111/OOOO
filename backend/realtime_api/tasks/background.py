"""
智能电网负荷预测系统 - 后台定时任务

包含：
- 系统指标采集 (每 5min)
- 实际负荷回填 (每 5min)
- 缓存性能快照 (每 5min)
- 性能预警检查 (每 5min)

从 app.py 的 lifespan 中抽取，由 lifespan 调用 start_background_tasks()。

作者: 毕业设计项目
"""

import asyncio
import logging

from realtime_api.crud import (
    SystemMetricsCRUD,
    PerformanceAlertsCRUD,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 定时任务定义
# ============================================================================

async def _periodic_system_metrics():
    """每 5 分钟采集一次系统指标并写入 system_metrics 表"""
    while True:
        try:
            import psutil
            sys_cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            await SystemMetricsCRUD.insert_metrics(
                cpu_percent=sys_cpu,
                cpu_count=psutil.cpu_count(),
                memory_percent=mem.percent,
                memory_used_gb=round(mem.used / 1024**3, 3),
                memory_available_gb=round(mem.available / 1024**3, 3),
                gpu_available=False,
                disk_usage_percent=disk.percent,
                process_count=len(psutil.pids()),
            )
        except ImportError:
            pass  # psutil 未安装则跳过
        except Exception as e:
            logger.warning(f"定期系统指标采集失败: {e}")
        await asyncio.sleep(300)


# NOTE: 原 _periodic_actual_load_backfill / _periodic_cache_performance 任务已删除：
# 前者用 ±2% 随机噪声伪造实际负荷数据，后者写入全 0 的缓存性能假指标。
# 实际负荷数据只应来自真实数据源，缓存指标在没有 Redis 采集前不应造数入库。


async def _periodic_performance_alerts():
    """每 5 分钟检查系统指标并生成性能预警"""
    while True:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()

            # CPU 使用率超过 90%
            if cpu > 90:
                await PerformanceAlertsCRUD.insert_alert(
                    alert_type='warning',
                    metric_name='cpu_percent',
                    current_value=cpu,
                    threshold=90.0,
                    message=f'CPU使用率过高: {cpu:.1f}%',
                    severity=2,
                )

            # 内存使用率超过 90%
            if mem.percent > 90:
                await PerformanceAlertsCRUD.insert_alert(
                    alert_type='warning',
                    metric_name='memory_percent',
                    current_value=mem.percent,
                    threshold=90.0,
                    message=f'内存使用率过高: {mem.percent:.1f}%',
                    severity=2,
                )

            # 磁盘使用率超过 85%
            disk = psutil.disk_usage('/')
            if disk.percent > 85:
                await PerformanceAlertsCRUD.insert_alert(
                    alert_type='critical',
                    metric_name='disk_usage_percent',
                    current_value=disk.percent,
                    threshold=85.0,
                    message=f'磁盘使用率过高: {disk.percent:.1f}%',
                    severity=1,
                )
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"性能预警检查失败: {e}")
        await asyncio.sleep(300)


# ============================================================================
# 启动 / 停止后台任务
# ============================================================================

# 全局任务列表引用，用于停止
_bg_tasks: list = []


def start_background_tasks() -> list:
    """启动所有后台定时任务，返回任务列表"""
    global _bg_tasks
    _bg_tasks = [
        asyncio.create_task(_periodic_system_metrics()),
        asyncio.create_task(_periodic_performance_alerts()),
    ]
    logger.info("✅ 定期后台任务已启动 (系统监控/性能预警)")
    return _bg_tasks


def stop_background_tasks():
    """取消所有后台定时任务"""
    global _bg_tasks
    for task in _bg_tasks:
        task.cancel()
    _bg_tasks = []
    logger.info("后台任务已取消")
