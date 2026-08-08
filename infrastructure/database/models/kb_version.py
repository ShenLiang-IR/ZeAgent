"""知识库版本快照模型：tb_kb_version。

设计参见 当前文档分析.md §3.10：知识库版本控制。

- 版本快照保存 KnowledgeBase 可变配置（knowledge_name/type/embedding_model/chunk_size 等）
- publish/rollback 与 agent_version 模式一致（draft→published→archived）
- 与 per-workspace 隔离互补：workspace_id 字段隔离 + version 快照回滚
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class KnowledgeBaseVersion(Base):
    """知识库版本快照。"""
    __tablename__ = "tb_kb_version"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，KBV_ 前缀")
    knowledge_base_id: Mapped[str | None] = mapped_column(String(32), comment="关联 tb_knowledge_base.knowledge_base_id")
    version_no: Mapped[str | None] = mapped_column(String(20), comment="版本号")
    version_description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="版本说明")
    snapshot: Mapped[str | None] = mapped_column(Text, comment="知识库可变配置 JSON")
    status: Mapped[str | None] = mapped_column(String(20), default="draft", comment="draft/published/archived")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="workspace 隔离")
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': '知识库版本快照'},
    )
