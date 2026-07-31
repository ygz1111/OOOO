"""
智能电网负荷预测系统 - 认证依赖工具

提供:
- 当前用户验证
- 权限检查
- API访问日志
- 请求审计

author: 毕业设计项目
"""

import logging
import time
import asyncio
import functools
from typing import Optional, List, Callable, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from realtime_api.database import get_db_async
from realtime_api.crud.auth_crud import AuthCRUD
from realtime_api.schemas.auth import OperationLogCreate


# 日志配置
logger = logging.getLogger(__name__)

# 认证方案
security = HTTPBearer()


def get_current_user():
    """
    获取当前用户依赖
    
    用法:
        @app.get("/users/me")
    async def read_users_me(current_user: User = Depends(get_current_user)):
            return current_user
    """
    async def user_dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db=Depends(get_db_async)
    ):
        """内部实现 - 验证JWT令牌并获取用户信息"""
        try:
            token = credentials.credentials
            
            # 验证令牌
            from realtime_api.config_manager import get_jwt_secret
            jwt_secret = get_jwt_secret()
            import jwt
            
            try:
                payload = jwt.decode(token, jwt_secret, algorithms=['HS256'])
                # 仅接受 access 类型令牌；refresh 令牌不能用于访问受保护接口
                if payload.get('type') != 'access':
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="无效的认证令牌（令牌类型错误）",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                user_id = payload.get('sub')
                username = payload.get('username')
            except jwt.PyJWTError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="无效的认证令牌",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            if not user_id or not username:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="令牌缺少必要信息",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # 获取用户信息
            auth_crud = AuthCRUD(db)
            user = await auth_crud.get_user_by_id(int(user_id))
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="用户不存在或已被禁用",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return user
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取当前用户失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="认证失败",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    return user_dependency


