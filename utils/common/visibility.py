"""三层可见性模型（个人/空间/全局）+ 对象级权限判断。

设计（见方案讨论）：归属永远用户级（creator_id），可见性三层：
- private:   仅创建者可见可改（用户的"私人时间"）
- workspace: 空间成员可见可用，创建者/空间 owner/admin 可改（团队的"共同目标"）
- public:    全局可见可用，创建者/admin 可改（公共生态/市场）

visibility 是新 source of truth；旧 is_public 字段保留并同步（public→1，其余→0）以向后兼容。
"""
from typing import Optional

VISIBILITY_PRIVATE = "private"
VISIBILITY_WORKSPACE = "workspace"
VISIBILITY_PUBLIC = "public"
VISIBILITY_VALUES = {VISIBILITY_PRIVATE, VISIBILITY_WORKSPACE, VISIBILITY_PUBLIC}


def normalize_visibility(value: Optional[str], default: str = VISIBILITY_PRIVATE) -> str:
    """归一化 visibility，非法/空值回退默认（新建默认 private）。"""
    if value in VISIBILITY_VALUES:
        return value
    return default


def visibility_to_is_public(visibility: str) -> int:
    """同步旧 is_public：public→1，其余→0（向后兼容仍读 is_public 的代码）。"""
    return 1 if visibility == VISIBILITY_PUBLIC else 0


def is_public_to_visibility(is_public: Optional[int]) -> str:
    """旧 is_public → visibility 迁移映射：1→public，0/None→workspace（保留原空间共享行为）。"""
    return VISIBILITY_PUBLIC if is_public else VISIBILITY_WORKSPACE


def can_read_object(
    obj_visibility: str,
    obj_creator_id: Optional[int],
    obj_workspace_id: Optional[int],
    current_user_id: Optional[int],
    current_workspace_id: Optional[int],
    is_admin: bool = False,
) -> bool:
    """当前用户能否读取该对象。

    admin 全可见；public 全可见；workspace 限同空间成员；private 限创建者。
    """
    if is_admin:
        return True
    if obj_visibility == VISIBILITY_PUBLIC:
        return True
    if obj_visibility == VISIBILITY_WORKSPACE:
        return obj_workspace_id is not None and obj_workspace_id == current_workspace_id
    # private
    return obj_creator_id is not None and obj_creator_id == current_user_id


def can_modify_object(
    obj_visibility: str,
    obj_creator_id: Optional[int],
    obj_workspace_id: Optional[int],
    current_user_id: Optional[int],
    current_workspace_id: Optional[int],
    is_admin: bool = False,
    is_workspace_owner: bool = False,
) -> bool:
    """当前用户能否修改该对象。

    admin 全可改；创建者可改自己的对象；workspace 对象空间 owner 可改；
    public 对象仅创建者/admin 可改。普通空间成员对 workspace 对象只读。
    """
    if is_admin:
        return True
    if obj_creator_id is not None and obj_creator_id == current_user_id:
        return True
    if obj_visibility == VISIBILITY_WORKSPACE:
        return is_workspace_owner and obj_workspace_id == current_workspace_id
    return False


def build_visibility_orm_filter(
    model_class,
    viewer_user_id: Optional[int] = None,
    viewer_workspace_id: Optional[int] = None,
    is_admin: bool = False,
    null_fallback_to_workspace: bool = True,
):
    """构建三层可见性 ORM 过滤条件（DB 级，供 repository 复用）。

    与 AgentRepository._build_visibility_filter 同语义，但参数化 model_class，
    供 MCP/Skill/外部工具等工具类对象共享。

    admin 不过滤（返回 None）；否则可见 = public | (workspace 且同空间) |
    (private 且创建者) | (visibility 为 NULL 的存量行回退到"同空间可见")。

    Args:
        model_class: SQLAlchemy 模型类（须有 visibility/workspace_id/creator_id 列）
        viewer_user_id: 当前用户 ID（提供时启用 private 过滤）
        viewer_workspace_id: 当前用户工作空间 ID
        is_admin: admin 全可见
        null_fallback_to_workspace: 存量 visibility=NULL 行回退为"同空间可见"

    Returns:
        SQLAlchemy 条件，admin 返回 None（不追加过滤）。
    """
    from sqlalchemy import or_, and_
    if is_admin:
        return None
    conditions = [model_class.visibility == VISIBILITY_PUBLIC]
    if viewer_workspace_id is not None:
        conditions.append(and_(
            model_class.visibility == VISIBILITY_WORKSPACE,
            model_class.workspace_id == viewer_workspace_id,
        ))
        if null_fallback_to_workspace:
            # 存量 NULL 行回退：同空间可见（这些表原本按 workspace_id 精确匹配）
            conditions.append(and_(
                model_class.visibility.is_(None),
                model_class.workspace_id == viewer_workspace_id,
            ))
    if viewer_user_id is not None:
        conditions.append(and_(
            model_class.visibility == VISIBILITY_PRIVATE,
            model_class.creator_id == viewer_user_id,
        ))
    return or_(*conditions)
