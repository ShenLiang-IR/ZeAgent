from datetime import datetime
from typing import Optional
from sqlalchemy import func, String, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
class TellerAuditMixin:
    create_teller_no: Mapped[Optional[str]] = mapped_column(String(11))
    create_teller_name: Mapped[Optional[str]] = mapped_column(String(100))
    mod_teller_name: Mapped[Optional[str]] = mapped_column(String(100))
    upd_teller_no: Mapped[Optional[str]] = mapped_column(String(11))
class TimestampMixin:
    create_stamp: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=True
    )
    upd_stamp: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True
    )
class TellerTimestampMixin(TellerAuditMixin, TimestampMixin):
    pass
class TimestampMixinLegacy:
    create_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    update_time: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        onupdate=func.now()
    )
def get_create_time(entity: Base) -> Optional[datetime]:
    return (
        getattr(entity, 'create_stamp', None) or
        getattr(entity, 'create_time', None)
    )
def get_update_time(entity: Base) -> Optional[datetime]:
    return (
        getattr(entity, 'upd_stamp', None) or
        getattr(entity, 'update_time', None) or
        getattr(entity, 'update_time', None)
    )