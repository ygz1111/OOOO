"""
智能电网负荷预测系统 - FastAPI 实时预测服务 (入口)

API 端点:
  POST /api/prediction/load   - 负荷预测 (24小时)
  GET  /api/weather/current    - 获取当前气象数据
  GET  /api/system/status      - 系统状态监控
  POST /api/prediction/batch   - 批量预测

特性:
  - 异步处理 (I/O 线程池 + CPU 线程池分离)
  - 请求参数验证 (Pydantic)
  - OpenAPI 自动文档 (/docs)
  - 超时控制 (30秒)
  - CORS 中间件
  - 全局异常处理
  - 请求日志中间件

架构:
  app.py (入口)
    ├── services/container.py         — 全局服务容器
    ├── services/prediction_pipeline.py — 预测管线
    ├── tasks/background.py            — 后台定时任务
    └── routers/
        ├── prediction.py  — 预测路由
        ├── weather.py     — 气象路由
        ├── system.py      — 系统状态路由
        ├── generation.py  — 光伏/风电路由
        ├── analytics.py   — 分析路由
        └── auth.py        — 认证路由

启动方式:
    cd backend
    python -m uvicorn realtime_api.app:app --host 0.0.0.0 --port 8000 --reload

    或直接运行:
    python realtime_api/app.py

作者: 毕业设计项目
"""

import os
import sys
import time
import uuid
import asyncio
from contextlib import asynccontextmanager

# 加载 .env 环境变量 (必须在其他模块导入之前)
from dotenv import load_dotenv
load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        '.env',
    )
)

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 项目路径
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# 导入配置
from realtime_api.config_manager import get_config
config = get_config()

# 导入结构化日志
from realtime_api.structured_logger import get_logger
logger = get_logger(__name__)

# 导入错误处理
from realtime_api.error_handling import ErrorHandler, SmartGridException

# 导入数据库
from realtime_api.database import init_database, close_database, db_manager

# 导入服务容器
from realtime_api.services.container import (
    services,
    init_services,
    release_services,
    eastern_now,
)

# 导入后台任务
from realtime_api.tasks.background import (
    start_background_tasks,
    stop_background_tasks,
)

# 导入认证中间件
from realtime_api.auth import AuthMiddleware

# 导入路由
from realtime_api.routers.auth import router as auth_router
from realtime_api.routers.analytics import router as analytics_router
from realtime_api.routers.prediction import router as prediction_router
from realtime_api.routers.weather import router as weather_router
from realtime_api.routers.system import router as system_router
from realtime_api.routers.generation import router as generation_router

# 导入 schemas (用于错误响应)
from realtime_api.schemas import ErrorResponse

# ============================================================================
# 记录启动信息
# ============================================================================

logger.info(f"启动环境: {config.environment}")
if config.is_production:
    logger.info("生产环境模式")
else:
    logger.info("开发环境模式")

logger.info(
    "智能电网负荷预测系统启动完成",
    extra={
        "environment": config.environment,
        "version": config.get('system.version'),
        "api_port": config.get('api.port'),
    }
)


