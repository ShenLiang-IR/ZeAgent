"""Prompt 模板模型：tb_prompt_template。

设计参见 当前文档分析.md §3.8：Prompt 治理。

- 可复用 prompt 片段，content 含 {{var}} 变量占位
- render 时用 variables dict 插值
- 版本管理（version 字段）+ workspace 隔离
- MVP 不含 A/B 测试/评测/沙箱（后续）
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class PromptTemplate(Base):
    """Prompt 模板（可复用片段，含 {{var}} 变量）。"""
    __tablename__ = "tb_prompt_template"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，PT_ 前缀")
    name: Mapped[str | None] = mapped_column(String(128), unique=True, comment="模板名称（唯一，便于引用）")
    content: Mapped[str | None] = mapped_column(Text, comment="模板内容，含 {{var}} 变量占位")
    variables: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变量名 JSON 数组，如 [\"name\",\"topic\"]")
    version: Mapped[str | None] = mapped_column(String(20), default="1.0.0", comment="版本号")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="模板说明")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="workspace 隔离")
    enabled: Mapped[str | None] = mapped_column(String(1), default="1", comment="1启用 0禁用")
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': 'Prompt 模板'},
    )
