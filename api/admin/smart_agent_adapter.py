from fastapi import APIRouter, Header, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from loguru import logger
from .common import verify_token
def api_response(data: Any = None, message: str = "success", success: bool = True) -> Dict[str, Any]:
    return {
        "code": "0000000000000000" if success else "9999999999999999",
        "message": message,
        "data": data
    }
DICT_DATA = {
    "MODEL_TP_CLS": [
        {"dictId": "LLM", "dictName": "LLM", "dictDesc": ""},
        {"dictId": "Embedding", "dictName": "Embedding", "dictDesc": ""},
        {"dictId": "Image", "dictName": "Image", "dictDesc": ""},
        {"dictId": "Audio", "dictName": "Audio", "dictDesc": ""},
        {"dictId": "Video", "dictName": "Video", "dictDesc": ""},
        {"dictId": "Multimodal", "dictName": "Multimodal", "dictDesc": ""},
    ],
    "SPEC_MODEL_LABEL": [
        {"dictId": "chat", "dictName": "", "dictDesc": ""},
        {"dictId": "completion", "dictName": "", "dictDesc": ""},
        {"dictId": "reasoning", "dictName": "", "dictDesc": ""},
        {"dictId": "coding", "dictName": "", "dictDesc": ""},
        {"dictId": "function_call", "dictName": "", "dictDesc": ""},
        {"dictId": "vision", "dictName": "", "dictDesc": ""},
    ],
    "ENABLE_STATUS": [
        {"dictId": "0", "dictName": ""},
        {"dictId": "1", "dictName": ""},
    ],
    "DISPLAY_STATUS": [
        {"dictId": "0", "dictName": ""},
        {"dictId": "1", "dictName": ""},
    ],
    "MENU_TYPE": [
        {"dictId": "directory", "dictName": ""},
        {"dictId": "menu", "dictName": ""},
        {"dictId": "button", "dictName": ""},
    ],
    "YES_NO": [
        {"dictId": "0", "dictName": ""},
        {"dictId": "1", "dictName": ""},
    ],
    "VISIBLE_SCOPE": [
        {"dictId": "1", "dictName": ""},
        {"dictId": "2", "dictName": ""},
        {"dictId": "3", "dictName": ""},
    ],
    "RELEASE_STATUS": [
        {"dictId": "0", "dictName": ""},
        {"dictId": "1", "dictName": ""},
        {"dictId": "2", "dictName": ""},
    ],
}
router = APIRouter(tags=["smart-agent-llm-admin"], dependencies=[Depends(verify_token)])
class DictRequest(BaseModel):
    dict_type_list: List[str] = Field(..., alias="dictTypeList")
    class Config:
        populate_by_name = True
class PageQuery(BaseModel):
    page_no: int = Field(1, alias="pageNo", ge=1)
    page_size: int = Field(10, alias="pageSize", ge=1, le=100)
    class Config:
        populate_by_name = True
class IdRequest(BaseModel):
    pr_key_id: str = Field(..., alias="prKeyId")
    class Config:
        populate_by_name = True
@router.post("/api/dict/entries/actions/getDicList")
async def get_dict_list(request: DictRequest):
    try:
        result = {}
        for dict_type in request.dict_type_list:
            dict_data = DICT_DATA.get(dict_type) or DICT_DATA.get(dict_type.upper())
            result[dict_type] = dict_data if dict_data else []
        logger.info(f"[Dict] : {request.dict_type_list}")
        return api_response(result)
    except Exception as e:
        logger.error(f"[Dict] : {str(e)}")
        return api_response(None, message=f"字典查询失败: {str(e)}", success=False)
@router.post("/api/agent/page")
async def agent_page(config: PageQuery):
    logger.info(f"[Agent] : pageNo={config.page_no}")
    return api_response({
        "list": [],
        "total": 0,
        "pageNo": config.page_no,
        "pageSize": config.page_size
    })
@router.post("/api/agent/updateStatus")
async def agent_update_status(config: Dict[str, Any]):
    logger.info(f"[Agent] ")
    return api_response(message="操作成功")
@router.post("/api/agent/delete")
async def agent_delete(config: IdRequest):
    logger.info(f"[Agent] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/api/agent/check")
async def agent_check(config: Dict[str, Any]):
    logger.info(f"[Agent] ")
    return api_response({"exists": False})
@router.post("/api/agent/create")
async def agent_create(config: Dict[str, Any]):
    logger.info(f"[Agent] ")
    return api_response(message="操作成功")
@router.post("/api/agent/detail")
async def agent_detail(config: IdRequest):
    logger.info(f"[Agent] : {config.pr_key_id}")
    return api_response({})
@router.post("/api/agent/update")
async def agent_update(config: Dict[str, Any]):
    logger.info(f"[Agent] ")
    return api_response(message="操作成功")