# ============================================================================
# 生命周期管理
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时加载模型，关闭时释放资源"""
    logger.info("=" * 60)
    logger.info("智能电网负荷预测系统 - 启动中")
    logger.info("=" * 60)

    services.start_time = time.time()

    # 0. 初始化数据库
    logger.info("[0/8] 初始化 MySQL 数据库连接池...")
    try:
        await init_database()
        db_health = await db_manager.health_check()
        logger.info(f"   数据库连接: {'✅ 成功' if db_health['status'] == 'healthy' else '❌ 失败'}")
        logger.info(f"   响应时间: {db_health.get('response_time_ms', 'N/A')}ms")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {e}")
        logger.warning("   将继续启动，但数据库功能可能不可用")

    # 1~8. 初始化业务服务
    init_services()

    logger.info(f"   API 文档: http://localhost:8000/docs")
    logger.info(f"   MySQL 数据库: {'已连接' if services.inference_service.is_ready() else '连接异常'}")

    # 启动后台定时任务
    start_background_tasks()

    yield

    # ── 关闭流程 ──
    stop_background_tasks()
    release_services()

    try:
        await close_database()
        logger.info("✅ 数据库连接已关闭")
    except Exception as e:
        logger.warning(f"数据库关闭时遇到异常: {e}")

    logger.info("✅ 资源已释放")


# ============================================================================
# FastAPI 应用
# ============================================================================

api_config = config.get_api_config()
app = FastAPI(
    title=config.get('system.name', '智能电网负荷预测系统'),
    description="""
    ## 实时电力负荷预测 API

    基于深度学习的电力负荷预测系统，整合4个模型（LSTM、BiGRU、TCN、Transformer）
    进行加权集成预测，同时提供光伏发电估算和净负荷计算。

    ### 功能
    - **负荷预测**: 24小时系统负荷预测
    - **气象数据**: 获取新英格兰地区6个气象站实时数据
    - **光伏估算**: 基于辐射数据估算光伏发电量
    - **系统监控**: 推理性能、模型状态监控
    - **用户认证**: JWT认证与RBAC权限控制
    - **访问控制**: API权限管理与操作审计

    ### 数据流
    ```
    Open-Meteo API → 气象数据 → 特征工程(38维) → 归一化 → 模型推理 → 预测结果
    ```
    """,
    version=config.get('system.version', '1.1.0'),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# 初始化错误处理器
error_handler = ErrorHandler()

# ============================================================================
# 中间件
# ============================================================================

# CORS
_default_origins = (
    "http://localhost:3000,http://localhost:3001,http://localhost:5173,"
    "http://127.0.0.1:3000,http://127.0.0.1:3001"
)
_cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", _default_origins).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 认证中间件
app.add_middleware(AuthMiddleware)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """请求日志和耗时记录中间件"""
    start_time = time.time()

    method = request.method
    path = request.url.path
    client = request.client.host if request.client else "unknown"

    logger.info(f"→ {method} {path} from {client}")

    # 超时控制
    try:
        response = await asyncio.wait_for(
            call_next(request),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.error(f"⏰ 请求超时: {method} {path}")
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=ErrorResponse(
                error="timeout",
                message="请求处理超时 (30秒)",
                timestamp=eastern_now().isoformat(),
            ).model_dump(mode="json"),
        )

    process_time = (time.time() - start_time) * 1000
    logger.info(f"← {method} {path} {response.status_code} ({process_time:.1f}ms)")

    response.headers["X-Process-Time"] = f"{process_time:.1f}ms"

    # 异步写入 API 请求日志到数据库（非阻塞）
    async def _persist_api_log():
        try:
            from realtime_api.crud import APILogsCRUD
            request_id = str(uuid.uuid4())
            request_size = None
            content_length = request.headers.get('content-length')
            if content_length:
                request_size = int(content_length)

            response_size = None
            if hasattr(response, 'body') and response.body:
                response_size = len(response.body)

            user_agent = (
                request.headers.get('user-agent', '')[:500]
                if request.headers.get('user-agent') else None
            )

            await APILogsCRUD.insert_log(
                request_id=request_id,
                endpoint=path,
                method=method,
                status_code=response.status_code,
                response_time_ms=round(process_time, 1),
                request_size_bytes=request_size,
                response_size_bytes=response_size,
                client_ip=client,
                user_agent=user_agent,
                error_message=None if response.status_code < 400 else f"HTTP {response.status_code}"
            )
        except Exception as e:
            logger.warning(f"API日志入库失败（非阻塞）: {e}")

    asyncio.create_task(_persist_api_log())

    return response


# ============================================================================
# 异常处理
# ============================================================================

@app.exception_handler(SmartGridException)
async def smartgrid_exception_handler(request: Request, exc: SmartGridException):
    """智能电网业务异常处理"""
    return await error_handler.handle_exception(request, exc)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常处理"""
    return await error_handler.handle_exception(request, exc)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            message="服务器内部错误，请稍后重试",
            timestamp=eastern_now().isoformat(),
        ).model_dump(mode="json"),
    )


# ============================================================================
# 包含路由
# ============================================================================

app.include_router(auth_router)
app.include_router(analytics_router)
app.include_router(prediction_router)
app.include_router(weather_router)
app.include_router(system_router)
app.include_router(generation_router)


# ============================================================================
# 根路径
# ============================================================================

@app.get("/", tags=["根"])
async def root():
    """根路径 - 服务信息"""
    return {
        "service": "智能电网负荷预测系统",
        "version": "1.1.0",
        "features": ["负荷预测", "光伏ML预测", "风电估算", "气象数据", "用户认证", "访问控制"],
        "docs": "/docs",
        "endpoints": [
            "POST /api/prediction/load",
            "GET  /api/weather/current",
            "GET  /api/system/status",
            "GET  /api/solar-generation - 光伏ML预测",
            "GET  /api/solar-generation/model-info - 光伏模型信息",
            "GET  /api/wind-generation",
            "GET  /api/wind-generation/power-curve",
            "POST /api/prediction/batch (需认证)",
            "GET  /api/prediction/history",
            "GET  /api/weather/history",
            "GET  /api/system/metrics (需认证)",
        ],
        "health_checks": [
            "GET  /api/health - 综合健康检查",
            "GET  /api/health/liveness - 存活检查",
            "GET  /api/health/readiness - 就绪检查",
        ],
        "analytics": [
            "GET  /api/analytics/accuracy/stats",
            "GET  /api/analytics/accuracy/recent",
            "GET  /api/analytics/drift/check",
            "GET  /api/analytics/quality/stats",
            "POST /api/analytics/quality/validate",
            "GET  /api/analytics/comparison/models",
            "GET  /api/analytics/temporal/trends",
            "GET  /api/analytics/error/distribution",
            "GET  /api/analytics/patterns/load",
            "GET  /api/analytics/report/comprehensive",
            "GET  /api/analytics/dashboard/metrics",
        ],
        "auth": [
            "POST /auth/register",
            "POST /auth/login",
            "GET  /auth/me",
        ],
    }


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    host = api_config.get('host', '0.0.0.0')
    port = api_config.get('port', 8000)
    debug_mode = api_config.get('debug', False)

    logger.info(f"🚀 启动API服务: {host}:{port} (调试模式: {debug_mode})")

    uvicorn.run(
        "realtime_api.app:app",
        host=host,
        port=port,
        reload=debug_mode,
        log_level="info",
    )
