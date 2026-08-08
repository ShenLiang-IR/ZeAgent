"""MCP 服务层：封装 tb_mcp / tb_mcp_intfc 的业务逻辑。

提供 CRUD + 测试连接 + 接口同步，供 api/admin/mcp.py 调用。
"""
import json
from typing import Dict, List, Any, Optional
from loguru import logger
from infrastructure.database.repositories.mcp_repository import (
    McpRepository,
    McpIntfcRepository,
)
from utils.id_generator import generate_mcp_id
from utils.mcp_util import fetch_mcp_tools_from_url


class McpService:
    """MCP 服务配置 + 接口同步的业务服务。"""

    def __init__(self):
        self.mcp_repo = McpRepository()
        self.intfc_repo = McpIntfcRepository()

    # ─────────────────────── 基础 CRUD ───────────────────────

    def register(
        self,
        mcp_name: str,
        description: str = "",
        category: str = "",
        connection_type: str = "stdio",
        connection_url: str = "",
        exec_cmd: str = "",
        auth_info: str = "",
        timeout: int = 30000,
        params: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        workspace_id: int = None,
        creator_id: int = None,
        visibility: str = None,
    ) -> Dict[str, Any]:
        """创建一个 MCP 服务配置。"""
        from utils.common.visibility import normalize_visibility, visibility_to_is_public
        if not mcp_name:
            raise ValueError("mcp_name 不能为空")
        if self.mcp_repo.get_by_name(mcp_name):
            raise ValueError(f"MCP 名称已存在: {mcp_name}")
        mcp_id = generate_mcp_id(mcp_name)
        entity = self.mcp_repo.create(
            mcp_id=mcp_id,
            mcp_name=mcp_name,
            description=description,
            category=category,
            exec_cmd=exec_cmd,
            connection_type=connection_type,
            connection_url=connection_url,
            auth_info=auth_info,
            timeout=timeout,
            params=json.dumps(params, ensure_ascii=False) if params else None,
            status="1" if enabled else "0",
            del_flag="0",
            workspace_id=workspace_id,
            creator_id=creator_id,
            visibility=normalize_visibility(visibility) if visibility else None,
            is_public=visibility_to_is_public(visibility) if visibility else 0,
        )
        if not entity:
            raise RuntimeError("保存 MCP 失败")
        result = self.mcp_repo.get_by_id(entity.pr_key_id)
        if not result:
            raise RuntimeError("保存后查询失败")
        logger.info(f"[McpService] register: {mcp_name} -> pr_key_id={entity.pr_key_id}")
        return result

    def page(
        self,
        page_no: int = 1,
        page_size: int = 10,
        mcp_name: str = None,
        status: str = None,
        workspace_id: int = None,
        viewer_user_id: int = None,
        viewer_workspace_id: int = None,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """分页查询 MCP 列表。

        非 admin 走三层可见性过滤（public + 同空间 workspace + 自己的 private）；
        admin 全可见（可选 workspace_id 聚合）。
        """
        items = self.mcp_repo.get_all(
            workspace_id=workspace_id,
            viewer_user_id=viewer_user_id,
            viewer_workspace_id=viewer_workspace_id,
            is_admin=is_admin,
        ) or []
        if mcp_name:
            kw = mcp_name.lower()
            items = [it for it in items if kw in (it.get("mcp_name") or "").lower()]
        if status is not None:
            items = [it for it in items if it.get("status") == status]
        total = len(items)
        start = (page_no - 1) * page_size
        end = start + page_size
        return {
            "list": items[start:end],
            "total": total,
            "pageNo": page_no,
            "pageSize": page_size,
        }

    def detail(self, pr_key_id) -> Optional[Dict[str, Any]]:
        """MCP 详情（含接口列表）。"""
        mcp = self.mcp_repo.get_by_id(pr_key_id)
        if not mcp:
            return None
        interfaces = self.intfc_repo.get_by_mcp_id(mcp.get("mcp_id", ""))
        return {"mcp": mcp, "interfaces": interfaces}

    def update(self, pr_key_id, **kwargs) -> bool:
        """更新 MCP 配置（部分字段）。"""
        existing = self.mcp_repo.get_by_id(pr_key_id)
        if not existing:
            return False
        update_data: Dict[str, Any] = {}
        for k, v in kwargs.items():
            if v is None:
                continue
            if k == "enabled":
                update_data["status"] = "1" if v else "0"
            elif k == "params" and isinstance(v, dict):
                update_data["params"] = json.dumps(v, ensure_ascii=False)
            elif k == "visibility":
                # 三层可见性：visibility 为 source of truth，同步 is_public
                from utils.common.visibility import normalize_visibility, visibility_to_is_public
                update_data["visibility"] = normalize_visibility(v)
                update_data["is_public"] = visibility_to_is_public(normalize_visibility(v))
            elif k == "mcp_name":
                # 改名需同步 mcp_id 与接口外键
                new_name = v
                if new_name != existing.get("mcp_name"):
                    update_data["mcp_name"] = new_name
                    update_data["mcp_id"] = generate_mcp_id(new_name)
                else:
                    update_data["mcp_name"] = new_name
            elif hasattr(self.mcp_repo._model_class, k):
                update_data[k] = v
        if not update_data:
            return True
        result = self.mcp_repo.update(pr_key_id, **update_data)
        ok = result is not None
        if ok and "mcp_id" in update_data:
            # 改名后把接口的 mcp_id 外键一并迁移
            old_mcp_id = existing.get("mcp_id")
            new_mcp_id = update_data["mcp_id"]
            if old_mcp_id and new_mcp_id and old_mcp_id != new_mcp_id:
                self._migrate_interfaces(old_mcp_id, new_mcp_id)
        logger.info(f"[McpService] update pr_key_id={pr_key_id} ok={ok}")
        return ok

    def update_status(self, pr_key_id, status: str) -> bool:
        """启用/禁用。status: '1' 启用 / '0' 禁用。"""
        result = self.mcp_repo.update(pr_key_id, status=status)
        return result is not None

    def delete(self, pr_key_id) -> bool:
        """软删除 MCP 及其接口（避免同名重建时旧接口复活）。"""
        existing = self.mcp_repo.get_by_id(pr_key_id)
        if not existing:
            return False
        mcp_id = existing.get("mcp_id", "")
        if mcp_id:
            for it in self.intfc_repo.get_by_mcp_id(mcp_id):
                self.intfc_repo.update(it["pr_key_id"], del_flag="1")
        ok = self.mcp_repo.delete(pr_key_id)
        logger.info(f"[McpService] delete pr_key_id={pr_key_id} mcp_id={mcp_id} ok={ok}")
        return ok

    # ─────────────────── 连接测试 + 接口同步 ───────────────────

    async def test_connect(
        self,
        connection_type: str,
        exec_cmd: str = "",
        connection_url: str = "",
        params: Optional[Dict[str, Any]] = None,
        auth_info: str = "",
        timeout: int = 30000,
    ) -> List[Dict[str, Any]]:
        """连接 MCP 服务并拉取工具列表（不写库）。"""
        params = params or {}
        if connection_type == "stdio":
            command = exec_cmd
            args = params.get("args", [])
            env = params.get("env")
            if not command:
                raise ValueError("stdio 连接需要 exec_cmd")
            tools = await self._fetch_tools_stdio(command, args, env)
        elif connection_type in ("sse", "http", "streamable_http"):
            headers = params.get("headers", {})
            if auth_info:
                headers.setdefault("Authorization", auth_info)
            url_params = params.get("url_params", {})
            if not connection_url:
                raise ValueError("sse 连接需要 connection_url")
            tools = await fetch_mcp_tools_from_url(connection_url, headers, url_params)
        else:
            raise ValueError(f"不支持的连接类型: {connection_type}")
        logger.info(f"[McpService] test_connect({connection_type}) -> {len(tools)} tools")
        return tools

    async def _fetch_tools_stdio(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """用 mcp SDK 客户端连接 stdio MCP server（含 initialize 握手）。"""
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp.client.session import ClientSession

        server_params = StdioServerParameters(
            command=command,
            args=list(args or []),
            env=env if env else None,
        )
        tools: List[Dict[str, Any]] = []
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                for tool in result.tools:
                    schema = getattr(tool, "inputSchema", None)
                    if hasattr(schema, "model_dump"):
                        schema = schema.model_dump()
                    if not isinstance(schema, dict):
                        schema = {}
                    tools.append({
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": schema,
                    })
        return tools

    async def sync_interfaces(self, pr_key_id) -> Dict[str, Any]:
        """从 MCP 服务拉取工具，upsert 到 tb_mcp_intfc。"""
        mcp = self.mcp_repo.get_by_id(pr_key_id)
        if not mcp:
            raise ValueError("MCP 不存在")
        mcp_id = mcp["mcp_id"]
        if not mcp_id:
            raise ValueError("MCP 缺少 mcp_id")
        tools = await self.test_connect(
            connection_type=mcp["connection_type"],
            exec_cmd=mcp["exec_cmd"],
            connection_url=mcp["connection_url"],
            params=mcp["params"],
            auth_info=mcp["auth_info"],
            timeout=mcp["timeout"],
        )
        existing = {i["intfc_name"]: i for i in self.intfc_repo.get_by_mcp_id(mcp_id)}
        synced = 0
        for tool in tools:
            name = tool.get("name")
            if not name:
                continue
            description = tool.get("description", "")
            input_schema = tool.get("inputSchema", {})
            if name in existing:
                # 已有接口：保留 pr_key_id 和用户手动设置的启用状态（不覆盖禁用）
                pr_key = existing[name]["pr_key_id"]
                enabled = existing[name].get("enabled", True)
            else:
                # 新接口：pr_key_id 留空让 DB autoincrement（避免 UUID 字符串查 BigInteger）
                pr_key = None
                enabled = True
            self.intfc_repo.save_interface(
                pr_key_id=pr_key,
                intfc_name=name,
                mcp_id=mcp_id,
                description=description,
                input_param_ex=input_schema,
                output_param_ex={},
                intfc_usage="1",
                enabled=enabled,
            )
            synced += 1
        logger.info(f"[McpService] sync_interfaces mcp_id={mcp_id} synced={synced}")
        return {"synced": synced, "total_tools": len(tools)}

    # ─────────────────────── 内部辅助 ───────────────────────

    def _migrate_interfaces(self, old_mcp_id: str, new_mcp_id: str) -> None:
        """改名时把接口的外键 mcp_id 迁移到新值。"""
        try:
            interfaces = self.intfc_repo.get_by_mcp_id(old_mcp_id)
            for it in interfaces:
                self.intfc_repo.update(it["pr_key_id"], mcp_id=new_mcp_id)
        except Exception as e:
            logger.warning(f"[McpService] migrate interfaces {old_mcp_id}->{new_mcp_id}: {e}")
