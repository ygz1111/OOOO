#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 结构化日志系统

提供结构化JSON日志、多级别日志输出和日志轮转

作者: 毕业设计项目
"""

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
from pathlib import Path

import threading
from concurrent.futures import ThreadPoolExecutor

from realtime_api.config_manager import get_config


class StructuredJSONFormatter(logging.Formatter):
    """结构化JSON日志格式器"""
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为JSON"""
        
        # 基础日志字段
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread_id": threading.get_ident(),
            "process_id": os.getpid(),
        }
        
        # 添加异常信息（如果有）
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            log_entry["traceback"] = self.formatException(record.exc_info)
        
        # 添加额外字段
        if hasattr(record, 'extra') and record.extra:
            log_entry.update(record.extra)
        
        # 添加业务上下文信息（如果有）
        if hasattr(record, 'request_id'):
            log_entry["request_id"] = record.request_id
        
        if hasattr(record, 'user_id'):
            log_entry["user_id"] = record.user_id
        
        if hasattr(record, 'session_id'):
            log_entry["session_id"] = record.session_id
        
        if hasattr(record, 'correlation_id'):
            log_entry["correlation_id"] = record.correlation_id
        
        # 添加性能指标（如果有）
        if hasattr(record, 'duration_ms'):
            log_entry["duration_ms"] = record.duration_ms
        
        if hasattr(record, 'response_time_ms'):
            log_entry["response_time_ms"] = record.response_time_ms
        
        # 添加标签（如果有）
        if hasattr(record, 'tags'):
            log_entry["tags"] = record.tags
        
        return json.dumps(log_entry, ensure_ascii=False, separators=(',', ':'))


