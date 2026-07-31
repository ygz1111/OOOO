"""
智能电网负荷预测系统 - 用户认证与权限管理 Schemas

功能:
- 用户注册登录数据模型
- JWT令牌定义
- 角色权限结构
- API请求响应模型

作者: 毕业设计项目
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, validator
from enum import Enum


class TokenType(str, Enum):
    """JWT令牌类型"""
    ACCESS = "access"
    REFRESH = "refresh"


class LoginMethod(str, Enum):
    """登录方式"""
    PASSWORD = "password"
    OAUTH2 = "oauth2"
    SSO = "sso"


class UserStatus(str, Enum):
    """用户状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"


class UserCreate(BaseModel):
    """用户注册 - 请求模型"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=8, max_length=100, description="密码")
    full_name: Optional[str] = Field(None, max_length=100, description="全名")
    department: Optional[str] = Field(None, max_length=50, description="部门")
    phone: Optional[str] = Field(None, max_length=20, description="电话")
    
    @validator('username')
    def username_alphanumeric(cls, v):
        if not v.isalnum():
            raise ValueError('用户名必须只包含字母和数字')
        return v.lower()

    @validator('password')
    def password_strength(cls, v):
        # 基础密码强度检查
        if len(v) < 8:
            raise ValueError('密码长度至少8位')
        if not any(c.isupper() for c in v):
            raise ValueError('密码必须包含大写字母')
        if not any(c.isdigit() for c in v):
            raise ValueError('密码必须包含数字')
        return v


class UserUpdate(BaseModel):
    """用户更新 - 请求模型"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """用户信息 - 响应模型"""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    department: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    is_verified: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PasswordResetRequest(BaseModel):
    """密码重置请求"""
    email: EmailStr = Field(..., description="用户邮箱")
    

class PasswordReset(BaseModel):
    """密码重置验证"""
    token: str = Field(..., description="重置令牌")
    new_password: str = Field(..., min_length=8, description="新密码")

    @validator('new_password')
    def password_strength(cls, v):
        return UserCreate.password_strength(v)


class PasswordChange(BaseModel):
    """密码修改"""
    old_password: str = Field(..., description="原密码")
    new_password: str = Field(..., description="新密码")

    @validator('new_password')
    def password_strength(cls, v):
        return UserCreate.password_strength(v)


class RoleCreate(BaseModel):
    """角色创建"""
    name: str = Field(..., max_length=50, description="角色名")
    description: Optional[str] = Field(None, max_length=255, description="描述")
    level: int = Field(1, ge=1, le=100, description="权限等级")


class RoleUpdate(BaseModel):
    """角色更新"""
    description: Optional[str] = Field(None, max_length=255)
    level: Optional[int] = Field(None, ge=1, le=100)


class RoleResponse(BaseModel):
    """角色响应"""
    id: int
    name: str
    description: Optional[str] = None
    level: int
    is_system_role: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PermissionResponse(BaseModel):
    """权限响应"""
    id: int
    name: str
    code: str
    description: Optional[str] = None
    category: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None

    class Config:
        from_attributes = True


class UserRoleAssign(BaseModel):
    """用户角色分配"""
    user_id: int = Field(..., description="用户ID")
    role_id: int = Field(..., description="角色ID")
    expires_at: Optional[datetime] = None
    reason: Optional[str] = Field(None, max_length=255, description="授予原因")


class RolePermissionAssign(BaseModel):
    """角色权限分配"""
    role_id: int
    permission_ids: List[int] = Field(..., description="权限ID列表")


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")
    remember_me: bool = Field(False, description="记住登录")


class TokenResponse(BaseModel):
    """令牌响应"""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """刷新令牌请求"""
    refresh_token: str = Field(..., description="刷新令牌")


class LogoutRequest(BaseModel):
    """登出请求"""
    all_devices: bool = Field(False, description="是否注销所有设备")


class AuthInfo(BaseModel):
    """认证信息"""
    user_id: int
    username: str
    email: str
    session_id: str
    permissions: List[str] = []
    roles: List[str] = []
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    authenticated_at: datetime


class APIAccessLogCreate(BaseModel):
    """API访问日志-创建"""
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    method: str
    url: str
    query_params: Optional[str] = None
    request_body_hash: Optional[str] = None
    client_ip: str
    user_agent: Optional[str] = None
    status_code: int
    response_time_ms: int
    request_size_bytes: Optional[int] = None
    response_size_bytes: Optional[int] = None
    error_message: Optional[str] = None


class APIAccessLogResponse(BaseModel):
    """API访问日志-响应"""
    id: int
    method: str
    url: str
    client_ip: str
    status_code: int
    response_time_ms: int
    created_at: datetime
    username: Optional[str] = None
    
    class Config:
        from_attributes = True


class OperationLogCreate(BaseModel):
    """操作日志-创建"""
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    operation_type: str
    resource_type: str
    resource_id: Optional[str] = None
    description: str
    details: Optional[dict] = None
    is_success: bool = True
    error_message: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None


class OperationLogResponse(BaseModel):
    """操作日志-响应"""
    id: int
    username: Optional[str] = None
    operation_type: str
    resource_type: str
    resource_id: Optional[str] = None
    description: str
    is_success: bool
    client_ip: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class LoginHistoryResponse(BaseModel):
    """登录历史-响应"""
    id: int
    login_ip: Optional[str] = None
    login_method: str
    is_success: bool
    failure_reason: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class SessionResponse(BaseModel):
    """会话信息-响应"""
    id: int
    session_id: str
    username: str
    client_ip: Optional[str] = None
    platform: Optional[str] = None
    last_activity: datetime
    expires_at: datetime
    idle_minutes: Optional[int] = None


class UserProfile(BaseModel):
    """用户资料"""
    user: UserResponse
    roles: List[str] = []
    permissions: List[str] = []
    active_sessions: int = 0
    last_login: Optional[datetime] = None
    total_logins: int = 0


class PermissionCategory(str, Enum):
    """权限分类"""
    USER_MGMT = "USER_MGMT"
    ROLE_MGMT = "ROLE_MGMT"
    PERMISSION_MGMT = "PERMISSION_MGMT"
    API_ACCESS = "API_ACCESS"
    DATA_ACCESS = "DATA_ACCESS"
    MODEL_OPS = "MODEL_OPS"
    ADMIN_PANEL = "ADMIN_PANEL"


class ResourceType(str, Enum):
    """资源类型"""
    USER = "USER"
    ROLE = "ROLE"
    PERMISSION = "PERMISSION"
    API = "API"
    DATA = "DATA"
    MODEL = "MODEL"
    PREDICTION = "PREDICTION"
    WEATHER = "WEATHER"


class OperationType(str, Enum):
    """操作类型"""
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    EXPORT = "EXPORT"
    UPLOAD = "UPLOAD"

__all__ = [
    'TokenType',
    'LoginMethod',
    'UserStatus',
    'PermissionCategory',
    'ResourceType',
    'OperationType',
    'UserCreate',
    'UserUpdate',
    'UserResponse',
    'PasswordResetRequest',
    'PasswordReset',
    'PasswordChange',
    'RoleCreate',
    'RoleUpdate',
    'RoleResponse',
    'PermissionResponse',
    'UserRoleAssign',
    'RolePermissionAssign',
    'LoginRequest',
    'TokenResponse',
    'RefreshTokenRequest',
    'LogoutRequest',
    'AuthInfo',
    'APIAccessLogCreate',
    'APIAccessLogResponse',
    'OperationLogCreate',
    'OperationLogResponse',
    'LoginHistoryResponse',
    'SessionResponse',
    'UserProfile',
]