@router.post("/api/agent/relation")
async def agent_relation(config: Dict[str, Any]):
    logger.info(f"[Agent] ")
    return api_response({"list": []})
@router.post("/api/mcp/register")
async def mcp_register(config: Dict[str, Any]):
    logger.info(f"[MCP] ")
    return api_response(message="操作成功")
@router.post("/api/mcp/update")
async def mcp_update(config: Dict[str, Any]):
    logger.info(f"[MCP] ")
    return api_response(message="操作成功")
@router.post("/api/mcp/updateStatus")
async def mcp_update_status(config: Dict[str, Any]):
    logger.info(f"[MCP] ")
    return api_response(message="操作成功")
@router.post("/api/mcp/page")
async def mcp_page(config: PageQuery):
    logger.info(f"[MCP] ")
    return api_response({
        "list": [],
        "total": 0,
        "pageNo": config.page_no,
        "pageSize": config.page_size
    })
@router.post("/api/mcp/detail")
async def mcp_detail(config: IdRequest):
    logger.info(f"[MCP] : {config.pr_key_id}")
    return api_response({})
@router.post("/api/mcp/delete")
async def mcp_delete(config: IdRequest):
    logger.info(f"[MCP] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/api/mcp/testConnect")
async def mcp_test_connect(config: Dict[str, Any]):
    logger.info(f"[MCP] ")
    return api_response(message="操作成功")
@router.post("/api/mcpIntfc/page")
async def mcp_intfc_page(config: PageQuery):
    logger.info(f"[MCP Interface] ")
    return api_response({
        "list": [],
        "total": 0,
        "pageNo": config.page_no,
        "pageSize": config.page_size
    })
@router.post("/api/mcpIntfc/sync")
async def mcp_intfc_sync(config: Dict[str, Any]):
    logger.info(f"[MCP Interface] ")
    return api_response(message="操作成功")
@router.post("/skillManage/createSkill")
async def skill_create(config: Dict[str, Any]):
    logger.info(f"[Skill] ")
    return api_response(message="操作成功")
@router.post("/skillManage/deleteSkill")
async def skill_delete(config: IdRequest):
    logger.info(f"[Skill] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/skillManage/getAgentList")
async def skill_get_agent_list(config: Dict[str, Any]):
    logger.info(f"[Skill] Agent")
    return api_response({"list": []})
@router.post("/skillManage/getSkillDetail")
async def skill_get_detail(config: IdRequest):
    logger.info(f"[Skill] : {config.pr_key_id}")
    return api_response({})
@router.post("/skillManage/page")
async def skill_page(config: PageQuery):
    logger.info(f"[Skill] ")
    return api_response({
        "list": [],
        "total": 0,
        "pageNo": config.page_no,
        "pageSize": config.page_size
    })
@router.post("/skillManage/testExecute")
async def skill_test_execute(config: Dict[str, Any]):
    logger.info(f"[Skill] ")
    return api_response({"result": ""})
@router.post("/skillManage/updateSkill")
async def skill_update(config: Dict[str, Any]):
    logger.info(f"[Skill] ")
    return api_response(message="操作成功")
@router.post("/skillManage/updateSkillStatus")
async def skill_update_status(config: Dict[str, Any]):
    logger.info(f"[Skill] ")
    return api_response(message="操作成功")
@router.post("/apiManager/apiNodeAdd")
async def api_node_add(config: Dict[str, Any]):
    logger.info(f"[API Node] ")
    return api_response(message="操作成功")
@router.post("/apiManager/apiNodeDel")
async def api_node_del(config: IdRequest):
    logger.info(f"[API Node] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/apiManager/apiNodeDownload")
async def api_node_download(config: Dict[str, Any]):
    logger.info(f"[API Node] ")
    return api_response({})
@router.post("/apiManager/apiNodeQry")
async def api_node_qry(config: Dict[str, Any]):
    logger.info(f"[API Node] ")
    return api_response({"list": [], "total": 0})
@router.post("/apiManager/apiNodeUp")
async def api_node_up(config: Dict[str, Any]):
    logger.info(f"[API Node] ")
    return api_response(message="操作成功")
@router.post("/apiManager/apiInterfaceAdd")
async def api_interface_add(config: Dict[str, Any]):
    logger.info(f"[API Interface] ")
    return api_response(message="操作成功")
@router.post("/apiManager/apiInterfaceDel")
async def api_interface_del(config: IdRequest):
    logger.info(f"[API Interface] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/apiManager/apiInterfaceDownlodad")
async def api_interface_download(config: Dict[str, Any]):
    logger.info(f"[API Interface] ")
    return api_response({})
