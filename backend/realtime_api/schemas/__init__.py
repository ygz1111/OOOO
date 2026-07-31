"""
智能电网负荷预测系统 - Schemas 包

统一导出所有 Pydantic 数据模型：
- core: 核心业务模型 (预测、气象、监控等)
- auth: 认证授权模型 (用户、角色、权限等)
"""

from realtime_api.schemas.core import *  # noqa: F401, F403
from realtime_api.schemas.core import __all__ as _core_all

# 重新导出 auth 模块，使 from realtime_api.schemas.auth import XXX 可用
from realtime_api.schemas import auth as auth_schemas  # noqa: F401

__all__ = list(_core_all)
