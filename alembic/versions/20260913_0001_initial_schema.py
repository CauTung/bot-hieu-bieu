"""Create initial bot schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260913_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("sku"),
        sa.CheckConstraint("sku = upper(btrim(sku))", name="ck_products_sku_normalized"),
    )
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.ForeignKeyConstraint(["sku"], ["products.sku"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_sku", "orders", ["sku"])
    op.create_index("ix_orders_order_date", "orders", ["order_date"])
    op.create_index("ix_orders_telegram_user_id", "orders", ["telegram_user_id"])

    op.create_table(
        "reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'cancelled', 'failed')",
            name="ck_reminders_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminders_due", "reminders", ["status", "remind_at", "next_retry_at"])
    op.create_index("ix_reminders_telegram_user_id", "reminders", ["telegram_user_id"])

    op.create_table(
        "pending_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'expired')",
            name="ck_pending_actions_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_actions_owner", "pending_actions", ["telegram_user_id", "chat_id"])
    op.create_index(
        "ix_pending_actions_status_expires", "pending_actions", ["status", "expires_at"]
    )

    op.create_table(
        "processed_updates",
        sa.Column("update_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("status", sa.String(length=20), server_default="processing", nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')", name="ck_processed_updates_status"
        ),
        sa.PrimaryKeyConstraint("update_id"),
    )
    op.create_index("ix_processed_updates_status", "processed_updates", ["status"])


def downgrade() -> None:
    op.drop_table("processed_updates")
    op.drop_table("pending_actions")
    op.drop_table("reminders")
    op.drop_table("orders")
    op.drop_table("products")
