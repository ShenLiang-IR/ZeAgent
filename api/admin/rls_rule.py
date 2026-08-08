from ._error_handler import handle_admin_errors
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger
from utils.config import get_config_db
from .permissions import require_read, require_write, require_delete
from .base import wrap_response
router = APIRouter(prefix="/rls-rules", tags=["rls_rules"])
class RLSRuleCreate(BaseModel):
    rule_id: str = Field(..., description=" rule_customer_org")
    table_name: str = Field(..., description=" *")
    column_name: Optional[str] = Field(None, description="table_name='*' ")
    operator: str = Field("=", description="=, IN, LIKE, >=, <=")
    value_source: str = Field("user", description="user/ fixed")
    value_key: Optional[str] = Field(None, description="value_source='user' ")
    fixed_value: Optional[str] = Field(None, description="value_source='fixed' ")
    priority: int = Field(100, ge=1, le=999, description="")
    enabled: bool = Field(True, description="")
    kb_id: Optional[str] = Field(None, description="IDNULL ")
    description: str = Field(..., description="")
class RLSRuleUpdate(BaseModel):
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    operator: Optional[str] = None
    value_source: Optional[str] = None
    value_key: Optional[str] = None
    fixed_value: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    kb_id: Optional[str] = None
    description: Optional[str] = None
def _validate_rls_rule(data: dict, is_create: bool = True) -> Optional[str]:
    import re
    value_source = data.get("value_source", "user")
    table_name = data.get("table_name", "")
    column_name = data.get("column_name")
    value_key = data.get("value_key")
    fixed_value = data.get("fixed_value")
    description = data.get("description", "")
    if is_create:
        rule_id = data.get("rule_id", "")
        if not rule_id or not rule_id.strip():
            return "rule_id "
        if len(rule_id) > 64:
            return "rule_id  64 "
        if not re.match(r'^[a-zA-Z0-9_-]+$', rule_id):
            return "rule_id "
    if not table_name or not table_name.strip():
        return "table_name "
    if table_name != "*":
        if not column_name or not column_name.strip():
            return "table_name  '*' column_name "
    if value_source == "user":
        if not value_key or not value_key.strip():
            return "value_source='user' value_key "
    elif value_source == "fixed":
        if not fixed_value or not fixed_value.strip():
            return "value_source='fixed' fixed_value "
    else:
        return f"value_source  'user'  'fixed'{value_source}"
    allowed_operators = {"=", "IN", "LIKE", ">=", "<=", ">", "<", "!="}
    if data.get("operator", "=") not in allowed_operators:
        return f"operator {', '.join(sorted(allowed_operators))}"
    priority = data.get("priority", 100)
    if priority < 1 or priority > 999:
        return "priority  1-999 "
    if not description or not description.strip():
        return "description "
    if len(description) > 256:
        return "description  256 "
    return None
def _filter_rules(
    rules: List[Dict[str, Any]],
    table_name: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if table_name:
        tn = table_name.lower()
        rules = [r for r in rules if tn in str(r.get("table_name", "")).lower()]
    if keyword:
        kw = keyword.lower()
        rules = [
            r for r in rules
            if kw in str(r.get("rule_id", "")).lower()
            or kw in str(r.get("description", "")).lower()
        ]
    return rules
@router.get("")
@handle_admin_errors("[RLSRuleAPI] ", detail_with_context=False)
async def list_rls_rules(
    skip: int = Query(0, ge=0, description=""),
    limit: int = Query(10, ge=1, le=100, description=""),
    kb_id: Optional[str] = Query(None, description="ID="),
    table_name: Optional[str] = Query(None, description=""),
    enabled: Optional[bool] = Query(None, description="true=false="),
    keyword: Optional[str] = Query(None, description=" rule_id  description "),
    user_permissions=Depends(require_read("rls_rule")),
):
    config_db = get_config_db()
    rules = config_db.rls_rules.get_all(kb_id=kb_id, enabled=enabled)
    if table_name or keyword:
        rules = _filter_rules(rules, table_name=table_name, keyword=keyword)
    total = len(rules)
    paginated = rules[skip : skip + limit]
    return {
        "rls_rules": paginated,
        "total": total,
        "count": len(paginated),
        "skip": skip,
        "limit": limit,
    }
@router.get("/{rule_id}")
@handle_admin_errors("[RLSRuleAPI]  ({rule_id})", detail_with_context=False)
async def get_rls_rule(
    rule_id: str,
    user_permissions=Depends(require_read("rls_rule")),
):
    config_db = get_config_db()
    rule = config_db.rls_rules.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"{rule_id}")
    return rule
@router.post("")
@handle_admin_errors("[RLSRuleAPI] ", detail_with_context=False)
async def create_rls_rule(
    data: RLSRuleCreate,
    user_permissions=Depends(require_write("rls_rule")),
):
    logger.info(f"[RLSRuleAPI]  {user_permissions.user_id}  RLS {data.rule_id}")
    err = _validate_rls_rule(data.model_dump(), is_create=True)
    if err:
        raise HTTPException(status_code=400, detail=err)
    config_db = get_config_db()
    if config_db.rls_rules.exists(data.rule_id):
        raise HTTPException(status_code=400, detail=f" ID {data.rule_id}")
    success = config_db.rls_rules.save(
        rule_id=data.rule_id.strip(),
        table_name=data.table_name.strip(),
        column_name=data.column_name.strip() if data.column_name else None,
        operator=data.operator,
        value_source=data.value_source,
        value_key=data.value_key.strip() if data.value_key else None,
        fixed_value=data.fixed_value.strip() if data.fixed_value else None,
        priority=data.priority,
        enabled=data.enabled,
        kb_id=data.kb_id.strip() if data.kb_id else None,
        description=data.description.strip(),
    )
    if not success:
        raise HTTPException(status_code=500, detail=" RLS ")
    logger.info(f" RLS : {data.rule_id}")
    rule = config_db.rls_rules.get_by_id(data.rule_id)
    return {
        "message": f"RLS {data.rule_id}",
        "status": "success",
        "data": rule,
    }
