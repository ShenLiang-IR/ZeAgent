-- 多租户 + RBAC DDL
-- 所有表 tb_ 前缀，关联字段名一致（user_id/workspace_id/role_id/permission_id/group_id）

-- 1. users → tb_user（rename + 加默认空间字段）
RENAME TABLE users TO tb_user;
ALTER TABLE tb_user ADD COLUMN default_workspace_id BIGINT NULL COMMENT '默认工作空间ID';
ALTER TABLE tb_user ADD COLUMN workspace_id BIGINT NULL COMMENT '当前工作空间ID（冗余，便于查询）';
ALTER TABLE tb_user ADD INDEX idx_workspace (workspace_id);

-- 2. tb_workspace（工作空间/租户隔离单元）
CREATE TABLE IF NOT EXISTS tb_workspace (
    workspace_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL COMMENT '空间名称',
    description TEXT,
    owner_id BIGINT COMMENT '创建者 user_id',
    status VARCHAR(20) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_owner (owner_id)
) COMMENT='工作空间（租户隔离单元）';

-- 3. tb_user_group（用户组，空间内分组）
CREATE TABLE IF NOT EXISTS tb_user_group (
    group_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    workspace_id BIGINT NOT NULL COMMENT '所属空间',
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_workspace (workspace_id)
) COMMENT='用户组';

-- 4. tb_role（角色，空间级+全局级）
CREATE TABLE IF NOT EXISTS tb_role (
    role_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    role_name VARCHAR(100) NOT NULL COMMENT '显示名',
    role_code VARCHAR(100) NOT NULL UNIQUE COMMENT '代码 admin/editor/viewer',
    workspace_id BIGINT NULL COMMENT '所属空间(NULL=全局角色)',
    description TEXT,
    is_system TINYINT DEFAULT 0 COMMENT '1=系统内置不可删',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_workspace (workspace_id)
) COMMENT='角色';

-- 5. tb_permission（权限定义）
CREATE TABLE IF NOT EXISTS tb_permission (
    permission_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    permission_code VARCHAR(100) NOT NULL UNIQUE COMMENT 'read:agent:*',
    domain VARCHAR(50) NOT NULL COMMENT 'read/write/delete/execute/manage',
    resource_type VARCHAR(50) NOT NULL COMMENT 'agent/mcp/tool/external_tool/skill/workspace/user',
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_domain_resource (domain, resource_type)
) COMMENT='权限定义';

-- 6. tb_user_workspace（用户-空间关联，多租户隔离核心）
CREATE TABLE IF NOT EXISTS tb_user_workspace (
    uw_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    workspace_id BIGINT NOT NULL,
    group_id BIGINT NULL COMMENT '用户组',
    is_owner TINYINT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_workspace (user_id, workspace_id),
    INDEX idx_workspace (workspace_id),
    INDEX idx_group (group_id)
) COMMENT='用户-空间关联';

-- 7. tb_user_role（用户-角色关联，空间级 RBAC）
CREATE TABLE IF NOT EXISTS tb_user_role (
    ur_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    workspace_id BIGINT NULL COMMENT '空间级角色(NULL=全局)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_role_ws (user_id, role_id, workspace_id),
    INDEX idx_user (user_id),
    INDEX idx_workspace (workspace_id)
) COMMENT='用户-角色关联';

-- 8. tb_role_permission（角色-权限关联）
CREATE TABLE IF NOT EXISTS tb_role_permission (
    rp_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    role_id BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_role_perm (role_id, permission_id),
    INDEX idx_role (role_id)
) COMMENT='角色-权限关联';

-- ===== 初始数据 =====

-- 默认空间
INSERT INTO tb_workspace (workspace_id, name, description, status) VALUES
(1, '默认空间', '系统默认工作空间', 'active')
ON DUPLICATE KEY UPDATE name=name;

