"""Store image fingerprints used to identify SKUs."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260914_0004"
down_revision: str | None = "20260914_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sku_image_fingerprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("telegram_file_unique_id", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("perceptual_hash", sa.String(length=16), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_in_chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["sku"], ["products.sku"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_file_unique_id"),
    )
    op.create_index("ix_sku_image_fingerprints_sku", "sku_image_fingerprints", ["sku"])
    op.create_index("ix_sku_image_fingerprints_sha256", "sku_image_fingerprints", ["sha256"])
    op.create_index(
        "ix_sku_image_fingerprints_perceptual_hash",
        "sku_image_fingerprints",
        ["perceptual_hash"],
    )


def downgrade() -> None:
    op.drop_table("sku_image_fingerprints")
