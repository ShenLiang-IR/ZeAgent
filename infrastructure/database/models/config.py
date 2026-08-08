from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, TIMESTAMP as SqlTIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from ..base import Base
from .mcp import Mcp as _McpBase
from .mode import Mode as _ModeBase
class SystemConfig(Base):
    __tablename__ = "tb_system_config"
    id: Mapped[Optional[int]] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text)
    create_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        {'comment': ''},
    )
class MCPConfigCompat(_McpBase):
    @property
    def id(self):
        return self.pr_key_id
    @property
    def name(self):
        return self.mcp_name
    @property
    def display_name(self):
        return self.mcp_name
    @property
    def config_json(self):
        from utils.common.json_utils import parse_json_field
        if self.params:
            try:
                return parse_json_field(self.params)
            except Exception:
                return {}
        return {}
    @property
    def enabled(self):
        return self.status == '0'
class AgentModeConfigCompat(_ModeBase):
    pass
class McpToolSetCompat:
    pass
class HttpConfigCompat:
    pass
class ExternalToolConfigCompat:
    pass
class ExternalToolParameterCompat:
    pass
class SubAgentConfigCompat:
    pass
class SystemConfigCompat:
    pass
MCPConfig = MCPConfigCompat
MCPToolSet = McpToolSetCompat
AgentModeConfig = AgentModeConfigCompat
HttpConfig = HttpConfigCompat
ExternalToolConfig = ExternalToolConfigCompat
ExternalToolParameter = ExternalToolParameterCompat
SubAgentConfig = SubAgentConfigCompat