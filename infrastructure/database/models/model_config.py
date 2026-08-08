"""模型配置表（LLM/Embedding/Rerank 模型统一管理）。

存储模型基本信息：名称、provider、类型、显示名、API Key、endpoint。
兼容 OpenAI 和 Ollama。建在 MySQL agent_config 库。
"""
from typing import Optional
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base, StampTimestampMixin


class ModelConfig(Base, StampTimestampMixin):
    """模型配置表。"""
    __tablename__ = "tb_model_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="主键ID")
    model_name: Mapped[str] = mapped_column(String(100), comment="模型名称")
    provider: Mapped[str] = mapped_column(String(50), comment="provider: openai/ollama/huggingface/local")
    model_type: Mapped[str] = mapped_column(String(20), comment="类型: LLM/Embedding/Rerank")
    display_name: Mapped[Optional[str]] = mapped_column(String(100), comment="显示名称")
    api_key: Mapped[Optional[str]] = mapped_column(String(200), comment="API Key")
    api_endpoint_url: Mapped[Optional[str]] = mapped_column(String(500), comment="API endpoint URL")
    status: Mapped[str] = mapped_column(String(1), default='1', comment="状态 1=启用 0=禁用")
    del_flag: Mapped[Optional[str]] = mapped_column(String(1), default='0', comment="删除标记")
    fallback_model_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, comment="备用模型ID（配额 degrade 时切该模型，per-model fallback 链；MVP 用 config quota.fallback_model_id 全局配置）")
