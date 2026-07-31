-- =========================================================
-- 智能电网负荷预测系统 - 用户管理与权限控制
-- 用于用户认证、角色权限管理
-- =========================================================

-- 创建用户表
CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL COMMENT '用户名(唯一)',
    email VARCHAR(100) UNIQUE NOT NULL COMMENT '邮箱',
    hashed_password VARCHAR(255) NOT NULL COMMENT '加密密码',
    full_name VARCHAR(100) COMMENT '全名',
    department VARCHAR(50) COMMENT '部门',
    phone VARCHAR(20) COMMENT '电话',
    
    -- 状态管理
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    is_verified BOOLEAN DEFAULT FALSE COMMENT '是否验证',
    
    -- 安全相关
    failed_login_attempts INT DEFAULT 0 COMMENT '失败登录次数',
    last_login_at TIMESTAMP NULL COMMENT '最后登录时间',
    password_changed_at TIMESTAMP NULL COMMENT '密码修改时间',
    
    -- 审计字段  
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by BIGINT COMMENT '创建人',
    updated_by BIGINT COMMENT '更新人'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- 创建角色表
CREATE TABLE IF NOT EXISTS roles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL COMMENT '角色名',
    description VARCHAR(255) COMMENT '描述',
    level INT NOT NULL DEFAULT 1 COMMENT '权限等级(数字越大权限越高)',
    
    -- 系统角色标识(不可删除)
    is_system_role BOOLEAN DEFAULT FALSE COMMENT '是否系统默认角色',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='角色表';

-- 创建权限表
CREATE TABLE IF NOT EXISTS permissions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL COMMENT '权限名称',
    code VARCHAR(100) UNIQUE NOT NULL COMMENT '权限代码',
    description VARCHAR(255) COMMENT '权限描述',
    category VARCHAR(50) COMMENT '权限分类',
    
    -- 资源类型和操作
    resource VARCHAR(50) COMMENT '操作资源', -- API, DATA, MODEL
    action VARCHAR(50) COMMENT '操作动作', -- CREATE, READ, UPDATE, DELETE
    
    is_system_permission BOOLEAN DEFAULT FALSE COMMENT '是否系统权限',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='权限表';

