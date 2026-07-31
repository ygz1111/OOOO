#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 统一错误处理模块

提供标准的错误码体系和异常处理机制

作者: 毕业设计项目
"""

from typing import Dict, Any, Optional
from enum import IntEnum
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
import logging


class ErrorCode(IntEnum):
    """HTTP状态码扩展 - 业务错误码"""
    
    # 2xx 成功 (200-299)
    SUCCESS = 20000
    
    # 4xx 客户端错误 (400-499)
    BAD_REQUEST = 40000
    VALIDATION_ERROR = 40001
    INVALID_PARAMETERS = 40002
    MISSING_REQUIRED_FIELD = 40003
    INVALID_FORMAT = 40004
    
    UNAUTHORIZED = 40100
    INVALID_CREDENTIALS = 40101
    TOKEN_EXPIRED = 40102
    TOKEN_INVALID = 40103
    INSUFFICIENT_PERMISSIONS = 40104
    
    FORBIDDEN = 40300
    ACCESS_DENIED = 40301
    RESOURCE_FORBIDDEN = 40302
    
    NOT_FOUND = 40400
    RESOURCE_NOT_FOUND = 40401
    ENDPOINT_NOT_FOUND = 40402
    
    METHOD_NOT_ALLOWED = 40500
    
    CONFLICT = 40900
    RESOURCE_CONFLICT = 40901
    DUPLICATE_RECORD = 40902
    
    TOO_MANY_REQUESTS = 42900
    RATE_LIMIT_EXCEEDED = 42901
    
    # 5xx 服务器错误 (500-599)
    INTERNAL_SERVER_ERROR = 50000
    UNKNOWN_ERROR = 50001
    SERVICE_UNAVAILABLE = 50002
    TIMEOUT_ERROR = 50003
    
    DATABASE_ERROR = 50010
    DATABASE_CONNECTION_FAILED = 50011
    DATABASE_QUERY_FAILED = 50012
    
    REDIS_ERROR = 50020
    REDIS_CONNECTION_FAILED = 50021
    REDIS_OPERATION_FAILED = 50022
    
    MODEL_ERROR = 50030
    MODEL_NOT_READY = 50031
    MODEL_INFERENCE_FAILED = 50032
    MODEL_LOAD_FAILED = 50033
    
    WEATHER_API_ERROR = 50040
    WEATHER_API_UNAVAILABLE = 50041
    WEATHER_DATA_INVALID = 50042
    
    PREDICTION_ERROR = 50050
    PREDICTION_PIPELINE_FAILED = 50051
    FEATURE_GENERATION_FAILED = 50052
    DATA_VALIDATION_FAILED = 50053
    
    CONFIGURATION_ERROR = 50060
    CONFIG_NOT_FOUND = 50061
    INVALID_CONFIGURATION = 50062
    
    FILE_ERROR = 50070
    FILE_NOT_FOUND = 50071
    FILE_READ_ERROR = 50072
    FILE_WRITE_ERROR = 50073


class SmartGridException(HTTPException):
    """智能电网系统业务异常基类"""
    
    def __init__(self, 
                 error_code: ErrorCode,
                 message: str,
                 detail: Optional[str] = None,
                 error_id: Optional[str] = None):
        
        self.error_code = error_code
        self.message = message
        self.detail = detail
        self.error_id = error_id or self._generate_error_id()
        
        # 映射到标准HTTP状态码
        http_status = self._map_to_http_status(error_code)
        
        super().__init__(
            status_code=http_status,
            detail={
                "error_id": self.error_id,
                "error_code": error_code.value,
                "error_name": error_code.name,
                "message": message,
                "detail": detail
            }
        )
    
    def _generate_error_id(self) -> str:
        """生成唯一的错误ID"""
        import uuid
        import time
        timestamp = int(time.time() * 1000)
        return f"err_{timestamp}_{str(uuid.uuid4())[:8]}"
    
    def _map_to_http_status(self, error_code: ErrorCode) -> int:
        """将业务错误码映射到HTTP状态码"""
        value = error_code.value
        
        if 20000 <= value < 30000:  # 2xx
            return 200
        elif 40000 <= value < 50000:  # 4xx
            return (value // 100) % 100 + 400
        elif 50000 <= value < 60000:  # 5xx
            return (value // 100) % 100 + 500
        else:
            return 500


# ============================================================================
# 具体的业务异常类
# ============================================================================

# 认证授权异常
class AuthenticationError(SmartGridException):
    """认证异常"""
    def __init__(self, message: str = "认证失败", detail: Optional[str] = None):
        super().__init__(ErrorCode.UNAUTHORIZED, message, detail)


class InvalidCredentialsError(SmartGridException):
    """无效凭据异常"""
    def __init__(self, message: str = "用户名或密码错误", detail: Optional[str] = None):
        super().__init__(ErrorCode.INVALID_CREDENTIALS, message, detail)


class TokenExpiredError(SmartGridException):
    """Token过期异常"""
    def __init__(self, message: str = "Token已过期", detail: Optional[str] = None):
        super().__init__(ErrorCode.TOKEN_EXPIRED, message, detail)


class PermissionDeniedError(SmartGridException):
    """权限不足异常"""
    def __init__(self, message: str = "权限不足", detail: Optional[str] = None):
        super().__init__(ErrorCode.INSUFFICIENT_PERMISSIONS, message, detail)


# 数据异常
class ValidationError(SmartGridException):
    """数据验证异常"""
    def __init__(self, message: str = "数据验证失败", detail: Optional[str] = None):
        super().__init__(ErrorCode.VALIDATION_ERROR, message, detail)


class ResourceNotFoundError(SmartGridException):
    """资源不存在异常"""
    def __init__(self, resource: str = "资源", message: Optional[str] = None, detail: Optional[str] = None):
        msg = message or f"{resource}不存在"
        super().__init__(ErrorCode.RESOURCE_NOT_FOUND, msg, detail)


class DuplicateResourceError(SmartGridException):
    """资源重复异常"""
    def __init__(self, resource: str = "资源", message: Optional[str] = None, detail: Optional[str] = None):
        msg = message or f"{resource}已存在"
        super().__init__(ErrorCode.DUPLICATE_RECORD, msg, detail)


# 服务异常
class DatabaseError(SmartGridException):
    """数据库异常"""
    def __init__(self, message: str = "数据库操作失败", detail: Optional[str] = None):
        super().__init__(ErrorCode.DATABASE_ERROR, message, detail)


class RedisError(SmartGridException):
    """Redis异常"""
    def __init__(self, message: str = "缓存操作失败", detail: Optional[str] = None):
        super().__init__(ErrorCode.REDIS_ERROR, message, detail)


class ModelServiceError(SmartGridException):
    """模型服务异常"""
    def __init__(self, message: str = "模型服务异常", detail: Optional[str] = None):
        super().__init__(ErrorCode.MODEL_ERROR, message, detail)


class ModelNotReadyError(SmartGridException):
    """模型未就绪异常"""
    def __init__(self, message: str = "模型服务未就绪", detail: Optional[str] = None):
        super().__init__(ErrorCode.MODEL_NOT_READY, message, detail)


class WeatherAPIError(SmartGridException):
    """气象API异常"""
    def __init__(self, message: str = "气象数据获取失败", detail: Optional[str] = None):
        super().__init__(ErrorCode.WEATHER_API_ERROR, message, detail)


class PredictionError(SmartGridException):
    """预测异常"""
    def __init__(self, message: str = "预测执行失败", detail: Optional[str] = None):
        super().__init__(ErrorCode.PREDICTION_ERROR, message, detail)


class ConfigurationError(SmartGridException):
    """配置异常"""
    def __init__(self, message: str = "配置错误", detail: Optional[str] = None):
        super().__init__(ErrorCode.CONFIGURATION_ERROR, message, detail)


# ============================================================================
# 错误处理工具函数
# ============================================================================

def get_error_message(error_code: ErrorCode) -> str:
    """获取错误码对应的中文描述"""
    error_messages = {
        # 客户端错误
        ErrorCode.VALIDATION_ERROR: "数据验证失败，请检查输入参数",
        ErrorCode.INVALID_PARAMETERS: "参数无效或格式错误",
        ErrorCode.MISSING_REQUIRED_FIELD: "缺少必需参数",
        ErrorCode.UNAUTHORIZED: "未授权访问，请先登录",
        ErrorCode.INSUFFICIENT_PERMISSIONS: "权限不足，无法执行此操作",
        ErrorCode.RESOURCE_NOT_FOUND: "请求的资源不存在",
        ErrorCode.DUPLICATE_RECORD: "记录已存在，无法重复创建",
        ErrorCode.RATE_LIMIT_EXCEEDED: "请求频率超限，请稍后重试",
        
        # 服务器错误
        ErrorCode.DATABASE_ERROR: "数据库操作失败，请稍后重试",
        ErrorCode.MODEL_ERROR: "模型服务异常，请稍后重试",
        ErrorCode.WEATHER_API_ERROR: "气象数据获取失败，请稍后重试",
        ErrorCode.PREDICTION_ERROR: "预测执行失败，请稍后重试",
        ErrorCode.CONFIGURATION_ERROR: "系统配置错误，请联系管理员",
        ErrorCode.INTERNAL_SERVER_ERROR: "系统内部错误，请稍后重试",
    }
    
    return error_messages.get(error_code, "未知错误")


def create_error_response(
    error_code: ErrorCode,
    message: Optional[str] = None,
    detail: Optional[str] = None,
    error_id: Optional[str] = None
) -> Dict[str, Any]:
    """创建标准化的错误响应"""
    
    response = {
        "error_id": error_id or f"err_{int(time.time() * 1000)}",
        "error_code": error_code.value,
        "error_name": error_code.name,
        "message": message or get_error_message(error_code),
        "detail": detail,
        "timestamp": datetime.now().isoformat()
    }
    
    return response


# 导入时间模块以便使用
import time
from datetime import datetime


class ErrorHandler:
    """错误处理器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def handle_exception(self, request: Request, exc: Exception) -> JSONResponse:
        """处理异常"""
        
        if isinstance(exc, SmartGridException):
            # 业务异常
            status_code = exc.status_code
            content = exc.detail
            
            # 日志记录
            self.logger.warning(
                f"业务异常: {exc.error_code.name} - {exc.message}",
                extra={
                    "error_id": exc.error_id,
                    "error_code": exc.error_code.value,
                    "path": request.url.path,
                    "method": request.method,
                    "client_ip": request.client.host if request.client else "unknown"
                }
            )
            
        elif isinstance(exc, HTTPException):
            # FastAPI HTTP异常
            status_code = exc.status_code
            content = create_error_response(
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
                message=exc.detail,
                detail="HTTP exception"
            )
            
            self.logger.warning(
                f"HTTP异常: {status_code} - {exc.detail}",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "client_ip": request.client.host if request.client else "unknown"
                }
            )
            
        else:
            # 未知异常
            status_code = 500
            content = create_error_response(
                error_code=ErrorCode.UNKNOWN_ERROR,
                message="系统内部错误，请稍后重试",
                detail=str(exc)
            )
            
            # 错误日志
            self.logger.error(
                f"未知异常: {type(exc).__name__} - {str(exc)}",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "client_ip": request.client.host if request.client else "unknown"
                },
                exc_info=True
            )
        
        return JSONResponse(
            status_code=status_code,
            content=content
        )