"""
智能电网负荷预测系统 - MySQL数据库连接与Session管理

企业级数据库操作模块，支持：
- 连接池管理 (async)
- 自动重连机制
- SQL注入防护
- 事务管理
- 异常处理和日志

作者: 毕业设计项目
"""

import os
import time
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Dict, Any

import mysql.connector
from mysql.connector import pooling, Error as MySQLError
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

# SQLAlchemy async 支持 (用于认证模块的 AsyncSession)
try:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    _SQLALCHEMY_ASYNC_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_ASYNC_AVAILABLE = False
    logger_warning = logging.getLogger("database")
    logger_warning.warning("SQLAlchemy async 未安装，认证模块的 get_db_async 将不可用。请安装: pip install sqlalchemy[asyncio] aiomysql")


# 配置日志
logger = logging.getLogger("database")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class DatabaseConfig:
    """数据库配置管理"""
    
    def __init__(self):
        # 从环境变量读取配置，使用默认值
        self.host = os.getenv("MYSQL_HOST", "localhost")
        self.port = int(os.getenv("MYSQL_PORT", 3306))
        self.database = os.getenv("MYSQL_DATABASE", "OOOO")
        self.user = os.getenv("MYSQL_USER", "root")
        self.password = str(os.getenv("MYSQL_PASSWORD", ""))
        if not self.password or self.password == "":
            logger.warning("MYSQL_PASSWORD 真环境变量未设置，请在 .env 文件中配置")
        self.pool_size = int(os.getenv("MYSQL_POOL_SIZE", 10))
        self.pool_name = os.getenv("MYSQL_POOL_NAME", "smartgrid_pool")
        self.pool_reset_session = True
        self.autocommit = True
        self.use_unicode = True
        self.charset = 'utf8mb4'
        
        # SSL配置（可选）
        self.use_ssl = os.getenv("MYSQL_USE_SSL", "False").lower() == "true"
    
    def get_connection_params(self) -> Dict[str, Any]:
        """获取连接参数字典"""
        params = {
            'host': str(self.host),
            'port': int(self.port),
            'database': str(self.database),
            'user': str(self.user),
            'password': str(self.password),
            'pool_size': int(self.pool_size),
            'pool_name': str(self.pool_name),
            'pool_reset_session': self.pool_reset_session,
            'autocommit': self.autocommit,
            'use_unicode': self.use_unicode,
            'charset': self.charset,
            'use_pure': True,  # 避免 C 扩展在 Python 3.12 上的兼容性问题
        }
        
        if self.use_ssl:
            params['ssl_disabled'] = False
        
        return params


