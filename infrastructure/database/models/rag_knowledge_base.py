"""RAG 知识库表模型（非结构化文档 RAG 用，独立于结构化 tb_knowledge_base）。

存储知识库基本信息：kb_id、名称、描述、存储路径、embedding 配置等。
建在 MySQL agent_config 库（get_config_session）。
"""
from typing import Optional
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base, StampTimestampMixin


class RagKnowledgeBase(Base, StampTimestampMixin):
    """RAG 知识库基本信息表。"""
    __tablename__ = "tb_rag_knowledge_base"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="主键ID")
    kb_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="知识库ID")
    name: Mapped[str] = mapped_column(String(100), comment="知识库名称")
    description: Mapped[Optional[str]] = mapped_column(String(500), comment="描述")
    persist_directory: Mapped[Optional[str]] = mapped_column(String(500), comment="向量存储路径")
    embedding_provider: Mapped[Optional[str]] = mapped_column(String(50), comment="embedding提供者: local/openai/ollama/huggingface")
    embedding_model: Mapped[Optional[str]] = mapped_column(String(100), comment="embedding模型")
    embedding_base_url: Mapped[Optional[str]] = mapped_column(String(500), comment="embedding API URL")
    chunk_size: Mapped[Optional[int]] = mapped_column(Integer, default=500, comment="分块大小")
    chunk_overlap: Mapped[Optional[int]] = mapped_column(Integer, default=100, comment="分块重叠")
    status: Mapped[str] = mapped_column(String(1), default='1', comment="状态 1=启用 0=禁用")
    del_flag: Mapped[Optional[str]] = mapped_column(String(1), default='0', comment="删除标记 0=正常 1=删除")
