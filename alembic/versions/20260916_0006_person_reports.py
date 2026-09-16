"""Daily person reports, independent of SKU orders."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260916_0006"
down_revision: str | None = "20260914_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("person_key", sa.String(160), nullable=False),
        sa.Column("person_name", sa.String(80), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("telegram_user_id", "chat_id", "report_date", "person_key",
                            name="uq_person_report_scope_day_name"),
        sa.CheckConstraint("count >= 0", name="ck_person_report_nonnegative"),
    )


def downgrade() -> None:
    op.drop_table("person_reports")