def get_current_active_user(current_user=Depends(get_current_user())):
    """
    获取当前活跃用户 (已激活且未禁用)
    
    此依赖会自动验证用户是否已激活
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=403,
            detail="用户账号已被禁用，请联系管理员"
        )
    return current_user


def check_permission(permission_code: str, error_message: Optional[str] = None):
    """
    权限检查依赖
    
    参数:
        permission_code: 权限代码 (如 'api:weather', 'user:create')
        error_message: 自定义错误信息
    
    用法:
        @app.get("/admin/users")
        @check_permission("user:read", "需要用户管理权限")
        async def get_users(current_user: User = Depends(get_current_active_user)):
            return {"message": "用户列表"}
    """
    async def permission_dependency(
        request: Request,
        current_user=Depends(get_current_active_user),
        db=Depends(get_db_async)
    ):
        """内部权限检查实现"""
        try:
            # 系统管理员拥有全部权限
            auth_crud = AuthCRUD(db)
            roles = await auth_crud.get_user_roles(current_user.id)
            
            if '系统管理员' in roles:
                return current_user
            
            # 检查具体权限
            permissions = await auth_crud.get_user_permissions(current_user.id)
            
            if permission_code not in permissions:
                detail = error_message or f"缺少权限: {permission_code}"
                raise HTTPException(
                    status_code=403,
                    detail=detail
                )
            
            return current_user
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"权限检查失败: {e}")
            raise HTTPException(
                status_code=500,
                detail="权限验证失败"
            )
    
    return permission_dependency


def rbac_required(*permissions: str, require_all: bool = False):
    """
    RBAC权限要求装饰器
    
    参数:
        *permissions: 权限代码列表
        require_all: 是否要求所有权限(AND)或任意权限(OR)
    
    用法:
        @app.get()
        @rbac_required("user:read", "api:weather")
        async def get_data(): pass
        
        @app.post() 
        @rbac_required("user:create", "user:delete", require_all=True)
    async def manage_users(): pass
    """
    async def rbac_dependency(
        request: Request,
        current_user=Depends(get_current_active_user),
        db=Depends(get_db_async)
    ):
        """RBAC检查实现"""
        try:
            auth_crud = AuthCRUD(db)
            
            # 系统管理员拥有全部权限，跳过检查
            roles = await auth_crud.get_user_roles(current_user.id)
            if '系统管理员' in roles:
                return current_user
            
            # 获取用户权限
            user_permissions = await auth_crud.get_user_permissions(current_user.id)
            
            # 检查权限
            if require_all:
                # 需要所有权限
                for perm in permissions:
                    if perm not in user_permissions:
                        raise HTTPException(
                            status_code=403,
                            detail=f"缺少权限: {perm}"
                        )
            else:
                # 需要任意权限
                if not any(perm in user_permissions for perm in permissions):
                    raise HTTPException(
                        status_code=403,
                        detail=f"需要以下任一权限: {', '.join(permissions)}"
                    )
            
            return current_user
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"RBAC检查失败: {e}")
            raise HTTPException(
                status_code=500,
                detail="权限验证失败"
            )
    
    return rbac_dependency


def log_operation(
    operation_type: str,
    resource_type: str,
    description_template: str,
    resource_id_func: Optional[Callable] = None,
):
    """
    操作日志装饰器
    
    参数:
        operation_type: 操作类型 (CREATE, READ, UPDATE, DELETE)
        resource_type: 资源类型 (USER, DATA, MODEL)
        description_template: 描述模板，可使用 {resource_id} 等占位符
        resource_id_func: 从依赖中提取资源ID的函数
  
    用法:
        @app.post("/users")
        @log_operation("CREATE", "USER", "创建用户")
        async def create_user(): pass
    """
    def log_operation_decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request = None
            current_user = None
            
            # 从kwargs中获取request和current_user
            for arg in args:
                if hasattr(arg, 'method') and hasattr(arg, 'url'):
                    request = arg
                    break
            
            for value in kwargs.values():
                if hasattr(value, 'id') and hasattr(value, 'username'):
                    current_user = value
                    break
            
            # 执行原始函数
            result = None
            exception = None
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                return result
                
            except Exception as e:
                exception = e
                raise
            
            finally:
                if request and current_user:
                    try:
                        # 构建日志数据
                        resource_id = None
                        if resource_id_func:
                            if callable(resource_id_func):
                                try:
                                    resource_id = resource_id_func(result, *args, **kwargs)
                                except Exception:
                                    pass
                        
                        description = description_template.format(
                            resource_id=resource_id,
                            user=current_user.username,
                            time=start_time
                        )
                        
                        # 记录操作日志
                        log_data = OperationLogCreate(
                            user_id=current_user.id,
                            session_id=getattr(request.state, 'session_id', None),
                            operation_type=operation_type,
                            resource_type=resource_type,
                            resource_id=str(resource_id) if resource_id else None,
                            description=description[:500],  # 截断描述
                            details={
                                'request_id': getattr(request.state, 'request_id', None),
                                'function': func.__name__,
                                'path': str(request.url.path),
                                'method': request.method,
                                'duration_ms': int((time.time() - start_time) * 1000)
                            },
                            is_success=exception is None,
                            error_message=str(exception) if exception else None,
                            client_ip=getattr(request.state, 'client_ip', None),
                            user_agent=request.headers.get('User-Agent')
                        )
                        
                        # 异步记录日志
                        async def save_log():
                            try:
                                db = await anext(get_db_async())
                                auth_crud = AuthCRUD(db)
                                await auth_crud.log_operation(log_data)
                                await db.close()
                            except Exception:
                                pass  # 日志失败不应影响业务
                        
                        asyncio.create_task(save_log())
                        
                    except Exception:
                        pass  # 日志异常不应抛出
        
        return wrapper
    return log_operation_decorator


def audit_sensitive_operation(operation_name: str, resource_type: str):
    """
    审计敏感操作装饰器
    
    记录高价值操作，用于安全审计和合规性
    """
    def audit_decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取上下文信息
            request = None
            current_user = None
            
            for arg in args:
                if hasattr(arg, 'method'):
                    request = arg
            
            for value in kwargs.values():
                if hasattr(value, 'id') and hasattr(value, 'username'):
                    current_user = value
            
            # 记录审计日志
            if request and current_user:
                audit_info = {
                    'operation': operation_name,
                    'resource_type': resource_type,
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'ip': getattr(request.state, 'client_ip', 'unknown'),
                    'user_agent': request.headers.get('User-Agent', 'unknown'),
                    'request_id': getattr(request.state, 'request_id', 'unknown'),
                    'endpoint': f"{request.method} {request.url.path}"
                }
                
                logger.info(f"审计敏感操作: {operation_name}", extra=audit_info)
            
            # 执行原始函数
            return await func(*args, **kwargs)
        
        return wrapper
    return audit_decorator


# 便捷的权限检查工具函数
def get_user_permissions(user_id: int, db):
    """获取用户所有权限(工具函数)"""
    auth_crud = AuthCRUD(db)
    return asyncio.create_task(auth_crud.get_user_permissions(user_id))


def get_user_roles(user_id: int, db):
    """获取用户所有角色(工具函数)"""
    auth_crud = AuthCRUD(db)
    return asyncio.create_task(auth_crud.get_user_roles(user_id))


def has_permission(user_id: int, permission_code: str, db):
    """检查用户是否有指定权限（协程封装，使用前需 await）"""
    auth_crud = AuthCRUD(db)
    return auth_crud.get_user_permissions(user_id)


# 导出
__all__ = [
    'get_current_user',
    'get_current_active_user',
    'check_permission',
    'rbac_required',
    'log_operation',
    'audit_sensitive_operation',
    'get_user_permissions',
    'get_user_roles',
    'has_permission',
]