from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, BigInteger, TIMESTAMP as SqlTIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from ..base import Base
class Mode(Base):
    __tablename__ = "tb_mode"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dclr_ptn_name: Mapped[Optional[str]] = mapped_column(String(100))
    en_name: Mapped[Optional[str]] = mapped_column(String(100))
    thval_desc_desc: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(1))
    comprehe_sugg_content: Mapped[Optional[str]] = mapped_column(Text)
    rem_pers_name: Mapped[Optional[str]] = mapped_column(String(500))
    by_rem_pers_name: Mapped[Optional[str]] = mapped_column(String(100))
    deal_num: Mapped[Optional[int]] = mapped_column(Integer)
    data_use_scene_name: Mapped[Optional[str]] = mapped_column(String(500))
    apply_lmtms: Mapped[Optional[int]] = mapped_column(Integer)
    para_eff_scope_cd: Mapped[Optional[str]] = mapped_column(String(2))
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    mode_type: Mapped[Optional[str]] = mapped_column(String(100))
    create_teller_no: Mapped[Optional[str]] = mapped_column(String(11))
    create_teller_name: Mapped[Optional[str]] = mapped_column(String(100))
    mod_teller_name: Mapped[Optional[str]] = mapped_column(String(100))
    upd_teller_no: Mapped[Optional[str]] = mapped_column(String(11))
    create_stamp: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now())
    upd_stamp: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        {'comment': ''},
    )