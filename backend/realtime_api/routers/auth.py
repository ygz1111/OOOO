"""
智能电网负荷预测系统 - 用户认证API路由

功能:
- 用户注册
- 用户登录/登出
- 令牌刷新
- 密码管理
- 用户Session管理

author: 毕业设计项目
"""

import logging
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from realtime_api.database import get_db_async
from realtime_api.crud.auth_crud import AuthCRUD, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS
from realtime_api.schemas.auth import (
    UserCreate,
    UserResponse,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    PasswordChange,
    PasswordReset,
    UserProfile,
    SessionResponse,
    LoginHistoryResponse
)
from realtime_api.auth.dependencies import get_current_active_user, audit_sensitive_operation


# 创建路由器
router = APIRouter(prefix="/api/auth", tags=["认证授权"])

# 日志配置
logger = logging.getLogger(__name__)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    description="用户注册 - 创建新用户账号"
)
@audit_sensitive_operation("用户注册", "USER")
async def register_user(
    user: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_async)
):
    """注册新用户"""
    try:
        auth_crud = AuthCRUD(db)
        
        # 检查邀请或管理员权限
        # TODO: 集成邮箱验证或管理员批准流程
        
        # 创建用户
        new_user = await auth_crud.create_user(user)
        
        # 分配默认角色(普通用户)
        from sqlalchemy import text as sql_text
        default_role_query = sql_text("SELECT id FROM roles WHERE name = '普通用户'")
        role_result = await db.execute(default_role_query)
        role_row = role_result.fetchone()
        
        if role_row:
            from realtime_api.schemas.auth import UserRoleAssign
            assignment = UserRoleAssign(
                user_id=new_user.id,
                role_id=role_row.id
            )
            await auth_crud.assign_user_role(assignment, 1)  # 1为系统用户
        
        logger.info(f"新用户注册成功: {new_user.username}")
        
        return new_user
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"注册失败: {str(e)}"
        )
    except Exception as e:
        logger.error(f"用户注册异常: {e}")
        raise HTTPException(
            status_code=500,
            detail="用户注册失败，请稍后重试"
        )



