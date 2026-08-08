"""端到端评测模型：tb_eval_dataset（golden set）+ tb_eval_result（评测结果）+ tb_feedback（用户反馈）。

设计参见 当前文档分析.md §3.7：Agent 端到端评测体系。
- eval_dataset：golden set（用户问题 + 期望输出 + 评分标准）
- eval_result：单次 LLM-as-Judge 评分结果（关联 dispatch_id）
- feedback：用户 thumbs up/down + 文本反馈（关联 dispatch_id）

与 rag/ragas_eval.py 的 RAG 检索评测不同，本模块评测 Agent 回复质量。
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class EvalDataset(Base):
    """评测数据集（golden set）：问题 + 期望输出 + 评分标准。"""
    __tablename__ = "tb_eval_dataset"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，EVAL_DS_ 前缀")
    name: Mapped[str | None] = mapped_column(String(128), comment="数据集名称")
    question: Mapped[str | None] = mapped_column(Text, comment="用户问题")
    expected_output: Mapped[str | None] = mapped_column(Text, comment="期望输出（标准答案）")
    scoring_criteria: Mapped[str | None] = mapped_column(Text, comment="评分标准（如：准确性/完整性/简洁性，各占多少分）")
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="标签，逗号分隔（如：math,general）")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="workspace 隔离")
    enabled: Mapped[str | None] = mapped_column(String(1), default="1", comment="1启用 0禁用")
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': '评测数据集（golden set）'},
    )


class EvalResult(Base):
    """单次 LLM-as-Judge 评测结果。"""
    __tablename__ = "tb_eval_result"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    result_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，EVAL_ 前缀")
    dispatch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联 tb_dispatch_record")
    dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联 tb_eval_dataset")
    question: Mapped[str | None] = mapped_column(Text, comment="评测的问题（冗余便于查询）")
    response: Mapped[str | None] = mapped_column(Text, comment="Agent 回复（被评测的）")
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True, comment="期望输出（冗余）")
    score: Mapped[int | None] = mapped_column(Integer, comment="评分 0-100")
    judge_feedback: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Judge 评语（扣分原因）")
    judge_model: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="评分用的 LLM 模型")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        {'comment': 'LLM-as-Judge 评测结果'},
    )


class Feedback(Base):
    """用户反馈（thumbs up/down + 文本）。"""
    __tablename__ = "tb_feedback"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    feedback_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，FB_ 前缀")
    dispatch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联 dispatch")
    thumbs_up: Mapped[bool | None] = mapped_column(Boolean, comment="True=赞 False=踩")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="文本反馈")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="用户ID（匿名时为 anonymous）")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        {'comment': '用户反馈'},
    )
