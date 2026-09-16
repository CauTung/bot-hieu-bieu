import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class PersonReport(Base):
    __tablename__ = "person_reports"
    __table_args__ = (
        UniqueConstraint(
            "telegram_user_id", "chat_id", "report_date", "person_key",
            name="uq_person_report_scope_day_name",
        ),
        CheckConstraint("count >= 0", name="ck_person_report_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    person_key: Mapped[str] = mapped_column(String(160), nullable=False)
    person_name: Mapped[str] = mapped_column(String(80), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
