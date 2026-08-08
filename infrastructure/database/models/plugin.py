"""插件市场模型。

P0 统一插件市场：
- Plugin（tb_plugin）：插件市场主表，统一包装 mcp_server / skill / tool 三类能力为"插件"，
  含市场化元数据（图标/分类/标签/作者/版本/评分/下载量/权限声明）。
- PluginInstall（tb_plugin_install）：按 workspace/user 的安装关系，
  linked_resource_id 统一记录安装时生成的运行时资源 ID（MCP 的 mcp_id / Skill 的 skill_id / Tool 的 tool_name），
  保留 linked_mcp_id 向后兼容（= linked_resource_id when plugin_type=mcp_server）。
"""
from typing import Optional
from sqlalchemy import String, Text, BigInteger, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base, TimestampMixin


class Plugin(Base, TimestampMixin):
    """插件市场主表。"""
    __tablename__ = "tb_plugin"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True, comment="插件业务ID，如 PLG_XXX")
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="插件技术名（唯一）")
    display_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="插件显示名称")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="插件描述")
    icon: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="图标名或 URL")
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True, comment="分类")
    tags: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="标签，逗号分隔")
    author: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="作者")
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="1.0.0", comment="版本号")
    plugin_type: Mapped[str] = mapped_column(String(20), nullable=False, default="mcp_server", comment="插件类型: mcp_server/skill_python/skill_nodejs/skill_go/tool")
    mcp_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="MCP 连接配置 JSON（复用 tb_mcp 协议）")
    manifest: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="权限声明 + 参数 schema + skill 配置 JSON")
    status: Mapped[str] = mapped_column(String(1), nullable=False, default="1", comment="1=上架 0=下架 2=审核中")
    del_flag: Mapped[str] = mapped_column(String(1), nullable=False, default="0", comment="0=正常 1=删除")
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="安装/下载量")
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="评分 0-5")
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="发布者工作空间，NULL=官方全局")

    __table_args__ = ({'comment': '插件市场主表'},)


class PluginInstall(Base, TimestampMixin):
    """插件安装关系表（按 workspace/user）。"""
    __tablename__ = "tb_plugin_install"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    install_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True, comment="安装业务ID")
    plugin_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="插件业务ID")
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="安装时的版本")
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="安装到的工作空间")
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="安装者用户ID")
    config: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="用户自定义配置 JSON")
    linked_mcp_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="兼容旧字段：安装 mcp_server 时生成的 tb_mcp.mcp_id")
    linked_resource_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="统一资源ID：mcp_id / skill_id / tool_name")
    enabled: Mapped[str] = mapped_column(String(1), nullable=False, default="1", comment="1=启用 0=停用")
    del_flag: Mapped[str] = mapped_column(String(1), nullable=False, default="0", comment="0=正常 1=删除")

    __table_args__ = ({'comment': '插件安装关系表'},)