@router.post("/apiManager/apiInterfaceQry")
async def api_interface_qry(config: Dict[str, Any]):
    logger.info(f"[API Interface] ")
    return api_response({"list": [], "total": 0})
@router.post("/apiManager/apiInterfaceTest")
async def api_interface_test(config: Dict[str, Any]):
    logger.info(f"[API Interface] ")
    return api_response({"result": ""})
@router.post("/apiManager/apiInterfaceUp")
async def api_interface_up(config: Dict[str, Any]):
    logger.info(f"[API Interface] ")
    return api_response(message="操作成功")
@router.post("/apiManager/apiNodeAndIntefaceQry")
async def api_node_and_interface_qry(config: Dict[str, Any]):
    logger.info(f"[API Manager] ")
    return api_response({"nodes": [], "interfaces": []})
@router.post("/api/knowledgebase/getDatabases")
async def knowledge_get_databases(config: Dict[str, Any]):
    logger.info(f"[Knowledge] ")
    return api_response({"list": []})
@router.post("/api/knowledgebase/searchTables")
async def knowledge_search_tables(config: Dict[str, Any]):
    logger.info(f"[Knowledge] ")
    return api_response({"list": []})
@router.post("/api/knowledgebase/save")
async def knowledge_save(config: Dict[str, Any]):
    logger.info(f"[Knowledge] ")
    return api_response(message="操作成功")
@router.post("/api/knowledgebase/list")
async def knowledge_list(config: Dict[str, Any], authorization: Optional[str] = Header(None)):
    """列出知识库（per-workspace 隔离：从 token 提取 workspace_id 过滤）。"""
    logger.info("[Knowledge] list")
    try:
        from services.quota_guard import extract_workspace_id
        from infrastructure.database.repositories.knowledge_repository import KnowledgeBaseRepository
        workspace_id = extract_workspace_id(authorization)
        kbs = KnowledgeBaseRepository().get_all(workspace_id=workspace_id)
        return api_response({"list": kbs, "total": len(kbs)})
    except Exception as e:
        logger.error(f"[Knowledge] list failed: {e}", exc_info=True)
        return api_response({"list": [], "total": 0}, message=f"查询失败: {e}")
@router.post("/api/knowledgebase/delete")
async def knowledge_delete(config: IdRequest):
    logger.info(f"[Knowledge] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/api/knowledgebase/detail")
async def knowledge_detail(config: IdRequest):
    logger.info(f"[Knowledge] : {config.pr_key_id}")
    return api_response({})
@router.post("/api/knowledgebase/getTableDetails")
async def knowledge_get_table_details(config: Dict[str, Any]):
    logger.info(f"[Knowledge] ")
    return api_response({})
@router.post("/api/knowledgebase/getOutputParams")
async def knowledge_get_output_params(config: Dict[str, Any]):
    logger.info(f"[Knowledge] ")
    return api_response({"params": []})
@router.post("/api/knowledgebase/sqlmodel/save")
async def knowledge_sqlmodel_save(config: Dict[str, Any]):
    logger.info(f"[Knowledge] SQL")
    return api_response(message="操作成功")
@router.post("/api/knowledgebase/sqlmodel/detail")
async def knowledge_sqlmodel_detail(config: IdRequest):
    logger.info(f"[Knowledge] SQL: {config.pr_key_id}")
    return api_response({})
@router.post("/api/knowledgebase/searchSqlResult")
async def knowledge_search_sql_result(config: Dict[str, Any]):
    logger.info(f"[Knowledge] SQL")
    return api_response({"data": [], "columns": []})
@router.post("/api/knowledgebase/getSqlModels")
async def knowledge_get_sql_models(config: Dict[str, Any]):
    logger.info(f"[Knowledge] SQL")
    return api_response({"list": []})
@router.post("/api/knowledgebase/documents/delete")
async def knowledge_documents_delete(config: IdRequest):
    logger.info(f"[Knowledge] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/api/knowledgebase/upload")
async def knowledge_upload(config: Dict[str, Any]):
    logger.info(f"[Knowledge] ")
    return api_response(message="操作成功")
@router.post("/api/knowledgebase/documents")
async def knowledge_documents(config: Dict[str, Any]):
    logger.info(f"[Knowledge] ")
    return api_response({"list": [], "total": 0})
@router.post("/system/resMgmt/page")
async def res_mgmt_page(config: PageQuery):
    logger.info(f"[ModelResource] : pageNo={config.page_no}")
    return api_response({
        "list": [],
        "total": 0,
        "pageNo": config.page_no,
        "pageSize": config.page_size
    })
@router.post("/system/resMgmt/create")
async def res_mgmt_create(config: Dict[str, Any]):
    logger.info(f"[ModelResource] ")
    return api_response(message="操作成功")
@router.post("/system/resMgmt/delete")
async def res_mgmt_delete(config: IdRequest):
    logger.info(f"[ModelResource] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/system/resMgmt/select")
