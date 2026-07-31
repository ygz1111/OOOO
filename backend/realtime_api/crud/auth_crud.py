"""
智能电网负荷预测系统 - 用户认证与权限 CRUD操作

功能:
- 用户管理(增删改查)
- 角色权限管理
- 登录登出处理
- JWT令牌管理
- 操作日志记录

作者: 毕业设计项目
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from hashlib import md5

import jwt
import bcrypt
from sqlalchemy import text, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from realtime_api.database import get_db_async
from realtime_api.config_manager import get_jwt_secret
from realtime_api.schemas.auth import (
    UserCreate, UserUpdate, UserResponse, PasswordChange,
    RoleCreate, RoleUpdate, RoleResponse, PermissionResponse,
    UserRoleAssign, RolePermissionAssign, AuthInfo,
    APIAccessLogCreate, OperationLogCreate, LoginHistoryResponse
)

# 日志配置
logger = logging.getLogger(__name__)

# 密码哈希工具函数 (直接使用 bcrypt 库，避免 passlib 兼容性问题)
def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码"""
    return bcrypt.hashpw(password[:72].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    try:
        return bcrypt.checkpw(password[:72].encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

# JWT配置
# 密钥统一从 config_manager.get_jwt_secret() 动态读取（优先 AUTH_JWT_SECRET_KEY 环境变量），
# 不在模块加载时固化，避免 import 顺序导致密钥不一致。
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


class AuthCRUD:
    """认证授权CRUD操作类"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    # =========================================================================
    # 用户管理
    # =========================================================================

    async def create_user(self, user: UserCreate, created_by: Optional[int] = None) -> UserResponse:
        """创建用户"""
        try:
            # 检查用户名和邮箱唯一性
            exists = await self._check_user_exists(user.username, user.email)
            if exists:
                raise ValueError("用户名或邮箱已存在")

            # 创建用户
            hashed_password = hash_password(user.password)
            
            query = text("""
                INSERT INTO users (
                    username, email, hashed_password, 
                    full_name, department, phone, created_by
                ) VALUES (
                    :username, :email, :hashed_password,
                    :full_name, :department, :phone, :created_by
                )
            """)
            result = await self.db.execute(query, {
                'username': user.username,
                'email': user.email,
                'hashed_password': hashed_password,
                'full_name': user.full_name,
                'department': user.department,
                'phone': user.phone,
                'created_by': created_by
            })
            await self.db.commit()
            
            # 获取新用户信息
            new_user = await self.get_user_by_id(result.lastrowid)
            return new_user
            
        except Exception as e:
            logger.error(f"创建用户失败: {e}")
            raise

    async def get_user_by_id(self, user_id: int) -> Optional[UserResponse]:
        """通过ID获取用户"""
        try:
            query = text("""
                SELECT * FROM users WHERE id = :user_id AND is_active = TRUE
            """)
            result = await self.db.execute(query, {'user_id': user_id})
            row = result.fetchone()
            
            if row:
                return UserResponse.from_orm(row)
            return None
            
        except Exception as e:
            logger.error(f"获取用户失败: {e}")
            raise

    async def get_user_by_username(self, username: str) -> Optional[UserResponse]:
        """通过用户名获取用户"""
        try:
            query = text("""
                SELECT * FROM users 
                WHERE (username = :username OR email = :username) 
                AND is_active = TRUE
            """)
            result = await self.db.execute(query, {'username': username})
            row = result.fetchone()
            
            if row:
                return UserResponse.from_orm(row)
            return None
            
        except Exception as e:
            logger.error(f"通过用户名获取用户失败: {e}")
            raise

    async def verify_user_password(self, username: str, password: str) -> Tuple[bool, Optional[UserResponse]]:
        """验证用户密码"""
        try:
            query = text("SELECT * FROM users WHERE (username = :username OR email = :username) AND is_active = TRUE")
            result = await self.db.execute(query, {'username': username})
            user_row = result.fetchone()
            
            if not user_row:
                return False, None

            # 检查密码
            is_valid = verify_password(password, user_row.hashed_password)
            
            if is_valid:
                user = UserResponse.from_orm(user_row)
                return True, user
            else:
                # 更新失败登录次数
                await self._update_failed_login_attempts(user_row.id)
                return False, None
                
        except Exception as e:
            logger.error(f"验证密码失败: {e}")
            return False, None

    async def update_user(self, user_id: int, user_update: UserUpdate, updated_by: Optional[int] = None) -> UserResponse:
        """更新用户信息"""
        try:
            # 构建更新字段
            update_data = {}
            if user_update.email is not None:
                update_data['email'] = user_update.email
            if user_update.full_name is not None:
                update_data['full_name'] = user_update.full_name
            if user_update.department is not None:
                update_data['department'] = user_update.department
            if user_update.phone is not None:
                update_data['phone'] = user_update.phone
            if user_update.is_active is not None:
                update_data['is_active'] = user_update.is_active
                
            if update_data:
                update_data['updated_by'] = updated_by
                
                set_clause = ', '.join([f"{key} = :{key}" for key in update_data.keys()])
                query = text(f"UPDATE users SET {set_clause} WHERE id = :user_id")
                update_data['user_id'] = user_id
                
                await self.db.execute(query, update_data)
                await self.db.commit()

            # 返回更新后的用户信息
            updated_user = await self.get_user_by_id(user_id)
            return updated_user
            
        except Exception as e:
            logger.error(f"更新用户失败: {e}")
            raise

    async def change_password(self, user_id: int, password_change: PasswordChange) -> bool:
        """修改密码"""
        try:
            # 获取用户
            user = await self.get_user_by_id(user_id)
            if not user:
                return False

            # 验证旧密码
            old_query = text("SELECT hashed_password FROM users WHERE id = :user_id")
            result = await self.db.execute(old_query, {'user_id': user_id})
            row = result.fetchone()
            
            if not verify_password(password_change.old_password, row.hashed_password):
                return False

            # 更新新密码
            new_password_hash = hash_password(password_change.new_password)
            update_query = text("""
                UPDATE users 
                SET hashed_password = :password_hash, password_changed_at = NOW()
                WHERE id = :user_id
            """)
            
            await self.db.execute(update_query, {
                'password_hash': new_password_hash,
                'user_id': user_id
            })
            await self.db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"修改密码失败: {e}")
            return False

    # =========================================================================
    # 角色和权限管理
    # =========================================================================

    async def get_user_permissions(self, user_id: int) -> List[str]:
        """获取用户所有权限"""
        try:
            query = text("""
                SELECT DISTINCT p.code
                FROM user_permissions_view p
                WHERE p.user_id = :user_id
            """)
            
            result = await self.db.execute(query, {'user_id': user_id})
            permissions = [row[0] for row in result.fetchall()]
            
            return permissions
            
        except Exception as e:
            logger.error(f"获取用户权限失败: {e}")
            return []

    async def get_user_roles(self, user_id: int) -> List[str]:
        """获取用户所有角色"""
        try:
            query = text("""
                SELECT r.name
                FROM user_roles ur
                    JOIN roles r ON ur.role_id = r.id
                WHERE ur.user_id = :user_id 
                    AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
            """)
            
            result = await self.db.execute(query, {'user_id': user_id})
            roles = [row[0] for row in result.fetchall()]
            
            return roles
            
        except Exception as e:
            logger.error(f"获取用户角色失败: {e}")
            return []

    async def assign_user_role(self, assignment: UserRoleAssign, granted_by: int) -> bool:
        """分配用户角色"""
        try:
            query = text("""
                INSERT INTO user_roles (user_id, role_id, granted_by, granted_reason, expires_at)
                VALUES (:user_id, :role_id, :granted_by, :reason, :expires_at)
                ON DUPLICATE KEY UPDATE 
                    granted_by = VALUES(granted_by),
                    granted_reason = VALUES(granted_reason),
                    expires_at = VALUES(expires_at)
            """)
            
            await self.db.execute(query, {
                'user_id': assignment.user_id,
                'role_id': assignment.role_id,
                'granted_by': granted_by,
                'reason': assignment.reason,
                'expires_at': assignment.expires_at
            })
            await self.db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"分配用户角色失败: {e}")
            return False

    async def remove_user_role(self, user_id: int, role_id: int) -> bool:
        """移除用户角色"""
        try:
            query = text("DELETE FROM user_roles WHERE user_id = :user_id AND role_id = :role_id")
            await self.db.execute(query, {
                'user_id': user_id,
                'role_id': role_id
            })
            return True
            
        except Exception as e:
            logger.error(f"移除用户角色失败: {e}")
            return False

    async def get_roles(self) -> List[RoleResponse]:
        """获取所有角色"""
        try:
            query = text("SELECT * FROM roles ORDER BY level DESC, name")
            result = await self.db.execute(query)
            roles = []
            
            for row in result.fetchall():
                roles.append(RoleResponse.from_orm(row))
                
            return roles
            
        except Exception as e:
            logger.error(f"获取角色失败: {e}")
            return []

    async def create_role(self, role: RoleCreate, created_by: Optional[int] = None) -> RoleResponse:
        """创建角色"""
        try:
            # 检查角色名唯一性
            check_query = text("SELECT id FROM roles WHERE name = :name")
            check_result = await self.db.execute(check_query, {'name': role.name})
            if check_result.fetchone():
                raise ValueError("角色名已存在")

            # 创建角色
            query = text("""
                INSERT INTO roles (name, description, level, created_by)
                VALUES (:name, :description, :level, :created_by)
            """)
            result = await self.db.execute(query, {
                'name': role.name,
                'description': role.description,
                'level': role.level,
                'created_by': created_by
            })
            
            # 获取新角色
            new_role_query = text("SELECT * FROM roles WHERE id = :role_id")
            role_result = await self.db.execute(new_role_query, {'role_id': result.lastrowid})
            row = role_result.fetchone()
            
            return RoleResponse.from_orm(row)
            
        except Exception as e:
            logger.error(f"创建角色失败: {e}")
            raise

    # =========================================================================
    # JWT 令牌管理
    # =========================================================================

    def create_access_token(self, user_id: int, username: str, expires_delta: Optional[timedelta] = None) -> str:
        """创建JWT访问令牌"""
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode = {
            'sub': str(user_id),
            'username': username,
            'type': 'access',
            'exp': expire,
            'iat': datetime.now(timezone.utc)
        }
        
        return jwt.encode(to_encode, get_jwt_secret(), algorithm=JWT_ALGORITHM)

    def create_refresh_token(self, user_id: int, username: str, expires_delta: Optional[timedelta] = None) -> str:
        """创建JWT刷新令牌"""
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        to_encode = {
            'sub': str(user_id),
            'username': username,
            'type': 'refresh',
            'exp': expire,
            'iat': datetime.now(timezone.utc)
        }
        
        return jwt.encode(to_encode, get_jwt_secret(), algorithm=JWT_ALGORITHM)

    def verify_token(self, token: str) -> Optional[dict]:
        """验证JWT令牌"""
        try:
            payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
            
            # 检查令牌类型
            if payload.get('type') not in ['access', 'refresh']:
                logger.warning(f"无效令牌类型: {payload.get('type')}")
                return None
                
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("令牌已过期")
            return None
        except jwt.PyJWTError as e:
            logger.error(f"令牌验证失败: {e}")
            return None

    async def store_user_session(
        self,
        user_id: int,
        token: str,
        refresh_token: Optional[str],
        session_id: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
        platform: Optional[str],
        expires_at: datetime
    ) -> bool:
        """存储用户会话"""
        try:
            query = text("""
                INSERT INTO user_sessions 
                (user_id, session_id, jwt_token, refresh_token, 
                client_ip, user_agent, platform, expires_at, last_activity)
                VALUES 
                (:user_id, :session_id, :token, :refresh_token,
                :client_ip, :user_agent, :platform, :expires_at, NOW())
            """)
            
            await self.db.execute(query, {
                'user_id': user_id,
                'session_id': session_id,
                'token': token,
                'refresh_token': refresh_token,
                'client_ip': client_ip,
                'user_agent': user_agent,
                'platform': platform,
                'expires_at': expires_at
            })
            await self.db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"存储会话失败: {e}")
            return False

    async def revoke_session(self, session_id: str) -> bool:
        """注销会话"""
        try:
            query = text("""
                UPDATE user_sessions 
                SET is_active = FALSE, revoked_at = NOW()
                WHERE session_id = :session_id
            """)
            
            await self.db.execute(query, {'session_id': session_id})
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"注销会话失败: {e}")
            return False

    async def revoke_all_user_sessions(self, user_id: int, except_session_id: Optional[str] = None) -> bool:
        """注销用户所有会话"""
        try:
            if except_session_id:
                query = text("""
                    UPDATE user_sessions 
                    SET is_active = FALSE, revoked_at = NOW()
                    WHERE user_id = :user_id AND session_id != :except_session_id
                """)
                await self.db.execute(query, {
                    'user_id': user_id,
                    'except_session_id': except_session_id
                })
                await self.db.commit()
            else:
                query = text("""
                    UPDATE user_sessions 
                    SET is_active = FALSE, revoked_at = NOW()
                    WHERE user_id = :user_id
                """)
                await self.db.execute(query, {'user_id': user_id})
                await self.db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"批量注销会话失败: {e}")
            return False

    # =========================================================================
    # 日志记录
    # =========================================================================

    async def log_api_access(self, log_data: APIAccessLogCreate) -> bool:
        """记录API访问日志"""
        try:
            query = text("""
                INSERT INTO api_access_logs
                (user_id, session_id, method, url, query_params, request_body_hash,
                client_ip, user_agent, status_code, response_time_ms,
                request_size_bytes, response_size_bytes, error_message)
                VALUES
                (:user_id, :session_id, :method, :url, :query_params, :request_body_hash,
                :client_ip, :user_agent, :status_code, :response_time_ms,
                :request_size_bytes, :response_size_bytes, :error_message)
            """)
            
            await self.db.execute(query, log_data.dict())
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"记录API访问日志失败: {e}")
            return False

    async def log_operation(self, log_data: OperationLogCreate) -> bool:
        """记录操作日志"""
        try:
            query = text("""
                INSERT INTO operation_logs
                (user_id, session_id, operation_type, resource_type, resource_id,
                description, details, is_success, error_message, client_ip, user_agent)
                VALUES
                (:user_id, :session_id, :operation_type, :resource_type, :resource_id,
                :description, :details, :is_success, :error_message, :client_ip, :user_agent)
            """)
            
            await self.db.execute(query, log_data.dict())
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"记录操作日志失败: {e}")
            return False

    async def log_login_history(
        self,
        user_id: int,
        login_ip: Optional[str],
        user_agent: Optional[str],
        login_method: str,
        is_success: bool,
        failure_reason: Optional[str] = None
    ) -> bool:
        """记录登录历史"""
        try:
            query = text("""
                INSERT INTO login_histories
                (user_id, login_ip, user_agent, login_method, is_success, failure_reason)
                VALUES
                (:user_id, :login_ip, :user_agent, :login_method, :is_success, :failure_reason)
            """)
            
            await self.db.execute(query, {
                'user_id': user_id,
                'login_ip': login_ip,
                'user_agent': user_agent,
                'login_method': login_method,
                'is_success': is_success,
                'failure_reason': failure_reason
            })
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"记录登录历史失败: {e}")
            return False

    # =========================================================================
    # 辅助方法
    # =========================================================================

    async def _check_user_exists(self, username: str, email: str) -> bool:
        """检查用户名或邮箱是否存在"""
        try:
            query = text("SELECT id FROM users WHERE username = :username OR email = :email")
            result = await self.db.execute(query, {
                'username': username,
                'email': email
            })
            return result.fetchone() is not None
            
        except Exception as e:
            logger.error(f"检查用户存在性失败: {e}")
            return False

    async def _update_failed_login_attempts(self, user_id: int) -> None:
        """更新失败登录次数"""
        try:
            # 增加失败计数
            query = text("""
                UPDATE users 
                SET failed_login_attempts = failed_login_attempts + 1
                WHERE id = :user_id
            """)
            await self.db.execute(query, {'user_id': user_id})
            
            # 如果失败次数过多，锁定账户
            lock_query = text("""
                UPDATE users 
                SET is_active = FALSE
                WHERE id = :user_id AND failed_login_attempts >= 5
            """)
            await self.db.execute(lock_query, {'user_id': user_id})
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"更新失败登录次数: {e}")

    async def update_last_login(self, user_id: int) -> None:
        """更新最后登录时间"""
        try:
            query = text("""
                UPDATE users 
                SET last_login_at = NOW(), failed_login_attempts = 0
                WHERE id = :user_id
            """)
            await self.db.execute(query, {'user_id': user_id})
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"更新最后登录时间失败: {e}")