class DatabaseManager:
    """数据库管理器 - 单例模式"""
    
    _instance = None
    _pool = None
    _config = None
    _initialized = False
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._config = DatabaseConfig()
            # 专用线程池执行同步 mysql-connector 调用：
            # 在 asyncio server（uvicorn/hypercorn）进程中，全局默认 executor
            # 的 run_in_executor 回调不唤醒事件循环导致 DB 调用挂起；
            # 专用线程池 + wrap_future 规避该问题（登录链路用 aiomysql 纯 async 不受影响）
            self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dbpool")
            self._initialized = True
    
    async def initialize(self) -> None:
        """异步初始化数据库连接池"""
        async with self._lock:
            if self._pool is None:
                try:
                    logger.info("正在初始化MySQL连接池...")
                    
                    # 同步创建连接池（mysql-connector-python暂不支持asyncio natively）
                    loop = asyncio.get_event_loop()
                    
                    def create_pool():
                        return pooling.MySQLConnectionPool(**self._config.get_connection_params())
                    
                    self._pool = await asyncio.wrap_future(self._executor.submit(create_pool))
                    
                    # 测试连接
                    test_conn = await self.get_connection()
                    await self.release_connection(test_conn)
                    
                    logger.info(f"MySQL连接池初始化成功 - 池大小: {self._config.pool_size}")
                except Exception as e:
                    logger.error(f"数据库连接池初始化失败: {str(e)}")
                    raise
    
    async def get_connection(self) -> mysql.connector.MySQLConnection:
        """从连接池获取连接的异步包装"""
        if self._pool is None:
            await self.initialize()
        
        try:
            loop = asyncio.get_event_loop()
            connection = await asyncio.wrap_future(self._executor.submit(self._pool.get_connection))
            logger.debug("成功从连接池获取数据库连接")
            return connection
        except Exception as e:
            logger.error(f"获取数据库连接失败: {str(e)}")
            raise
    
    async def release_connection(self, connection: mysql.connector.MySQLConnection) -> None:
        """释放连接到连接池"""
        try:
            await asyncio.wrap_future(self._executor.submit(connection.close))
            logger.debug("连接已释放回连接池")
        except Exception as e:
            logger.warning(f"释放连接时发生异常: {str(e)}")
    
    @asynccontextmanager
    async def get_db(self) -> AsyncGenerator[mysql.connector.MySQLConnection, None]:
        """数据库会话上下文管理器"""
        connection = None
        try:
            connection = await self.get_connection()
            yield connection
        finally:
            if connection:
                await self.release_connection(connection)
    
    async def execute_sql(self, sql: str, params: Optional[tuple] = None) -> list:
        """执行SQL查询并返回结果"""
        async with self.get_db() as connection:
            cursor = None
            try:
                loop = asyncio.get_event_loop()
                cursor = connection.cursor(dictionary=True)
                
                _fut = self._executor.submit(
                    lambda: cursor.execute(sql, params) or cursor.fetchall()
                )
                result = await asyncio.wrap_future(_fut)

                return result if result is not None else []
            except Exception as e:
                logger.error(f"SQL执行失败: {sql}, 参数: {params}, 错误: {str(e)}")
                raise
            finally:
                if cursor:
                    cursor.close()
    
    async def execute_sql_scalar(self, sql: str, params: Optional[tuple] = None) -> Any:
        """执行SQL并返回单个值"""
        result = await self.execute_sql(sql, params)
        if result and len(result) > 0:
            row = result[0]
            return list(row.values())[0] if row else None
        return None
    
    async def execute_sql_insert(self, sql: str, params: Optional[tuple] = None) -> int:
        """执行INSERT语句并返回最后插入的ID"""
        async with self.get_db() as connection:
            cursor = None
            try:
                loop = asyncio.get_event_loop()
                cursor = connection.cursor()
                
                await asyncio.wrap_future(self._executor.submit(lambda: cursor.execute(sql, params)))
                insert_id = cursor.lastrowid
                
                return insert_id
            except Exception as e:
                logger.error(f"INSERT执行失败: {sql}, 参数: {params}, 错误: {str(e)}")
                raise
            finally:
                if cursor:
                    cursor.close()
    
    async def execute_sql_many(self, sql: str, params_list: list) -> int:
        """批量执行SQL"""
        async with self.get_db() as connection:
            cursor = None
            try:
                loop = asyncio.get_event_loop()
                cursor = connection.cursor()
                
                result = await asyncio.wrap_future(
                    self._executor.submit(
                        lambda: cursor.executemany(sql, params_list) or cursor.rowcount
                    )
                )
                
                count = result if result is not None else 0
                
                return count
            except Exception as e:
                logger.error(f"批量SQL执行失败: {sql}, 参数数量: {len(params_list)}, 错误: {str(e)}")
                raise
            finally:
                if cursor:
                    cursor.close()
    
    async def health_check(self) -> Dict[str, Any]:
        """数据库健康检查"""
        try:
            start_time = time.time()
            
            # 测试执行一个简单查询
            result = await self.execute_sql("SELECT 1 as test")
            response_time = (time.time() - start_time) * 1000
            
            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "connection_pool_active": self._pool is not None,
                "test_query_result": result[0]['test'] if result else None
            }
        except Exception as e:
            logger.error(f"数据库健康检查失败: {str(e)}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def close(self) -> None:
        """关闭连接池（谨慎使用）"""
        if self._pool:
            # mysql.connector的连接池没有显式的close方法
            # 连接会在垃圾回收时自动关闭
            self._pool = None
            logger.info("数据库连接池已标记为关闭")


# ============================================================================
# SQLAlchemy Async Session (用于认证模块)
# ============================================================================

_async_engine = None
_AsyncSessionLocal = None


def _init_async_engine():
    """初始化 SQLAlchemy 异步引擎"""
    global _async_engine, _AsyncSessionLocal
    if not _SQLALCHEMY_ASYNC_AVAILABLE:
        return
    if _async_engine is not None:
        return

    config = DatabaseConfig()
    # 构建异步连接 URL: mysql+aiomysql://user:password@host:port/database
    url = f"mysql+aiomysql://{config.user}:{config.password}@{config.host}:{config.port}/{config.database}?charset={config.charset}"

    _async_engine = create_async_engine(
        url,
        pool_size=config.pool_size,
        pool_pre_ping=True,
        echo=False,
    )
    _AsyncSessionLocal = async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info("SQLAlchemy 异步引擎初始化完成")


async def get_db_async() -> AsyncGenerator[AsyncSession, None]:
    """
    获取 SQLAlchemy 异步会话 (用于认证模块的 Depends)

    用法:
        @app.get("/protected")
        async def protected(db: AsyncSession = Depends(get_db_async)):
            ...
    """
    if not _SQLALCHEMY_ASYNC_AVAILABLE:
        raise RuntimeError(
            "SQLAlchemy async 未安装。请运行: pip install sqlalchemy[asyncio] aiomysql"
        )
    if _AsyncSessionLocal is None:
        _init_async_engine()
    if _AsyncSessionLocal is None:
        raise RuntimeError("异步数据库引擎初始化失败")

    async with _AsyncSessionLocal() as session:
        # 由 async with 的 __aexit__ 统一管理 close/回滚；
        # 此前 finally 里再显式 close 会触发
        # IllegalStateChangeError: "Method 'close()' can't be called here"
        yield session


# 全局数据库管理器实例
db_manager = DatabaseManager()


def get_db_manager():
    """FastAPI 依赖: 返回全局数据库管理器实例"""
    return db_manager


async def init_database() -> None:
    """应用启动时初始化数据库"""
    await db_manager.initialize()


async def close_database() -> None:
    """应用关闭时清理数据库连接"""
    await db_manager.close()


__all__ = [
    'DatabaseManager',
    'DatabaseConfig',
    'db_manager',
    'get_db_manager',
    'init_database',
    'close_database',
    'get_db_async',
]