-- 用户-角色关联表
CREATE TABLE IF NOT EXISTS user_roles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    
    -- 授予信息
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by BIGINT COMMENT '授予人',
    granted_reason VARCHAR(255) COMMENT '授予原因',
    
    -- 有效期
    expires_at TIMESTAMP NULL COMMENT '角色过期时间',
    
    -- 约束
    UNIQUE KEY unique_user_role (user_id, role_id),
    KEY idx_user_id (user_id),
    KEY idx_role_id (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户角色关联';

-- 角色-权限关联表
CREATE TABLE IF NOT EXISTS role_permissions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    role_id BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by BIGINT COMMENT '授予人',
    
    UNIQUE KEY unique_role_permission (role_id, permission_id),
    KEY idx_role_id (role_id),
    KEY idx_permission_id (permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='角色权限关联';

-- 登录历史记录表
CREATE TABLE IF NOT EXISTS login_histories (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    login_ip VARCHAR(45) COMMENT '登录IP',
    user_agent VARCHAR(500) COMMENT '用户代理',
    login_method VARCHAR(50) COMMENT '登录方式', -- password, oauth2, sso
    
    -- 登录结果
    is_success BOOLEAN DEFAULT TRUE COMMENT '是否成功',
    failure_reason VARCHAR(255) COMMENT '失败原因',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_id (user_id),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录历史';

-- 用户会话表
CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    session_id VARCHAR(100) NOT NULL COMMENT '会话ID',
    jwt_token TEXT COMMENT 'JWT令牌',
    refresh_token TEXT COMMENT '刷新令牌',
    
    -- 客户端信息
    client_ip VARCHAR(45) COMMENT '客户端IP',
    user_agent VARCHAR(500) COMMENT '用户代理',
    platform VARCHAR(50) COMMENT '平台', -- web, mobile, api
    
    -- 有效期管理
    expires_at TIMESTAMP NOT NULL COMMENT '过期时间',
    last_activity TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最后活动',
    
    -- 状态
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否活跃',
    revoked_at TIMESTAMP NULL COMMENT '注销时间',
    
    -- 索引
    UNIQUE KEY unique_session_id (session_id),
    KEY idx_user_id (user_id),
    KEY idx_expires_at (expires_at),
    KEY idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户会话表';

-- API访问日志表
CREATE TABLE IF NOT EXISTS api_access_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT COMMENT '用户ID',
    session_id VARCHAR(100) COMMENT '会话ID',
    
    -- 请求信息
    method VARCHAR(10) NOT NULL COMMENT 'HTTP方法',
    url VARCHAR(500) NOT NULL COMMENT '请求URL',
    query_params TEXT COMMENT '查询参数',
    request_body TEXT COMMENT '请求body',
    
    -- 客户端
    client_ip VARCHAR(45) NOT NULL COMMENT '客户端IP',
    user_agent VARCHAR(500) COMMENT '用户代理',
    
    -- 响应信息
    status_code INT COMMENT '状态码',
    response_body TEXT COMMENT '响应body',
    error_message TEXT COMMENT '错误信息',
    
    -- 性能
    response_time_ms INT COMMENT '响应时间(毫秒)',
    request_size_bytes INT COMMENT '请求大小(字节)',
    response_size_bytes INT COMMENT '响应大小(字节)',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_id (user_id),
    KEY idx_client_ip (client_ip),
    KEY idx_created_at (created_at),
    KEY idx_status_code (status_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='API访问日志';

-- 操作日志表
CREATE TABLE IF NOT EXISTS operation_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT COMMENT '操作用户',
    session_id VARCHAR(100) COMMENT '会话ID',
    
    -- 操作信息
    operation_type VARCHAR(50) NOT NULL COMMENT '操作类型'， -- CREATE, UPDATE, DELETE, LOGIN, LOGOUT
    resource_type VARCHAR(50) NOT NULL COMMENT '资源类型', -- USER, MODEL, DATA
    resource_id VARCHAR(100) COMMENT '资源ID',
    
    -- 详细信息
    description VARCHAR(500) NOT NULL COMMENT '操作描述',
    details JSON COMMENT '详细信息',
    
    -- 结果
    is_success BOOLEAN DEFAULT TRUE COMMENT '是否成功',
    error_message TEXT,
    
    -- 客户端
    client_ip VARCHAR(45) COMMENT '客户端IP',
    user_agent VARCHAR(500) COMMENT '用户代理',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_id (user_id),
    KEY idx_operation_type (operation_type),
    KEY idx_resource_type (resource_type),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作日志';

-- 数据表添加外键约束
ALTER TABLE user_roles ADD CONSTRAINT fk_ur_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_roles ADD CONSTRAINT fk_ur_role_id FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE;

ALTER TABLE role_permissions ADD CONSTRAINT fk_rp_role_id FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE;
ALTER TABLE role_permissions ADD CONSTRAINT fk_rp_permission_id FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE;

ALTER TABLE login_histories ADD CONSTRAINT fk_lh_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_sessions ADD CONSTRAINT fk_us_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE api_access_logs ADD CONSTRAINT fk_al_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE operation_logs ADD CONSTRAINT fk_ol_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

-- =========================================================
-- 初始化默认数据
-- =========================================================

-- 插入系统角色
INSERT IGNORE INTO roles (name, description, level, is_system_role) VALUES
('系统管理员', '拥有系统所有权限', 100, TRUE),
('管理员', '系统管理员', 90, TRUE),
('运维人员', '负责系统运维', 80, TRUE),
('高级工程师', '高级开发权限', 70, TRUE),
('普通用户', '基础使用权限', 50, TRUE),
('访客', '只读权限', 20, TRUE);

-- 插入系统权限
INSERT IGNORE INTO permissions (name, code, description, category, resource, action, is_system_permission) VALUES
-- 用户管理
('用户创建', 'user:create', '创建用户', 'USER_MGMT', 'USER', 'CREATE', TRUE),
('用户查看', 'user:read', '查看用户信息', 'USER_MGMT', 'USER', 'READ', TRUE),
('用户更新', 'user:update', '更新用户信息', 'USER_MGMT', 'USER', 'UPDATE', TRUE),
('用户删除', 'user:delete', '删除用户', 'USER_MGMT', 'USER', 'DELETE', TRUE),
('重置用户密码', 'user:reset_password', '重置用户密码', 'USER_MGMT', 'USER', 'UPDATE', TRUE),

-- 角色权限管理
('角色管理', 'role:manage', '角色分配管理', 'ROLE_MGMT', 'ROLE', 'MANAGE', TRUE),
('权限管理', 'permission:manage', '权限分配管理', 'PERMISSION_MGMT', 'PERMISSION', 'MANAGE', TRUE),

-- API访问权限
('API天气数据', 'api:weather', '获取天气数据', 'API_ACCESS', 'WEATHER', 'READ', TRUE),
('API负荷预测', 'api:prediction', '获取负荷预测', 'API_ACCESS', 'PREDICTION', 'READ', TRUE),
('API模型管理', 'api:model:manage', '管理模型', 'API_ACCESS', 'MODEL', 'MANAGE', TRUE),
('API系统管理', 'api:system:admin', '系统管理', 'API_ACCESS', 'SYSTEM', 'ADMIN', TRUE),

-- 数据访问权限
('数据查看', 'data:read', '查看业务数据', 'DATA_ACCESS', 'DATA', 'READ', TRUE),
('数据导出', 'data:export', '导出数据', 'DATA_ACCESS', 'DATA', 'EXPORT', TRUE),

-- 模型操作权限
('模型训练', 'model:train', '模型训练', 'MODEL_OPS', 'MODEL', 'TRAIN', TRUE),
('模型部署', 'model:deploy', '模型部署', 'MODEL_OPS', 'MODEL', 'DEPLOY', TRUE),
('模型删除', 'model:delete', '删除模型', 'MODEL_OPS', 'MODEL', 'DELETE', TRUE);

-- 分配权限给系统角色
-- 系统管理员 - 拥有全部权限
INSERT IGNORE INTO role_permissions (role_id, permission_id, granted_by) 
SELECT r.id, p.id, NULL FROM roles r, permissions p WHERE r.name = '系统管理员';

-- 管理员 - 除系统管理外的所有权限
INSERT IGNORE INTO role_permissions (role_id, permission_id, granted_by)
SELECT r.id, p.id, NULL FROM roles r, permissions p
WHERE r.name = '管理员' AND p.code NOT LIKE 'api:system:%';

-- 运维人员 - 基础权限
INSERT IGNORE INTO role_permissions (role_id, permission_id, granted_by)
SELECT r.id, p.id, NULL FROM roles r, permissions p
WHERE r.name = '运维人员' 
AND p.category IN ('DATA_ACCESS', 'API_ACCESS')
AND p.action IN ('READ', 'EXPORT');

-- 普通用户 - 只读权限
INSERT IGNORE INTO role_permissions (role_id, permission_id, granted_by)
SELECT r.id, p.id, NULL FROM roles r, permissions p
WHERE r.name = '普通用户'
AND p.action = 'READ'
AND p.category IN ('API_ACCESS', 'DATA_ACCESS');

-- 访客 - 最低权限
INSERT IGNORE INTO role_permissions (role_id, permission_id, granted_by)
SELECT r.id, p.id, NULL FROM roles r, permissions p
WHERE r.name = '访客' AND p.code IN ('api:weather', 'api:prediction', 'data:read');

-- =========================================================
-- 便捷查询视图
-- =========================================================

-- 用户权限视图
CREATE OR REPLACE VIEW user_permissions_view AS
SELECT 
    u.id as user_id,
    u.username,
    u.full_name,
    u.email,
    u.is_active,
    r.name as role_name,
    p.name as permission_name,
    p.code as permission_code,
    p.resource,
    p.action
FROM users u
    LEFT JOIN user_roles ur ON u.id = ur.user_id
    LEFT JOIN roles r ON ur.role_id = r.id
    LEFT JOIN role_permissions rp ON r.id = rp.role_id
    LEFT JOIN permissions p ON rp.permission_id = p.id
WHERE u.is_active = TRUE;

-- 活跃会话视图
CREATE OR REPLACE VIEW active_sessions_view AS
SELECT 
    us.id,
    us.session_id,
    u.username,
    u.full_name,
    us.client_ip,
    us.platform,
    us.last_activity,
    us.expires_at,
    TIMESTAMPDIFF(MINUTE, us.last_activity, NOW()) as idle_minutes
FROM user_sessions us
    LEFT JOIN users u ON us.user_id = u.id
WHERE us.is_active = TRUE 
    AND us.expires_at > NOW();

-- 登录统计视图
CREATE OR REPLACE VIEW login_stats_view AS
SELECT 
    u.id as user_id,
    u.username,
    COUNT(lh.id) as total_logins,
    COUNT(CASE WHEN lh.is_success = TRUE THEN 1 END) as success_logins,
    COUNT(CASE WHEN lh.is_success = FALSE THEN 1 END) as failed_logins,
    MAX(lh.created_at) as last_login,
    AVG(CASE WHEN lh.is_success = TRUE THEN TIMESTAMPDIFF(SECOND, lh.created_at, NOW()) END) as avg_session_duration
FROM users u
    LEFT JOIN login_histories lh ON u.id = lh.user_id
WHERE u.is_active = TRUE
GROUP BY u.id, u.username;

-- =========================================================
-- 索引优化
-- =========================================================

-- 添加更多查询性能优化索引
CREATE INDEX idx_users_username_email ON users(username, email);
CREATE INDEX idx_roles_name_level ON roles(name, level);
CREATE INDEX idx_permissions_code ON permissions(code);
CREATE INDEX idx_user_roles_ua ON user_roles(user_id, role_id, expires_at);
CREATE INDEX idx_role_permissions_rp ON role_permissions(role_id, permission_id);
CREATE INDEX idx_login_histories_user_date ON login_histories(user_id, created_at);
CREATE INDEX idx_api_logs_user_date ON api_access_logs(user_id, created_at);
CREATE INDEX idx_api_logs_ip_date ON api_access_logs(client_ip, created_at);
CREATE INDEX idx_operation_logs_user_op ON operation_logs(user_id, operation_type, created_at);

-- =========================================================
-- 完成信息
-- =========================================================

/*
✅ 用户管理认证表创建完成

功能特性:
- 用户注册登录
- 角色权限(RBAC)
- JWT会话管理
- API访问日志
- 操作审计日志
- 便捷查询视图

使用方式:
1. 执行此SQL创建表结构
2. 通过应用层API管理用户
3. 集成FastAPI认证中间件
4. 使用JWT保护API端点

相关文件:
- realtime_api/auth/ (认证中间件)
- realtime_api/crud/auth_crud.py (操作实现)
- realtime_api/schemas/auth.py (数据模型)
- docs/USER_MANAGEMENT_GUIDE.md (使用指南)
*/
