from typing import Optional
from sqlalchemy import String, Text, Numeric, Integer
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
from .timestamp_mixins import TimestampMixin
class SysModelResMgmt(Base, TimestampMixin):
    __tablename__ = "tb_sys_model_res_mgmt"
    pr_key_id: Mapped[str] = mapped_column(String(32), primary_key=True, comment='ID')
    risk_model_name: Mapped[Optional[str]] = mapped_column(String(300), comment='')
    model_id: Mapped[Optional[str]] = mapped_column(String(128), comment='')
    model_tp_cls: Mapped[Optional[str]] = mapped_column(String(128), comment='')
    model_desc: Mapped[Optional[str]] = mapped_column(String(500), comment='')
    spec_model_label: Mapped[Optional[str]] = mapped_column(String(300), comment='')
    website_hpg_url: Mapped[Optional[str]] = mapped_column(String(1000), comment='')
    sgnt_pwfatt_info: Mapped[Optional[str]] = mapped_column(Text, comment='')
    temperat: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), comment='')
    max_serv_num: Mapped[Optional[int]] = mapped_column(Integer, comment='token')
    scene_desc: Mapped[Optional[str]] = mapped_column(Text, comment='')
    model_status: Mapped[Optional[str]] = mapped_column(String(1), comment=' 0- 1-')
    del_flag: Mapped[Optional[str]] = mapped_column(String(1), default='0', comment=' 0- 1-')
    __table_args__ = (
        {'comment': ''},
    )