class ContextLogger:
    """带有上下文的日志记录器"""
    
    def __init__(self, name: str, request_id: Optional[str] = None):
        self.logger = logging.getLogger(name)
        self.request_id = request_id or str(uuid.uuid4())
        self.user_id = None
        self.session_id = None
        self.correlation_id = None
        self.tags = []
    
    def bind(self, **kwargs) -> 'ContextLogger':
        """绑定上下文信息"""
        bound_logger = ContextLogger(self.logger.name, self.request_id)
        bound_logger.logger = self.logger
        bound_logger.request_id = self.request_id
        bound_logger.user_id = kwargs.get('user_id', self.user_id)
        bound_logger.session_id = kwargs.get('session_id', self.session_id)
        bound_logger.correlation_id = kwargs.get('correlation_id', self.correlation_id)
        bound_logger.tags = kwargs.get('tags', self.tags[:])
        return bound_logger
    
    def add_tag(self, tag: str) -> 'ContextLogger':
        """添加标签"""
        if tag not in self.tags:
            self.tags.append(tag)
        return self
    
    def remove_tag(self, tag: str) -> 'ContextLogger':
        """移除标签"""
        if tag in self.tags:
            self.tags.remove(tag)
        return self
    
    def _log(self, level: int, msg: str, *args, **kwargs):
        """执行日志记录"""
        extra = kwargs.get('extra', {})
        
        # 添加调用者信息
        import inspect
        frame = inspect.currentframe().f_back.f_back
        extra['caller_file'] = frame.f_code.co_filename
        extra['caller_line'] = frame.f_lineno
        
        # 添加上下文信息
        context_info = {
            'request_id': self.request_id,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'correlation_id': self.correlation_id,
            'tags': self.tags[:],
        }
        extra.update(context_info)
        
        kwargs['extra'] = extra
        
        self.logger.log(level, msg, *args, **kwargs)
    
    def debug(self, msg: str, *args, **kwargs):
        """DEBUG级日志"""
        self._log(logging.DEBUG, msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        """INFO级日志"""
        self._log(logging.INFO, msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        """WARNING级日志"""
        self._log(logging.WARNING, msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        """ERROR级日志"""
        self._log(logging.ERROR, msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        """CRITICAL级日志"""
        self._log(logging.CRITICAL, msg, *args, **kwargs)
    
    def exception(self, msg: str, *args, **kwargs):
        """异常日志"""
        kwargs['exc_info'] = True
        self._log(logging.ERROR, msg, *args, **kwargs)


class AsyncStructuredLogger:
    """异步结构化日志记录器"""
    
    def __init__(self, name: str):
        self.logger = ContextLogger(name)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Logger")
    
    def log_async(self, level: int, msg: str, **kwargs):
        """异步记录日志"""
        future = self.executor.submit(self._log_sync, level, msg, **kwargs)
        return future
    
    def _log_sync(self, level: int, msg: str, **kwargs):
        """同步日志记录（在子线程中执行）"""
        try:
            if level == logging.DEBUG:
                self.logger.debug(msg, **kwargs)
            elif level == logging.INFO:
                self.logger.info(msg, **kwargs)
            elif level == logging.WARNING:
                self.logger.warning(msg, **kwargs)
            elif level == logging.ERROR:
                self.logger.error(msg, **kwargs)
            elif level == logging.CRITICAL:
                self.logger.critical(msg, **kwargs)
        except Exception as e:
            # 防止日志记录错误导致程序崩溃
            print(f"Log error: {e}")
    
    def debug_async(self, msg: str, **kwargs):
        """异步DEBUG日志"""
        return self.log_async(logging.DEBUG, msg, **kwargs)
    
    def info_async(self, msg: str, **kwargs):
        """异步INFO日志"""
        return self.log_async(logging.INFO, msg, **kwargs)
    
    def warning_async(self, msg: str, **kwargs):
        """异步WARNING日志"""
        return self.log_async(logging.WARNING, msg, **kwargs)
    
    def error_async(self, msg: str, **kwargs):
        """异步ERROR日志"""
        return self.log_async(logging.ERROR, msg, **kwargs)
    
    def shutdown(self):
        """关闭异步日志记录器"""
        self.executor.shutdown(wait=True)


class LogRotator:
    """日志轮转器"""
    
    def __init__(self, log_dir: str = "logs", max_file_size_mb: int = 100, backup_count: int = 5):
        self.log_dir = Path(log_dir)
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.backup_count = backup_count
        self.log_dir.mkdir(exist_ok=True)
    
    def rotate_file(self, filename: str) -> bool:
        """执行文件轮转"""
        file_path = self.log_dir / filename
        
        if not file_path.exists():
            return False
        
        file_size = file_path.stat().st_size
        
        if file_size < self.max_file_size_bytes:
            return False
        
        # 执行轮转：app.log -> app.log.1, app.log.1 -> app.log.2, etc.
        for i in range(self.backup_count - 1, 0, -1):
            old_file = self.log_dir / f"{filename}.{i}"
            new_file = self.log_dir / f"{filename}.{i + 1}"
            
            if old_file.exists():
                if new_file.exists():
                    new_file.unlink()
                old_file.rename(new_file)
        
        # 将当前文件移到 .1
        backup_file = self.log_dir / f"{filename}.1"
        if backup_file.exists():
            backup_file.unlink()
        file_path.rename(backup_file)
        
        return True


class StructuredLoggingManager:
    """结构化日志管理器"""
    
    _instance = None
    _loggers = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StructuredLoggingManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.config = get_config()
            self.rotator = LogRotator()
            self._setup_logging()
            self._initialized = True
    
    def _setup_logging(self):
        """设置日志系统"""
        
        # 获取日志配置
        log_config = self.config.get_logging_config()
        log_level = getattr(logging, log_config.get('level', 'INFO'))
        
        # 创建根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # 允许所有级别
        
        # 清除现有处理器
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 1. 控制台处理器（始终存在）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_formatter = StructuredJSONFormatter()
        console_handler.setFormatter(console_formatter)
        console_handler.addFilter(self._console_filter)
        root_logger.addHandler(console_handler)
        
        # 2. 文件处理器（如果启用）
        if log_config.get('file', {}).get('enabled', False):
            log_path = log_config['file'].get('path', 'logs/app.log')
            log_dir = Path(log_path).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # 日志轮转：单文件 10MB，保留 5 个备份
            file_handler = RotatingFileHandler(
                log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
            file_formatter = StructuredJSONFormatter()
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        
        # 3. 错误文件处理器（仅ERROR和CRITICAL）
        error_log_path = Path('logs/error.log')
        error_log_path.parent.mkdir(exist_ok=True)
        
        error_handler = RotatingFileHandler(
            error_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_formatter = StructuredJSONFormatter()
        error_handler.setFormatter(error_formatter)
        root_logger.addHandler(error_handler)
        
        # 4. 访问日志处理器
        access_log_path = Path('logs/access.log')
        access_log_path.parent.mkdir(exist_ok=True)
        
        access_handler = RotatingFileHandler(
            access_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
        )
        access_handler.setLevel(logging.INFO)
        access_formatter = StructuredJSONFormatter()
        access_handler.setFormatter(access_formatter)
        access_handler.addFilter(self._access_log_filter)
        root_logger.addHandler(access_handler)
    
    def _console_filter(self, record: logging.LogRecord) -> bool:
        """控制台输出过滤器 - 只输出当前级别的日志"""
        log_config = self.config.get_logging_config()
        current_level = getattr(logging, log_config.get('level', 'INFO'))
        return record.levelno >= current_level
    
    def _access_log_filter(self, record: logging.LogRecord) -> bool:
        """访问日志过滤器 - 只记录包含request_id的日志"""
        extra = getattr(record, 'extra', {})
        return 'request_id' in extra and hasattr(record, 'request_id')
    
    def get_logger(self, name: str, request_id: Optional[str] = None) -> ContextLogger:
        """获取日志记录器"""
        
        if name not in self._loggers:
            self._loggers[name] = ContextLogger(name, request_id)
        
        return self._loggers[name].bind(request_id=request_id or str(uuid.uuid4()))
    
    def log_request_start(self, method: str, path: str, request_id: str, client_ip: str = "unknown"):
        """记录请求开始"""
        logger = self.get_logger("api.access", request_id)
        logger.info(
            f"🔄 API请求开始: {method} {path}",
            extra={
                "api_method": method,
                "api_path": path,
                "client_ip": client_ip,
                "event_type": "request_start"
            }
        )
    
    def log_request_end(self, method: str, path: str, request_id: str, 
                       status_code: int, duration_ms: float, client_ip: str = "unknown"):
        """记录请求结束"""
        logger = self.get_logger("api.access", request_id)
        logger.info(
            f"✅ API请求完成: {method} {path} - {status_code} ({duration_ms:.1f}ms)",
            extra={
                "api_method": method,
                "api_path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
                "event_type": "request_end"
            }
        )
    
    def log_prediction(self, request_id: str, location: str, prediction_duration_ms: float,
                      model_count: int = 4):
        """记录预测操作"""
        logger = self.get_logger("api.prediction", request_id)
        logger.info(
            f"📊 负荷预测完成 - 位置: {location}",
            extra={
                "prediction_location": location,
                "prediction_duration_ms": prediction_duration_ms,
                "models_used": model_count,
                "event_type": "load_prediction"
            }
        )
    
    def log_weather_data_fetch(self, request_id: str, location_count: int, 
                              response_time_ms: float):
        """记录气象数据获取"""
        logger = self.get_logger("api.weather", request_id)
        logger.info(
            f"🌤️ 气象数据获取完成 - {location_count} 个站点",
            extra={
                "weather_stations_count": location_count,
                "fetch_duration_ms": response_time_ms,
                "event_type": "weather_data_fetch"
            }
        )


# 全局日志管理器
logging_manager = StructuredLoggingManager()


def get_logger(name: str = "app", request_id: Optional[str] = None) -> ContextLogger:
    """获取结构化日志记录器"""
    return logging_manager.get_logger(name, request_id)


def get_request_logger(request_id: Optional[str] = None) -> ContextLogger:
    """获取请求级日志记录器"""
    return get_logger("request", request_id)


def get_api_logger(request_id: Optional[str] = None) -> ContextLogger:
    """获取API日志记录器"""
    return get_logger("api", request_id)


def get_prediction_logger(request_id: Optional[str] = None) -> ContextLogger:
    """获取预测日志记录器"""
    return get_logger("prediction", request_id)