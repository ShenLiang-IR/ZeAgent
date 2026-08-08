"""回填：为 admin 角色补 5 个域通配权限，修复 permission.json 移除后 DB seed 不全导致的 403。

根因：权限从 permission.json 迁移到 DB (tb_role_permission) 后，seed
(multi_tenant_rbac.sql) 只定义了 7 个资源(agent/mcp/tool/external_tool/skill/
workspace/user)的权限。admin 端点还用到 memory/menu/mode/audit/dict/security/
subagent/trigger/usage 等资源——tb_permission 里没有 → admin"授权所有 tb_permission"
也拿不到 → 访问记忆管理(及这些资源)报 403 read:memory:*。

修复：补 5 个域通配(read/write/delete/execute/manage :*:*)到 tb_permission，
admin 经"所有权限"授权自动获得 → 超管，一次覆盖所有资源(含 memory)及未来新增资源。
与 _get_default_permissions 的 admin fallback 一致。

用法：python command/migrate_admin_wildcard_permissions.py
幂等：ON DUPLICATE KEY UPDATE / INSERT IGNORE。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 5 个域通配权限（与 utils/common/permissions.py 的 admin fallback 默认一致）
WILDCARD_PERMS = [
    ("read:*:*", "read", "*", "管理员通配：读所有资源"),
    ("write:*:*", "write", "*", "管理员通配：写所有资源"),
    ("delete:*:*", "delete", "*", "管理员通配：删除所有资源"),
    ("execute:*:*", "execute", "*", "管理员通配：执行所有资源"),
    ("manage:*:*", "manage", "*", "管理员通配：管理所有资源"),
]


def run_migration(session_factory, log=print):
    """补 5 个域通配权限到 tb_permission + 重新授权 admin 所有权限。

    Args:
        session_factory: 返回 DB session 上下文管理器的可调用
        log: 日志函数
    Returns: WILDCARD_PERMS
    """
    from sqlalchemy import text

    with session_factory() as s:
        for code, domain, rt, desc in WILDCARD_PERMS:
            s.execute(
                text(
                    "INSERT INTO tb_permission (permission_code, domain, resource_type, description) "
                    "VALUES (:code, :d, :rt, :desc) "
                    "ON DUPLICATE KEY UPDATE description=VALUES(description)"
                ),
                {"code": code, "d": domain, "rt": rt, "desc": desc},
            )
            log(f"ensured permission: {code}")
        # admin 角色"授权所有 tb_permission"（含新增通配）；INSERT IGNORE 幂等
        s.execute(
            text(
                "INSERT IGNORE INTO tb_role_permission (role_id, permission_id) "
                "SELECT r.role_id, p.permission_id FROM tb_role r, tb_permission p "
                "WHERE r.role_code = 'admin'"
            )
        )
        s.commit()
    log("done: 5 wildcards ensured + admin re-granted all permissions")
    return WILDCARD_PERMS


def main():
    from infrastructure.database.sessions import get_config_session

    run_migration(get_config_session)


if __name__ == "__main__":
    main()
