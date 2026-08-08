"""Agent 版本快照模型：tb_agent_version。

设计参见 当前文档分析.md §3.6：Agent 版本与发布流程。

- 每次保存生成快照（draft → published → archived）
- publish 时同 agent 旧 published 版本自动 archived
- rollback 恢复 agent 配置到指定版本快照
- snapshot 字段存 agent 可变配置 JSON（system_prompt/model_id/temperature 等）

与 tb_agent.release_status/version_no 互补：
  tb_agent 存当前生效配置 + 当前版本号
  tb_agent_version 存历史版本快照（可回滚）
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class AgentVersion(Base):
    """Agent 版本快照。"""
    __tablename__ = "tb_agent_version"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，AGV_ 前缀")
    agent_pr_key_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联 tb_agent.pr_key_id")
    version_no: Mapped[str | None] = mapped_column(String(20), comment="版本号，如 1.0.0")
    version_description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="版本说明")
    snapshot: Mapped[str | None] = mapped_column(Text, comment="agent 可变配置 JSON：system_prompt/model_id/temperature 等")
    status: Mapped[str | None] = mapped_column(String(20), default="draft", comment="draft/published/archived")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="workspace 隔离")
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': 'Agent 版本快照'},
    )
