import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SkuImageFingerprint(Base):
    __tablename__ = "sku_image_fingerprints"
    __table_args__ = (
        Index("ix_sku_image_fingerprints_sku", "sku"),
        Index("ix_sku_image_fingerprints_perceptual_hash", "perceptual_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(
        String(100), ForeignKey("products.sku", ondelete="CASCADE"), nullable=False
    )
    telegram_file_unique_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    perceptual_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_in_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
