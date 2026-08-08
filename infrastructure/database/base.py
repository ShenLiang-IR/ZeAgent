from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, func
class Base(DeclarativeBase):
    pass
class TimestampMixin:
    create_time: Mapped[datetime] = mapped_column(
        "create_time",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=True
    )
    update_time: Mapped[datetime] = mapped_column(
        "update_time",
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True
    )
class StampTimestampMixin:
    create_stamp: Mapped[datetime] = mapped_column(
        "create_stamp",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=True
    )
    upd_stamp: Mapped[datetime] = mapped_column(
        "upd_stamp",
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True
    )