async def res_mgmt_select(config: Dict[str, Any]):
    logger.info(f"[ModelResource] ")
    return api_response({"list": []})
@router.post("/system/resMgmt/testConnection")
async def res_mgmt_test_connection(config: Dict[str, Any]):
    logger.info(f"[ModelResource] ")
    return api_response(message="操作成功")
@router.post("/system/resMgmt/update")
async def res_mgmt_update(config: Dict[str, Any]):
    logger.info(f"[ModelResource] ")
    return api_response(message="操作成功")
@router.post("/system/menu/selectMenuList")
async def menu_select_list(config: Dict[str, Any]):
    logger.info(f"[Menu] ")
    return api_response({"list": [], "total": 0})
@router.post("/system/menu/selectMenuListByCondition")
async def menu_select_list_by_condition(config: Dict[str, Any]):
    logger.info(f"[Menu] ")
    return api_response({"list": [], "total": 0})
@router.post("/system/menu/addMenu")
async def menu_add(config: Dict[str, Any]):
    logger.info(f"[Menu] ")
    return api_response(message="操作成功")
@router.post("/system/menu/deleteMenu")
async def menu_delete(config: IdRequest):
    logger.info(f"[Menu] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/system/menu/editMenu")
async def menu_edit(config: Dict[str, Any]):
    logger.info(f"[Menu] ")
    return api_response(message="操作成功")
@router.post("/system/menu/selectMenuTree")
async def menu_select_tree(config: Dict[str, Any]):
    logger.info(f"[Menu] ")
    return api_response({"tree": []})
@router.post("/system/menu/detail")
async def menu_detail(config: IdRequest):
    logger.info(f"[Menu] : {config.pr_key_id}")
    return api_response({})
@router.post("/system/menu/authoGen")
async def menu_autho_gen(config: Dict[str, Any]):
    logger.info(f"[Menu] ")
    return api_response(message="操作成功")
@router.post("/system/role/select")
async def role_select(config: PageQuery):
    logger.info(f"[Role] : pageNo={config.page_no}")
    return api_response({
        "list": [],
        "total": 0,
        "pageNo": config.page_no,
        "pageSize": config.page_size
    })
@router.post("/system/role/addRole")
async def role_add(config: Dict[str, Any]):
    logger.info(f"[Role] ")
    return api_response(message="操作成功")
@router.post("/system/role/editRole")
async def role_edit(config: Dict[str, Any]):
    logger.info(f"[Role] ")
    return api_response(message="操作成功")
@router.post("/system/role/removeRole")
async def role_remove(config: IdRequest):
    logger.info(f"[Role] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/system/role/export")
async def role_export(config: Dict[str, Any]):
    logger.info(f"[Role] ")
    return api_response({"list": []})
@router.post("/system/role/addRoleUser")
async def role_add_user(config: Dict[str, Any]):
    logger.info(f"[Role] ")
    return api_response(message="操作成功")
@router.post("/system/role/removeRoleUser")
async def role_remove_user(config: Dict[str, Any]):
    logger.info(f"[Role] ")
    return api_response(message="操作成功")
@router.post("/system/role/roleResConfig")
async def role_res_config(config: Dict[str, Any]):
    logger.info(f"[Role] ")
    return api_response(message="操作成功")
@router.post("/system/role/selectRoleResConfig")
async def select_role_res_config(config: Dict[str, Any]):
    logger.info(f"[Role] ")
    return api_response({"config": {}, "list": []})
@router.post("/modes/page")
async def modes_page(config: PageQuery):
    logger.info(f"[Mode] : pageNo={config.page_no}")
    return api_response({
        "list": [],
        "total": 0,
        "pageNo": config.page_no,
        "pageSize": config.page_size
    })
@router.post("/modes/create")
async def modes_create(config: Dict[str, Any]):
    logger.info(f"[Mode] ")
    return api_response(message="操作成功")
@router.post("/modes/update")
async def modes_update(config: Dict[str, Any]):
    logger.info(f"[Mode] ")
    return api_response(message="操作成功")
@router.post("/modes/get")
async def modes_get(config: IdRequest):
    logger.info(f"[Mode] : {config.pr_key_id}")
    return api_response({})
@router.post("/modes/delete")
async def modes_delete(config: IdRequest):
    logger.info(f"[Mode] : {config.pr_key_id}")
    return api_response(message="操作成功")
@router.post("/modes/agents")
async def modes_agents(config: Dict[str, Any]):
    logger.info(f"[Mode] Agent")
    return api_response({"list": []})
@router.post("/modes/agent/status")
async def modes_agent_status(config: Dict[str, Any]):
    logger.info(f"[Mode] Agent")
    return api_response(message="操作成功")