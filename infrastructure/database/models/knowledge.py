
from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .timestamp_mixins import TimestampMixin


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "tb_knowledge_base"
    pr_key_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(32))
    knowledge_name: Mapped[str] = mapped_column(String(100))
    knowledge_type: Mapped[str] = mapped_column(String(1))
    description: Mapped[str | None] = mapped_column(String(500))
    business_type: Mapped[str | None] = mapped_column(String(50))
    visible_scope: Mapped[str] = mapped_column(String(50))
    document_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    chunk_size: Mapped[int | None] = mapped_column(Integer, default=1000)
    overlap_size: Mapped[int | None] = mapped_column(Integer, default=200)
    public_access: Mapped[str] = mapped_column(String(1), default='0')
    hit_count: Mapped[int | None] = mapped_column(Integer, default=0)
    tags: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(1), default='1')
    segment_strategy: Mapped[str | None] = mapped_column(String(50))
    del_flag: Mapped[str | None] = mapped_column(String(1))
    level_count: Mapped[str | None] = mapped_column(String(1))
    level_switch: Mapped[str | None] = mapped_column(String(1))
    database_type: Mapped[str | None] = mapped_column(String(20))
    database_table: Mapped[str | None] = mapped_column(String(1000))
    label_extraction_rule: Mapped[str | None] = mapped_column(Text)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="所属工作空间（per-workspace 隔离）")
    __table_args__ = (
        {'comment': ''},
        )
    TYPE_UNSTRUCTURED = '0'
    TYPE_STRUCTURED = '1'
    SEGMENT_CUSTOM = '0'
    SEGMENT_HIERARCHICAL = '1'
class KnowledgeBaseDocument(Base, TimestampMixin):
    __tablename__ = "tb_knowledge_base_document"
    pr_key_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(32))
    knowledge_base_id: Mapped[str] = mapped_column(String(32))
    document_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    document_type: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(String(500))
    bucket_name: Mapped[str | None] = mapped_column(String(32), default='invres-smart-agent')
    file_size: Mapped[int | None] = mapped_column()
    file_hash: Mapped[str | None] = mapped_column(String(100))
    recognition_rules: Mapped[str | None] = mapped_column(String(50), default='custom')
    segment_strategy: Mapped[str | None] = mapped_column(String(50), default='smart')
    status: Mapped[str | None] = mapped_column(String(20), default='pending')
    total_chunks: Mapped[int | None] = mapped_column(Integer, default=0)
    processed_chunks: Mapped[int | None] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500))
    del_flag: Mapped[str | None] = mapped_column(String(1))
    __table_args__ = (
        {'comment': ''},
    )
class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "tb_document_chunk"
    pr_key_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(32))
    file_id: Mapped[str] = mapped_column(String(32))
    chunk_index: Mapped[int] = mapped_column()
    chunk_content: Mapped[str] = mapped_column(Text)
    embedding_vector: Mapped[bytes | None] = mapped_column()
    del_flag: Mapped[str | None] = mapped_column(String(1))
    __table_args__ = (
        {'comment': ''},
    )
class KnowledgeBaseSqlModel(Base, TimestampMixin):
    __tablename__ = "tb_knowledge_base_sql_model"
    pr_key_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sql_model_id: Mapped[str] = mapped_column(String(32))
    knowledge_base_id: Mapped[str] = mapped_column(String(32))
    sql_model_name: Mapped[str] = mapped_column(String(50))
    sql_model_description: Mapped[str | None] = mapped_column(String(500))
    sql_execution_config: Mapped[str | None] = mapped_column(Text)
    del_flag: Mapped[str | None] = mapped_column(String(1))
    __table_args__ = (
        {'comment': 'SQL'},
    )
class KnowledgeBaseTableField(Base, TimestampMixin):
    __tablename__ = "tb_knowledge_base_table_field"
    pr_key_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(32))
    table_name: Mapped[str] = mapped_column(String(255))
    field_name: Mapped[str] = mapped_column(String(255))
    field_type: Mapped[str | None] = mapped_column(String(100))
    field_desc: Mapped[str | None] = mapped_column(String(5000))
    enable_flag: Mapped[str | None] = mapped_column(String(1))
    del_flag: Mapped[str | None] = mapped_column(String(1))
    __table_args__ = (
        {'comment': ''},
    )
