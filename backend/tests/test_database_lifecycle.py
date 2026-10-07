"""Database workers retain ownership until synchronous I/O has finished."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import AsyncMock, Mock

import pytest

from realtime_api import database


@pytest.mark.asyncio
async def test_cancelled_connection_acquisition_returns_the_eventual_connection():
    started, finish, released = threading.Event(), threading.Event(), threading.Event()
    connection = Mock()
    connection.close.side_effect = released.set

    def acquire():
        started.set()
        assert finish.wait(3)
        return connection

    manager = object.__new__(database.DatabaseManager)
    manager._pool = Mock()
    manager._pool.get_connection.side_effect = acquire
    manager._executor = ThreadPoolExecutor(max_workers=1)
    request = asyncio.create_task(manager.get_connection())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        finish.set()
        assert await asyncio.to_thread(released.wait, 1)
        connection.close.assert_called_once()
    finally:
        finish.set()
        manager._executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [
    ("execute_sql", (1,)),
    ("execute_sql_insert", (1,)),
    ("execute_sql_many", [(1,), (2,)]),
])
async def test_cancelled_sql_does_not_release_a_connection_still_in_use(method, params):
    started, finish, released = threading.Event(), threading.Event(), threading.Event()
    premature_close = []
    operation_finished = threading.Event()

    def execute(*_):
        started.set()
        assert finish.wait(3)
        operation_finished.set()

    def close_cursor():
        if not operation_finished.is_set():
            premature_close.append("cursor")

    def close_connection():
        if not operation_finished.is_set():
            premature_close.append("connection")
        released.set()

    cursor = Mock(lastrowid=17, rowcount=2)
    cursor.execute.side_effect = execute
    cursor.executemany.side_effect = execute
    cursor.fetchall.return_value = [{"value": 1}]
    cursor.close.side_effect = close_cursor
    connection = Mock()
    connection.cursor.return_value = cursor
    connection.close.side_effect = close_connection
    pool = Mock()
    pool.get_connection.return_value = connection
    manager = object.__new__(database.DatabaseManager)
    manager._pool = pool
    manager._executor = ThreadPoolExecutor(max_workers=2)
    request = asyncio.create_task(getattr(manager, method)("SQL", params))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert not released.is_set(), "request cancellation returned a busy connection to the pool"
        assert premature_close == []
        finish.set()
        assert await asyncio.to_thread(released.wait, 1)
        assert premature_close == []
    finally:
        finish.set()
        if not request.done():
            request.cancel()
        manager._executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params,expected", [
    ("execute_sql", (1,), [{"value": 1}]),
    ("execute_sql_insert", (1,), 17),
    ("execute_sql_many", [(1,), (2,)], 2),
])
async def test_sql_resource_work_runs_outside_the_event_loop(method, params, expected):
    event_loop_thread = threading.get_ident()
    operations = []

    def record(*_, **__):
        operations.append(threading.get_ident())

    cursor = Mock(lastrowid=17, rowcount=2)
    cursor.execute.side_effect = record
    cursor.executemany.side_effect = record
    cursor.fetchall.side_effect = lambda: (record() or [{"value": 1}])
    cursor.close.side_effect = record
    connection = Mock()
    connection.cursor.side_effect = lambda **_: (record() or cursor)
    connection.close.side_effect = record
    pool = Mock()
    pool.get_connection.side_effect = lambda: (record() or connection)
    manager = object.__new__(database.DatabaseManager)
    manager._pool = pool
    manager._executor = ThreadPoolExecutor(max_workers=1)
    try:
        assert await getattr(manager, method)("SQL", params) == expected
        assert operations and all(thread != event_loop_thread for thread in operations)
        assert len(set(operations)) == 1
        cursor.close.assert_called_once()
        connection.close.assert_called_once()
    finally:
        manager._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_sql_error_is_reported_and_resources_are_released():
    cursor = Mock()
    cursor.execute.side_effect = RuntimeError("query failed")
    connection = Mock()
    connection.cursor.return_value = cursor
    manager = object.__new__(database.DatabaseManager)
    manager._pool = Mock()
    manager._pool.get_connection.return_value = connection
    manager._executor = ThreadPoolExecutor(max_workers=1)
    try:
        with pytest.raises(RuntimeError, match="query failed"):
            await manager.execute_sql("SQL")
        cursor.close.assert_called_once()
        connection.close.assert_called_once()
    finally:
        manager._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_legacy_pool_reinitializes_after_close(monkeypatch):
    cursor = Mock()
    cursor.fetchall.return_value = [{"value": 2}]
    connection = Mock()
    connection.cursor.return_value = cursor
    replacement_pool = Mock()
    replacement_pool.get_connection.return_value = connection
    manager = object.__new__(database.DatabaseManager)
    manager._pool = Mock()
    manager._config = Mock(pool_size=1)
    manager._config.get_connection_params.return_value = {}
    manager._executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(database.pooling, "MySQLConnectionPool", Mock(return_value=replacement_pool))
    try:
        await manager.close()
        assert manager._pool is None
        assert await manager.execute_sql("SELECT 2") == [{"value": 2}]
        assert manager._pool is replacement_pool
    finally:
        manager._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_close_database_disposes_auth_engine_and_allows_reinitialization(monkeypatch):
    close = AsyncMock()
    engine = Mock(dispose=AsyncMock())
    monkeypatch.setattr(database.db_manager, "close", close)
    monkeypatch.setattr(database, "_async_engine", engine)
    monkeypatch.setattr(database, "_AsyncSessionLocal", object())

    await database.close_database()

    close.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    assert database._async_engine is None
    assert database._AsyncSessionLocal is None


@pytest.mark.asyncio
async def test_auth_engine_is_disposed_when_legacy_pool_close_fails(monkeypatch):
    engine = Mock(dispose=AsyncMock())
    monkeypatch.setattr(database.db_manager, "close", AsyncMock(side_effect=RuntimeError("pool close")))
    monkeypatch.setattr(database, "_async_engine", engine)
    monkeypatch.setattr(database, "_AsyncSessionLocal", object())

    with pytest.raises(RuntimeError, match="pool close"):
        await database.close_database()

    engine.dispose.assert_awaited_once()