@router.post(
    "/login",
    response_model=TokenResponse,
    description="用户登录 - 获取JWT令牌"
)
@audit_sensitive_operation("用户登录", "USER")
async def login(
    login_request: LoginRequest,
    request: Request,
        db: AsyncSession = Depends(get_db_async)
):
    """用户登录"""
    try:
        auth_crud = AuthCRUD(db)
        
        # 验证用户名密码
        is_valid, user = await auth_crud.verify_user_password(
            login_request.username,
            login_request.password
        )
        
        if not is_valid or not user:
            # 记录失败登录
            await auth_crud.log_login_history(
                user_id=user.id if user else None,
                login_ip=request.client.host,
                user_agent=request.headers.get('User-Agent'),
                login_method='password',
                is_success=False,
                failure_reason='用户名或密码错误'
            )
            
            raise HTTPException(
                status_code=401,
                detail="用户名或密码错误"
            )
        
        # 检查用户是否激活
        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="账号已被禁用，请联系管理员"
            )

        # 更新最后登录时间
        await auth_crud.update_last_login(user.id)
        
        # 会话ID先于令牌生成，避免把JWT误当作数据库中的UUID。
        import uuid
        session_id = str(uuid.uuid4())
        access_token = auth_crud.create_access_token(user.id, user.username, session_id=session_id)
        
        refresh_token = None
        # 如果要求记住登录，则生成Refresh Token
        if login_request.remember_me:
            refresh_token = auth_crud.create_refresh_token(user.id, user.username, session_id=session_id)
        
        # 存储会话
        if login_request.remember_me and refresh_token:
            refresh_expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        else:
            refresh_expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        stored = await auth_crud.store_user_session(
            user_id=user.id,
            token=access_token,
            refresh_token=refresh_token,
            session_id=session_id,
            client_ip=request.client.host,
            user_agent=request.headers.get('User-Agent'),
            platform=request.headers.get('platform', 'web'),
            expires_at=refresh_expires
        )
        if not stored:
            raise HTTPException(status_code=503, detail="登录会话暂时无法保存，请稍后重试")
        
        # 记录成功登录
        await auth_crud.log_login_history(
            user_id=user.id,
            login_ip=request.client.host,
            user_agent=request.headers.get('User-Agent'),
            login_method='password',
            is_success=True
        )
        
        logger.info(f"用户登录成功: {user.username}")
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=43200,  # 12 小时
            user=user  # 包含用户信息
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录异常: {e}")
        raise HTTPException(
            status_code=500,
            detail="登录失败，请稍后重试"
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    description="刷新访问令牌"
)
async def refresh_access_token(
    body: RefreshTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_async)
):
    """使用Refresh Token获取新的Access Token（body 传 {refresh_token}）"""
    try:
        auth_crud = AuthCRUD(db)
        refresh_token = body.refresh_token
        
        # 验证Refresh Token
        token_data = auth_crud.verify_token(refresh_token)
        if not token_data or token_data.get('type') != 'refresh':
            raise HTTPException(
                status_code=401,
                detail="无效的Refresh Token"
            )
        
        try:
            user_id = int(token_data.get('sub'))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="无效的Refresh Token")
        session = await auth_crud.get_active_session(refresh_token, user_id, "refresh")
        if session is None:
            raise HTTPException(status_code=401, detail="登录会话已过期或注销，请重新登录")
        
        # 获取用户信息
        user = await auth_crud.get_user_by_id(user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=401,
                detail="用户不存在或已被禁用"
            )
        
        # 生成新的Access Token
        new_access_token = auth_crud.create_access_token(user_id, user.username, session_id=session.session_id)
        updated = await auth_crud.update_session_access_token(session.session_id, user_id, new_access_token)
        if not updated:
            raise HTTPException(status_code=401, detail="登录会话已过期或注销，请重新登录")
        
        # 可选：生成新的Refresh Token(刷新刷新令牌)
        # 这里保持原refresh token，可以扩展实现刷新token轮转
        
        return TokenResponse(
            access_token=new_access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=43200,  # 12 小时
            user=user
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("刷新令牌失败: %s", type(e).__name__)
        raise HTTPException(
            status_code=503,
            detail="令牌刷新失败"
        )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    description="用户登出 - 注销会话"
)
@audit_sensitive_operation("用户登出", "USER")
async def logout(
    request: Request,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """用户登出"""
    try:
        auth_crud = AuthCRUD(db)
        
        session_id = getattr(request.state, 'session_id', None)
        if not session_id:
            raise HTTPException(status_code=401, detail="无效的登录会话")
        if not await auth_crud.revoke_session(session_id):
            raise HTTPException(status_code=503, detail="会话注销暂时失败，请重试")
        
        logger.info(f"用户登出: {current_user.username}")
        
        return {"message": "登出成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登出异常: {e}")
        raise HTTPException(
            status_code=500,
            detail="登出失败"
        )


@router.post(
    "/logout-all", 
    status_code=status.HTTP_200_OK,
    description="注销所有设备上的会话"
)
@audit_sensitive_operation("批量登出", "USER")
async def logout_all_devices(
    request: Request,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """注销用户在所有设备上的会话"""
    try:
        auth_crud = AuthCRUD(db)
        
        current_session_id = getattr(request.state, 'session_id', None)
        if not current_session_id:
            raise HTTPException(status_code=401, detail="无效的登录会话")
        
        # 注销所有会话(保留当前)
        if not await auth_crud.revoke_all_user_sessions(current_user.id, current_session_id):
            raise HTTPException(status_code=503, detail="会话注销暂时失败，请重试")
        
        logger.info(f"用户批量登出: {current_user.username}")
        
        return {"message": "已在所有设备上登出(当前设备保持登录)"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量登出异常: {e}")
        raise HTTPException(
            status_code=500,
            detail="操作失败"
        )


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    description="修改密码"
)
@audit_sensitive_operation("修改密码", "USER")
async def change_password(
    password_change: PasswordChange,
    request: Request,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """修改当前用户密码"""
    try:
        auth_crud = AuthCRUD(db)
        
        # 修改密码
        success = await auth_crud.change_password(current_user.id, password_change)
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail="原密码错误或密码修改失败"
            )

        logger.info(f"密码修改成功: {current_user.username}")
        
        return {"message": "密码修改成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"密码修改异常: {e}")
        raise HTTPException(
            status_code=500,
            detail="密码修改失败"
        )


@router.get(
    "/me",
    response_model=UserProfile,
    description="获取当前用户完整资料"
)
async def get_current_user_profile(
    request: Request,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """获取当前用户完整资料"""
    try:
        auth_crud = AuthCRUD(db)
        
        # 获取用户权限和角色
        permissions = await auth_crud.get_user_permissions(current_user.id)
        roles = await auth_crud.get_user_roles(current_user.id)
        
        # 查询活跃会话数
        from sqlalchemy import text as sql_text
        session_query = sql_text("""
            SELECT COUNT(*) FROM active_sessions_view 
            WHERE username = :username
        """)
        session_result = await db.execute(session_query, {'username': current_user.username})
        active_sessions = session_result.scalar() or 0
        
        # 查询登录统计
        stats_query = sql_text("""
            SELECT * FROM login_stats_view 
            WHERE username = :username
        """)
        stats_result = await db.execute(stats_query, {'username': current_user.username})
        stats_row = stats_result.fetchone()
        
        return UserProfile(
            user=current_user,
            permissions=permissions,
            roles=roles,
            active_sessions=active_sessions,
            last_login=stats_row.last_login if stats_row else None,
            total_logins=stats_row.total_logins if stats_row else 0
        )
        
    except Exception as e:
        logger.error(f"获取用户资料失败: {e}")
        raise HTTPException(
            status_code=500,
            detail="获取用户资料失败"
        )


@router.get(
    "/sessions",
    response_model=List[SessionResponse],
    description="获取用户所有活跃会话"
)
async def get_user_sessions(
    request: Request,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """获取当前用户的所有活跃会话"""
    try:
        from sqlalchemy import text as sql_text
        query = sql_text("""
            SELECT * FROM active_sessions_view 
            WHERE username = :username AND expires_at > UTC_TIMESTAMP()
        """)
        result = await db.execute(query, {'username': current_user.username})
        
        sessions = []
        for row in result.fetchall():
            sessions.append(SessionResponse(
                id=row.id,
                session_id=row.session_id,
                username=row.username,
                client_ip=row.client_ip,
                platform=row.platform,
                last_activity=row.last_activity,
                expires_at=row.expires_at,
                idle_minutes=row.idle_minutes
            ))
        
        return sessions
        
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(
            status_code=500,
            detail="获取会话信息失败"
        )


@router.get(
    "/login-history",
    response_model=List[LoginHistoryResponse],
    description="获取登录历史记录"
)
async def get_login_history(
    request: Request,
    limit: int = 10,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """获取用户登录历史"""
    try:
        from sqlalchemy import text as sql_text
        query = sql_text("""
            SELECT * FROM login_histories 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC 
            LIMIT :limit
        """)
        result = await db.execute(query, {
            'user_id': current_user.id,
            'limit': limit
        })
        
        history = []
        for row in result.fetchall():
            history.append(LoginHistoryResponse.from_orm(row))
        
        return history
        
    except Exception as e:
        logger.error(f"获取登录历史失败: {e}")
        raise HTTPException(
            status_code=500,
            detail="获取登录历史失败"
        )


@router.delete(
    "/session/{session_id}",
    status_code=status.HTTP_200_OK,
    description="注销指定会话"
)
@audit_sensitive_operation("会话管理", "USER")
async def revoke_session(
    session_id: str,
    request: Request,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """注销指定会话(只能注销自己的)"""
    try:
        auth_crud = AuthCRUD(db)
        
        # 检查是否为自己的会话
        from sqlalchemy import text as sql_text
        check_query = sql_text("""
            SELECT user_id FROM user_sessions 
            WHERE session_id = :session_id
        """)
        result = await db.execute(check_query, {'session_id': session_id})
        session_row = result.fetchone()
        
        if not session_row or session_row.user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="无权操作此会话"
            )
        
        # 注销会话
        success = await auth_crud.revoke_session(session_id)
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail="会话注销失败"
            )
        
        logger.info(f"会话注销: {current_user.username} -> {session_id}")
        
        return {"message": "会话已失效"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注销会话异常: {e}")
        raise HTTPException(
            status_code=500,
            detail="操作失败"
        )


# 健康检查路由(无认证)
@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    description="认证系统健康检查"
)
async def auth_health_check():
    """检查认证系统状态"""
    return {
        "status": "ok",
        "service": "auth",
        "timestamp": datetime.utcnow()
    }


__all__ = [
    'router'
]
