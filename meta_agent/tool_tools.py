"""Meta-Agent 外部工具（API 接口）管理工具。

直接调用 ApiRepository（不经过 HTTP），返回 LLM 可读的字符串。
"""
import ipaddress
from urllib.parse import urlparse
from langchain_core.tools import tool


# SSRF 防护：拒绝内网/环回/链路本地/元数据端点
_LOOPBACK_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata"}


def _is_safe_url(url: str) -> bool:
    """校验 URL 不指向内网/环回/链路本地/元数据端点（防 SSRF）。

    基础校验：拒绝私有/环回/链路本地/保留 IP + 元数据主机名。
    DNS rebinding（域名解析到内网 IP）需解析后校验，作为后续迭代。
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        if hostname in _LOOPBACK_HOSTNAMES:
            return False
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            # 域名：基础校验通过（DNS rebinding 需更深防护，作为后续）
            return True
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
        return True
    except Exception:
        return False


@tool
async def create_external_tool(
    name: str,
    api_base_url: str = "",
    api_endpoint: str = "",
    method: str = "POST",
    description: str = "",
    parameter_list: str = "",
    enabled: bool = True,
) -> str:
    """创建一个外部工具（API 接口配置）。当用户想添加一个 HTTP API 作为工具时使用。

    Args:
        name: 工具名称（如 "search_indicators"）
        api_base_url: API 基础地址（如 "http://localhost:8001"）
        api_endpoint: API 端点路径（如 "/api/indicators/search"）
        method: HTTP 方法（"POST" 或 "GET"）
        description: 工具描述
        enabled: 是否启用

    Returns:
        创建结果
    """
    from utils.config import get_config_db

    config_db = get_config_db()
    try:
        if api_base_url and not _is_safe_url(api_base_url):
            return f"拒绝创建外部工具：api_base_url '{api_base_url}' 指向内网/环回/元数据端点（SSRF 防护）"
        extend = {}
        if api_base_url:
            extend["api_base_url"] = api_base_url
        if parameter_list:
            extend["parameter_list"] = parameter_list
        ok = config_db.external_tools.save_api(
            pr_key_id="0",
            intfc_name=name,
            intfc_path=api_endpoint,
            http_requer_mth_cd=method,
            intfc_desc=description,
            extend_info=extend if extend else None,
            enabled=enabled,
        )
        if ok:
            return f"外部工具 '{name}' 创建成功。"
        return f"外部工具 '{name}' 创建失败"
    except Exception as e:
        return f"创建外部工具失败: {e}"


@tool
async def list_external_tools() -> str:
    """列出所有外部工具。"""
    from utils.config import get_config_db

    config_db = get_config_db()
    tools = config_db.external_tools.get_all(return_format="external_tool") or []
    lines = []
    for t in tools:
        name = t.get("name") or t.get("intfc_name", "")
        status = "启用" if t.get("enabled") else "禁用"
        pk = t.get("pr_key_id") or t.get("id", "")
        lines.append(f"- {name} (pr_key_id={pk}, {status})")
    return f"共 {len(tools)} 个外部工具:\n" + "\n".join(lines)


@tool
async def delete_external_tool(pr_key_id: str) -> str:
    """删除一个外部工具。

    Args:
        pr_key_id: 外部工具的 pr_key_id

    Returns:
        删除结果
    """
    from utils.config import get_config_db

    config_db = get_config_db()
    try:
        ok = config_db.external_tools.delete_api(int(pr_key_id))
        if ok:
            return f"外部工具 (pr_key_id={pr_key_id}) 删除成功。"
        return f"外部工具 (pr_key_id={pr_key_id}) 不存在或删除失败。"
    except Exception as e:
        return f"删除失败: {e}"