@router.put("/{rule_id}")
@handle_admin_errors("[RLSRuleAPI]  ({rule_id})", detail_with_context=False)
async def update_rls_rule(
    rule_id: str,
    data: RLSRuleUpdate,
    user_permissions=Depends(require_write("rls_rule")),
):
    logger.info(f"[RLSRuleAPI]  {user_permissions.user_id}  RLS {rule_id}")
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="未提供更新字段")
    err = _validate_rls_rule({**update_data, "rule_id": rule_id}, is_create=False)
    if err:
        raise HTTPException(status_code=400, detail=err)
    config_db = get_config_db()
    if not config_db.rls_rules.exists(rule_id):
        raise HTTPException(status_code=404, detail=f"{rule_id}")
    if "enabled" in update_data:
        update_data["enabled"] = 1 if update_data["enabled"] else 0
    success = config_db.rls_rules.update(rule_id, **update_data)
    if not success:
        raise HTTPException(status_code=500, detail=" RLS ")
    logger.info(f"[RLSRuleAPI] RLS : {rule_id}")
    rule = config_db.rls_rules.get_by_id(rule_id)
    return {
        "message": f"RLS {rule_id}",
        "status": "success",
        "data": rule,
    }
@router.delete("/{rule_id}")
@handle_admin_errors("[RLSRuleAPI]  ({rule_id})", detail_with_context=False)
async def delete_rls_rule(
    rule_id: str,
    user_permissions=Depends(require_delete("rls_rule")),
):
    logger.info(f"[RLSRuleAPI]  {user_permissions.user_id}  RLS {rule_id}")
    config_db = get_config_db()
    rule = config_db.rls_rules.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"{rule_id}")
    success = config_db.rls_rules.delete(rule_id)
    if not success:
        raise HTTPException(status_code=500, detail=" RLS ")
    return {
        "message": f"RLS {rule.get('description', rule_id)}",
        "status": "success",
        "data": {},
    }
@router.delete("")
@handle_admin_errors("[RLSRuleAPI] ", detail_with_context=False)
async def batch_delete_rls_rules(
    ids: str = Query(..., description=" rule_id rule1,rule2"),
    user_permissions=Depends(require_delete("rls_rule")),
):
    rule_ids = [rid.strip() for rid in ids.split(",") if rid.strip()]
    if not rule_ids:
        raise HTTPException(status_code=400, detail=" rule_id")
    logger.info(f"[RLSRuleAPI]  {user_permissions.user_id}  RLS {rule_ids}")
    config_db = get_config_db()
    deleted_count = config_db.rls_rules.batch_delete(rule_ids)
    return {
        "message": f" {deleted_count}  RLS ",
        "status": "success",
        "data": {
            "deleted_count": deleted_count,
            "deleted_ids": rule_ids,
        },
    }
@router.patch("/{rule_id}/status")
@handle_admin_errors("[RLSRuleAPI]  ({rule_id})", detail_with_context=False)
async def toggle_rls_rule_status(
    rule_id: str,
    enabled: bool = Query(..., description="true=false="),
    user_permissions=Depends(require_write("rls_rule")),
):
    logger.info(f"[RLSRuleAPI]  {user_permissions.user_id} {rule_id} -> {enabled}")
    config_db = get_config_db()
    if not config_db.rls_rules.exists(rule_id):
        raise HTTPException(status_code=404, detail=f"{rule_id}")
    success = config_db.rls_rules.toggle_enabled(rule_id, enabled)
    if not success:
        raise HTTPException(status_code=500, detail="切换 RLS 规则启用状态失败")
    return {
        "message": f"{rule_id} -> {'启用' if enabled else '禁用'}",
        "status": "success",
        "data": {"enabled": enabled},
    }
@router.get("/table-columns")
@handle_admin_errors("[RLSRuleAPI] ", detail_with_context=False)
async def get_table_columns(
    table_name: str = Query(..., description=""),
    kb_id: Optional[str] = Query(None, description="ID"),
    user_permissions=Depends(require_read("rls_rule")),
):
    if not table_name or not table_name.strip():
        raise HTTPException(status_code=400, detail="table_name ")
    logger.debug(f"[RLSRuleAPI] table_name={table_name}, kb_id={kb_id}")
    return {
        "table_name": table_name,
        "columns": [],
        "notice": "/"
    }
@router.get("/check-rule-id")
@handle_admin_errors("[RLSRuleAPI]  rule_id ", detail_with_context=False)
async def check_rule_id_unique(
    rule_id: str = Query(..., description=" rule_id"),
    user_permissions=Depends(require_read("rls_rule")),
):
    if not rule_id or not rule_id.strip():
        return wrap_response(data={"exists": False, "valid": False}, message="rule_id 不能为空", success=False)
    config_db = get_config_db()
    exists = config_db.rls_rules.exists(rule_id.strip())
    return wrap_response(data={
        "exists": exists,
        "valid": not exists,
        "rule_id": rule_id.strip(),
    })