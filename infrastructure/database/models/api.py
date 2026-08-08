from typing import Optional
from sqlalchemy import String, Text, Integer, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
from .timestamp_mixins import TellerAuditMixin
class RkApiNode(Base, TellerAuditMixin):
    __tablename__ = "tb_rk_api_node"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_name: Mapped[Optional[str]] = mapped_column(String(15))
    agent_node_no: Mapped[Optional[str]] = mapped_column(String(32))
    intfc_path: Mapped[Optional[str]] = mapped_column(String(500))
    node_desc: Mapped[Optional[str]] = mapped_column(Text)
    server_run_envnm_cd: Mapped[Optional[str]] = mapped_column(String(1))
    node_status: Mapped[Optional[str]] = mapped_column(String(1))
    belong_area_name: Mapped[Optional[str]] = mapped_column(String(100))
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    __table_args__ = (
        {'comment': 'API'},
    )
class RkApi(Base, TellerAuditMixin):
    __tablename__ = "tb_rk_api"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    intfc_name: Mapped[Optional[str]] = mapped_column(String(500))
    intfc_path: Mapped[Optional[str]] = mapped_column(String(500))
    http_requer_mth_cd: Mapped[Optional[str]] = mapped_column(String(100))
    intfc_invoke_mode_cd: Mapped[Optional[str]] = mapped_column(String(100))
    node_id: Mapped[Optional[str]] = mapped_column(String(32))
    intfc_sta_cd: Mapped[Optional[str]] = mapped_column(String(1))
    vsbl_scope_flag: Mapped[Optional[str]] = mapped_column(String(1))
    intfc_desc: Mapped[Optional[str]] = mapped_column(Text)
    tmout_time_num: Mapped[Optional[int]] = mapped_column(Integer)
    retry_times: Mapped[Optional[int]] = mapped_column(Integer)
    extend_info: Mapped[Optional[str]] = mapped_column(Text)
    req_msg: Mapped[Optional[str]] = mapped_column(Text)
    resp_msg: Mapped[Optional[str]] = mapped_column(Text)
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="所属工作空间")
    is_public: Mapped[Optional[int]] = mapped_column(Integer, default=0, comment="0=私有 1=公开（旧字段，由 visibility 同步）")
    visibility: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True, comment="可见性 private/workspace/public（新 source of truth，NULL=待迁移）")
    creator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="创建者用户ID")
    __table_args__ = (
        {'comment': 'API'},
    )
class RkApiParam(Base, TellerAuditMixin):
    __tablename__ = "tb_rk_api_param"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    intfc_name: Mapped[Optional[str]] = mapped_column(String(500))
    intfc_path: Mapped[Optional[str]] = mapped_column(String(500))
    req_flag_code: Mapped[Optional[str]] = mapped_column(String(1))
    para_name: Mapped[Optional[str]] = mapped_column(String(100), primary_key=True)
    para_type_name: Mapped[Optional[str]] = mapped_column(String(32))
    para_desc: Mapped[Optional[str]] = mapped_column(Text)
    para_value: Mapped[Optional[str]] = mapped_column(Text)
    param_sta: Mapped[Optional[str]] = mapped_column(String(1))
    req_msg: Mapped[Optional[str]] = mapped_column(Text)
    resp_msg: Mapped[Optional[str]] = mapped_column(Text)
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    __table_args__ = (
        {'comment': 'API'},
    )