"""Background jobs must recover from transient failures and stop on cancellation."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from realtime_api.tasks import background as jobs
from realtime_api.utils import background as tasks
from realtime_api.utils import iso_ne


STATS = {"cpu_percent": 92, "cpu_count": 4, "memory_percent": 94, "memory_used_gb": 3,
         "memory_available_gb": 1, "disk_percent": 88, "process_count": 20}


@pytest.mark.asyncio
@pytest.mark.parametrize("first_error", [ImportError("psutil absent"), RuntimeError("sample failed")])
async def test_metrics_retries_on_next_tick_and_propagates_cancellation(monkeypatch, first_error):
    sampler = AsyncMock(side_effect=[first_error, STATS])
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    insert = AsyncMock()
    monkeypatch.setattr(jobs.asyncio, "to_thread", sampler)
    monkeypatch.setattr(jobs.asyncio, "sleep", sleep)
    monkeypatch.setattr(jobs.SystemMetricsCRUD, "insert_metrics", insert)
    with pytest.raises(asyncio.CancelledError):
        await jobs._periodic_system_metrics()
    assert sampler.await_count == 2
    assert insert.await_args.kwargs["cpu_percent"] == 92
    assert insert.await_args.kwargs["disk_usage_percent"] == 88
    assert sleep.await_args.args == (300,)


@pytest.mark.asyncio
@pytest.mark.parametrize("stats,errors,expected", [(STATS, None, ["cpu_percent", "memory_percent", "disk_usage_percent"]),
    ({**STATS, "cpu_percent": 90, "memory_percent": 90, "disk_percent": 85}, None, []),
    (STATS, ImportError("psutil absent"), []), (STATS, RuntimeError("sample failed"), [])])
async def test_alert_thresholds_and_sampling_failures(monkeypatch, stats, errors, expected):
    monkeypatch.setattr(jobs.asyncio, "to_thread", AsyncMock(return_value=stats, side_effect=errors))
    monkeypatch.setattr(jobs.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))
    insert = AsyncMock()
    monkeypatch.setattr(jobs.PerformanceAlertsCRUD, "insert_alert", insert)
    with pytest.raises(asyncio.CancelledError):
        await jobs._periodic_performance_alerts()
    assert [call.kwargs["metric_name"] for call in insert.await_args_list] == expected
    if expected:
        assert insert.await_args_list[-1].kwargs["severity"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_actual_sync_full_history_then_recent_days_after_success(monkeypatch, failure):
    responses = ([RuntimeError("ISO-NE temporarily unavailable"), {"days": 14, "inserted": 3, "backfilled": 2}]
                 if failure else [{"days": 14, "inserted": 3, "backfilled": 2}, {"days": 2, "inserted": 1, "backfilled": 1}])
    sync = AsyncMock(side_effect=responses)
    monkeypatch.setattr(iso_ne, "sync_actual_load_for_days", sync)
    monkeypatch.setattr(jobs.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()]))
    with pytest.raises(asyncio.CancelledError):
        await jobs._periodic_actual_load_sync()
    assert len(sync.await_args_list[0].args[0]) == 14
    assert len(sync.await_args_list[1].args[0]) == (14 if failure else 2)
    days = sync.await_args_list[0].args[0]
    assert days == sorted(days)
    assert (days[-1] - days[0]).days == 13


def test_system_sampler_units(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval: 42 if interval == 1 else 0)
    monkeypatch.setattr(psutil, "cpu_count", lambda: 4)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(percent=25, used=2 * 1024**3, available=6 * 1024**3))
    monkeypatch.setattr(psutil, "disk_usage", lambda path: SimpleNamespace(percent=30))
    monkeypatch.setattr(psutil, "pids", lambda: [1, 2, 3])
    sample = jobs._sample_system_stats()
    assert sample["memory_used_gb"] == 2
    assert sample["memory_available_gb"] == 6
    assert sample["process_count"] == 3


@pytest.mark.asyncio
async def test_job_lifecycle_retains_then_cancels_tasks(monkeypatch):
    async def forever():
        await asyncio.Event().wait()
    for name in ("_periodic_system_metrics", "_periodic_performance_alerts", "_periodic_actual_load_sync"):
        monkeypatch.setattr(jobs, name, forever)
    started = jobs.start_background_tasks()
    assert len(started) == 3
    jobs.stop_background_tasks()
    await asyncio.gather(*started, return_exceptions=True)
    assert jobs._bg_tasks == []
    assert all(task.cancelled() for task in started)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_fire_and_forget_retains_task_and_releases_it(monkeypatch, outcome):
    logger = Mock()
    monkeypatch.setattr(tasks, "logger", logger)
    async def work():
        if outcome == "failure":
            raise RuntimeError("write failed")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return 7
    tasks.fire_and_forget(work, "persistence")
    scheduled = list(tasks._background_tasks)
    await asyncio.gather(*scheduled, return_exceptions=True)
    await asyncio.sleep(0)
    assert not any(task in tasks._background_tasks for task in scheduled)
    assert logger.error.called == (outcome == "failure")
