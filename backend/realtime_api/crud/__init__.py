"""
智能电网负荷预测系统 - CRUD 包

统一导出所有数据库 CRUD 操作类：
- core: 核心业务 CRUD (气象、预测、性能、日志等)
- auth_crud: 认证授权 CRUD (用户、角色、权限等)
"""

from realtime_api.crud.core import (
    WeatherDataCRUD,
    LoadPredictionsCRUD,
    ModelPerformanceCRUD,
    APILogsCRUD,
    SystemMetricsCRUD,
    CachePerformanceCRUD,
    PerformanceAlertsCRUD,
    ActualLoadDataCRUD,
)

from realtime_api.crud.auth_crud import AuthCRUD

__all__ = [
    'WeatherDataCRUD',
    'LoadPredictionsCRUD',
    'ModelPerformanceCRUD',
    'APILogsCRUD',
    'SystemMetricsCRUD',
    'CachePerformanceCRUD',
    'PerformanceAlertsCRUD',
    'ActualLoadDataCRUD',
    'AuthCRUD',
]
