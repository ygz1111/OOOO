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
        ├── generation.py  — 光伏路由
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

# 任何 ``realtime_api`` 导入都必须位于根目录 .env 加载之后。导入子模块时
# Python 会先执行包的 ``__init__.py``，而该文件又会间接初始化配置单例；若
# 提前导入，JWT/数据库等环境变量会被配置文件默认值永久缓存到当前进程。
from realtime_api.utils.background import fire_and_forget

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
    active_model_runtime_stats,
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
from realtime_api.routers.price import router as price_router

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

    # 修复：Windows 下 asyncio 全局默认 executor（run_in_executor(None)/to_thread）
    # 在 asyncio server（uvicorn/hypercorn）中完成回调不唤醒事件循环，
    # 导致线程池任务（DB/健康检查/系统采样）挂起。显式设置专用默认 executor。
    try:
        from concurrent.futures import ThreadPoolExecutor
        _loop = asyncio.get_running_loop()
        _loop.set_default_executor(
            ThreadPoolExecutor(max_workers=16, thread_name_prefix="asyncio-default")
        )
        logger.info("✅ 已设置专用默认线程池 (asyncio-default)")
    except Exception as e:
        logger.warning(f"设置默认线程池失败: {e}")

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
    runtime = active_model_runtime_stats()
    logger.info(
        f"   预测模型: {runtime['backend']} "
        f"({runtime['models_loaded']}/{runtime['models_total']} ready)"
    )

    # 启动后台定时任务
    if str(config.get('models.engines.inference_mode', 'live')).lower() == 'live':
        from realtime_api.services.live_forecast import start_live_preload
        start_live_preload()
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

    基于 TensorFlow 的智能电网多任务预测系统，使用相互独立的负荷预测、
    电价分位预测和光伏预测三个生产模型，并提供净负荷计算。

    ### 功能
    - **负荷预测**: 24小时系统负荷预测
    - **气象数据**: 获取新英格兰地区6个气象站实时数据
    - **电价预测**: 未来24小时 P10/P50/P90 分位电价预测
    - **光伏预测**: TensorFlow 模型预测 ISO-NE BTM 光伏发电量
    - **系统监控**: 推理性能、模型状态监控
    - **用户认证**: JWT认证与RBAC权限控制
    - **访问控制**: API权限管理与操作审计

    ### 数据流
    ```
    ISO-NE + Open-Meteo → 任务特征工程 → TensorFlow 模型推理 → 预测结果
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

# Prometheus 指标采集（轻量中间件 + /metrics 端点）
from realtime_api.metrics import metrics_middleware, metrics_endpoint

@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    return await metrics_middleware(request, call_next)

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return await metrics_endpoint()


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """请求日志和耗时记录中间件"""
    start_time = time.time()

    method = request.method
    path = request.url.path
    client = request.client.host if request.client else "unknown"

    logger.info(f"→ {method} {path} from {client}")

    # 超时控制。预测总览需要拉取/聚合 6 个站点的历史气象，冷缓存或网络波动时
    # 明显超过普通 API 的 30 秒；此前统一 30 秒会取消正在执行的数据库/线程池任务，
    # 既返回 504 又可能留下 SQLAlchemy 会话关闭竞争。为重计算端点使用更合理的上限。
    long_running_paths = {
        "/api/prediction/load",
        "/api/prediction/overview",
        "/api/prediction/batch",
        "/api/price/forecast",
        "/api/solar-generation",
        "/api/analytics/operations/situation",
        "/api/analytics/operations/feature-sensitivity",
        "/api/analytics/backtest/date",
        "/api/price/backtest",
    }
    timeout_seconds = 120.0 if path in long_running_paths else 45.0
    try:
        response = await asyncio.wait_for(
            call_next(request),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.error(f"⏰ 请求超时: {method} {path} ({timeout_seconds:.0f}s)")
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=ErrorResponse(
                error="timeout",
                message=f"请求处理超时 ({timeout_seconds:.0f}秒)",
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

    fire_and_forget(_persist_api_log, "api_log")

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
app.include_router(price_router)


# ============================================================================
# 根路径
# ============================================================================

@app.get("/", tags=["根"])
async def root():
    """根路径 - 服务信息"""
    return {
        "service": "智能电网负荷预测系统",
        "version": "1.1.0",
        "features": ["负荷预测", "电价预测", "光伏ML预测", "气象数据", "用户认证", "访问控制"],
        "docs": "/docs",
        "endpoints": [
            "POST /api/prediction/load",
            "GET  /api/prediction/overview",
            "GET  /api/price/forecast",
            "GET  /api/price/backtest",
            "GET  /api/price/model-info",
            "GET  /api/weather/current",
            "GET  /api/system/status",
            "GET  /api/solar-generation - 光伏ML预测",
            "GET  /api/solar-generation/backtest - 光伏历史回测",
            "GET  /api/solar-generation/model-info - 光伏模型信息",
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
            "POST /api/auth/register",
            "POST /api/auth/login",
            "GET  /api/auth/me",
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