-- 系统角色（全局，workspace_id=NULL）
INSERT INTO tb_role (role_name, role_code, workspace_id, description, is_system) VALUES
('管理员', 'admin', NULL, '全局管理员，拥有所有权限', 1),
('编辑者', 'editor', NULL, '可编辑 agent/mcp/tool/skill', 1),
('查看者', 'viewer', NULL, '只读权限', 1)
ON DUPLICATE KEY UPDATE role_name=VALUES(role_name);

-- 权限定义
INSERT INTO tb_permission (permission_code, domain, resource_type, description) VALUES
('read:agent:*', 'read', 'agent', '查看 Agent'),
('write:agent:*', 'write', 'agent', '创建/编辑 Agent'),
('delete:agent:*', 'delete', 'agent', '删除 Agent'),
('read:mcp:*', 'read', 'mcp', '查看 MCP'),
('write:mcp:*', 'write', 'mcp', '创建/编辑 MCP'),
('delete:mcp:*', 'delete', 'mcp', '删除 MCP'),
('read:tool:*', 'read', 'tool', '查看工具'),
('write:tool:*', 'write', 'tool', '创建/编辑工具'),
('read:external_tool:*', 'read', 'external_tool', '查看外部工具'),
('write:external_tool:*', 'write', 'external_tool', '创建/编辑外部工具'),
('read:skill:*', 'read', 'skill', '查看 Skill'),
('write:skill:*', 'write', 'skill', '创建/编辑 Skill'),
('delete:skill:*', 'delete', 'skill', '删除 Skill'),
('manage:workspace:*', 'manage', 'workspace', '管理空间'),
('manage:user:*', 'manage', 'user', '管理用户和权限（仅管理员）'),
-- admin 域通配（与 permissions.py admin fallback 一致）：覆盖 memory/menu/mode/audit 等所有资源
('read:*:*', 'read', '*', '管理员通配：读所有资源'),
('write:*:*', 'write', '*', '管理员通配：写所有资源'),
('delete:*:*', 'delete', '*', '管理员通配：删除所有资源'),
('execute:*:*', 'execute', '*', '管理员通配：执行所有资源'),
('manage:*:*', 'manage', '*', '管理员通配：管理所有资源')
ON DUPLICATE KEY UPDATE description=VALUES(description);

-- admin 角色所有权限
INSERT IGNORE INTO tb_role_permission (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM tb_role r, tb_permission p WHERE r.role_code = 'admin';

-- editor 角色：read+write agent/mcp/tool/external_tool/skill
INSERT IGNORE INTO tb_role_permission (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM tb_role r, tb_permission p
WHERE r.role_code = 'editor' AND p.domain IN ('read', 'write')
AND p.resource_type IN ('agent', 'mcp', 'tool', 'external_tool', 'skill');

-- viewer 角色：read 所有具体资源（排除通配，避免越权读 memory/audit 等管理员资源）
INSERT IGNORE INTO tb_role_permission (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM tb_role r, tb_permission p
WHERE r.role_code = 'viewer' AND p.domain = 'read' AND p.resource_type != '*';

-- 默认 admin 用户（密码 admin123，bcrypt hash）
-- 注意：实际使用时需改密码
INSERT INTO tb_user (username, phone, password_hash, role, status, default_workspace_id, workspace_id)
VALUES ('admin', '13800000000', '$2b$12$LJ3m4ys3Lk5v6wXyZq8r0e1f2g3h4i5j6k7l8m9n0o1p2q3r4s5t6u7v8', 'admin', 'active', 1, 1)
ON DUPLICATE KEY UPDATE username=username;

-- admin 用户关联默认空间
INSERT IGNORE INTO tb_user_workspace (user_id, workspace_id, is_owner, status)
SELECT u.id, 1, 1, 'active' FROM tb_user u WHERE u.username = 'admin';

-- admin 用户全局 admin 角色
INSERT IGNORE INTO tb_user_role (user_id, role_id, workspace_id)
SELECT u.id, r.role_id, NULL FROM tb_user u, tb_role r
WHERE u.username = 'admin' AND r.role_code = 'admin';
