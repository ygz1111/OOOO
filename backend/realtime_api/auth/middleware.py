"""
智能电网负荷预测系统 - 认证中间件

功能:
- JWT令牌验证
- API访问日志记录
- 权限检查
- 请求审计

author: 毕业设计项目
"""

from realtime_api.utils.background import fire_and_forget
import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
import logging

from realtime_api.database import get_db_async
from realtime_api.crud.auth_crud import AuthCRUD
from realtime_api.schemas.auth import APIAccessLogCreate


# 日志配置
logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    认证中间件 - 拦截所有API请求
    
    处理流程:
    1. 提取JWT令牌
    2. 验证令牌有效性
    3. 记录访问日志
    4. 审计敏感操作
    """

    def __init__(self, app, exclude_paths: list = None):
        super().__init__(app)
        
        # 排除认证的路径(公开API)
        # 注意：这里每一项都必须是"明确的公开端点"。绝不能出现单独的 '/'，
        # 否则 _should_skip_auth 的前缀匹配会让所有请求跳过认证。
        self.exclude_paths = exclude_paths or [
            # API 文档（只读）
            '/docs',
            '/redoc',
            '/openapi.json',
            # 根路径信息
            '/',
            # 健康检查（Docker healthcheck 依赖）
            '/health',
            '/api/health',
            # 认证入口（仅这几个公开；/api/auth/me 等受保护端点不在白名单内）
            '/api/auth/login',
            '/api/auth/register',
            '/api/auth/reset',
            '/api/auth/health',
            # 令牌刷新：用 refresh token 自证身份，不受 access token 中间件拦截
            '/api/auth/refresh',
            # 天气当前值与系统状态（无敏感数据，供前端免登录展示）
            '/api/weather/current',
            '/api/system/status',
            # Prometheus 抓取端点（无敏感数据）
            '/metrics',
        ]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # 生成请求ID (用于跟踪)
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # 记录开始时间(性能分析)
        start_time = time.time()

        # Browser ancillary probes have no business endpoint or credentials.
        # Exact paths only: all prediction and other business APIs stay protected.
        if request.url.path in ('/favicon.ico', '/.well-known/appspecific/com.chrome.devtools.json') and request.method in ('GET', 'HEAD'):
            return Response(status_code=204)
        
        # 1. 检查排除路径
        if self._should_skip_auth(request.url.path):
            logger.debug(f"跳过认证: {request.url.path}")
            response = await call_next(request)
            await self._log_api_access(request, response, start_time, None, request_id)
            return response

        # 2. JWT验证
        try:
            user_id, username = await self._authenticate_request(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={'error': 'SERVICE_UNAVAILABLE', 'message': exc.detail, 'request_id': request_id},
            )
        
        if user_id is None:
            return JSONResponse(
                status_code=401,
                content={
                    'error': 'UNAUTHORIZED',
                    'message': '无效或过期的认证令牌',
                    'request_id': request_id
                }
            )

        # 3. 设置用户上下文
        request.state.user_id = user_id
        request.state.username = username

        try:
            # 4. 执行主处理程序
            response = await call_next(request)
            
            # 5. 记录API访问日志
            await self._log_api_access(
                request, response, start_time, user_id, request_id
            )
            
            # 6. 添加审计头
            response.headers['X-Request-ID'] = request_id
            response.headers['X-User-ID'] = str(user_id)
            
            return response
            
        except Exception as e:
            logger.error(f"请求处理异常: {e}", extra={'request_id': request_id})
            
            # 记录错误日志
            await self._log_api_access(
                request, None, start_time, user_id, request_id, str(e)
            )
            
            return JSONResponse(
                status_code=500,
                content={
                    'error': 'INTERNAL_SERVER_ERROR',
                    'message': '服务器内部错误',
                    'request_id': request_id
                }
            )

    def _should_skip_auth(self, path: str) -> bool:
        """检查是否需要跳过认证"""
        # 精确匹配
        if path in self.exclude_paths:
            return True

        # 前缀匹配（必须跳过 '/' —— 否则 startswith('/') 会放行所有路径）
        for exclude_path in self.exclude_paths:
            if exclude_path == '/':
                continue
            if path.startswith(exclude_path):
                return True

        return False

    async def _authenticate_request(self, request: Request) -> tuple[Optional[int], Optional[str]]:
        """
        认证请求
        返回: (user_id, username) 或 (None, None)
        """
        parts = request.headers.get('Authorization', '').split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return None, None
        token = parts[1]
        from realtime_api.config_manager import get_jwt_secret
        import jwt
        try:
            payload = jwt.decode(token, get_jwt_secret(), algorithms=['HS256'])
            if payload.get('type') != 'access':
                return None, None
            user_id = int(payload.get('sub'))
            if user_id <= 0 or not payload.get('username'):
                return None, None
            session_id = payload.get('sid')
            if session_id is not None and (not isinstance(session_id, str) or not session_id):
                return None, None
        except (jwt.PyJWTError, TypeError, ValueError):
            return None, None

        # A correctly signed JWT must still belong to an active login session.
        # Infrastructure failures are retryable, not evidence that credentials expired.
        try:
            db_gen = get_db_async()
            try:
                db = await anext(db_gen)
                session = await AuthCRUD(db).get_active_session(token, user_id, 'access', session_id)
            finally:
                await db_gen.aclose()
        except Exception as exc:
            logger.error("会话认证暂时不可用: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="认证服务暂时不可用，请稍后重试") from exc
        if session is None:
            return None, None
        request.state.session_id = session.session_id
        return user_id, session.username

    async def _log_api_access(
        self,
        request: Request,
        response: Optional[Response],
        start_time: float,
        user_id: Optional[int],
        request_id: str,
        error_message: Optional[str] = None
    ) -> None:
        """记录API访问日志"""
        try:
            # 计算响应时间
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # 构建请求体哈希(隐私保护)
            body_hash = None
            if request.method in ['POST', 'PUT', 'PATCH']:
                try:
                    # 读取body并计算哈希
                    body = await request.body()
                    if body:
                        import hashlib
                        body_hash = hashlib.md5(body).hexdigest()
                except:
                    pass  # 忽略body读取错误

            # 准备日志数据
            log_data = APIAccessLogCreate(
                user_id=user_id,
                session_id=getattr(request.state, 'session_id', None),
                method=request.method,
                url=str(request.url),
                query_params=str(request.query_params) if request.query_params else None,
                request_body_hash=body_hash,
                client_ip=self._get_client_ip(request),
                user_agent=request.headers.get('User-Agent'),
                # 异常分支没有 Response 对象，但数据库字段要求整数。
                # 使用真实将返回给客户端的 500，避免主异常之后再触发
                # Pydantic status_code=None 校验错误并污染诊断日志。
                status_code=response.status_code if response is not None else 500,
                response_time_ms=response_time_ms,
                request_size_bytes=len(body) if 'body' in locals() else None,
                response_size_bytes=len(response.body) if response and hasattr(response, 'body') else None,
                error_message=error_message
            )

            # 异步记录日志(不阻塞请求)
            async def async_log():
                try:
                    # 2026-08 修复：通过 generator aclose() 正常关闭会话，
                    # 此前 anext 取 session 后手动 db.close()，generator 被 GC 时
                    # async with 再次 close → IllegalStateChangeError
                    db_gen = get_db_async()
                    db = await anext(db_gen)
                    try:
                        auth_crud = AuthCRUD(db)
                        await auth_crud.log_api_access(log_data)
                    finally:
                        await db_gen.aclose()
                except Exception as e:
                    logger.error(f"异步记录API日志失败: {e}")

            # 启动后台任务
            fire_and_forget(async_log, "api_access_log")
            
        except Exception as e:
            logger.error(f"构建API日志失败: {e}")

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP地址"""
        try:
            # 优先从X-Forwarded-For获取(代理后)
            x_forwarded_for = request.headers.get('X-Forwarded-For')
            if x_forwarded_for:
                # X-Forwarded-For: client, proxy1, proxy2
                client_ip = x_forwarded_for.split(',')[0].strip()
                return client_ip
            
            # 从X-Real-IP获取
            x_real_ip = request.headers.get('X-Real-IP')
            if x_real_ip:
                return x_real_ip
            
            # 最后从connection获取
            return request.client.host
            
        except Exception:
            return 'unknown'
