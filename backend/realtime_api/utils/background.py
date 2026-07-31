# -*- coding: utf-8 -*-
"""
后台任务工具：fire-and-forget 异步落库

统一"请求内启动后台协程（如异步写日志/指标/预测性能），不阻塞响应"的模式，
替代原先散落在 app.py / middleware.py / routers 中的 5+ 份
`async def _persist_xxx() + asyncio.create_task()` 重复实现。

要点：
- 持有任务引用（_background_tasks），避免 asyncio 对未引用任务提前 GC 回收
- 任务失败只记日志，绝不向上抛出影响请求
- 协程通过零参工厂延迟创建，避免在错误的事件循环中创建
"""
import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# 持有所有后台任务引用；任务完成时自动移除
_background_tasks: set = set()


def fire_and_forget(coro_factory: Callable[[], Awaitable], name: str = "") -> None:
    """调度一个后台协程（不阻塞、不等待、不抛出）。

    Args:
        coro_factory: 返回协程的零参数工厂函数（延迟创建协程）
        name: 任务名，用于日志
    """
    task = asyncio.create_task(coro_factory())
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error(f"后台任务[{name or coro_factory.__name__}]失败: {t.exception()}")

    task.add_done_callback(_done)
