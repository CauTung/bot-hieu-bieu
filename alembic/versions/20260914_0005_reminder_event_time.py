"""Separate reminder delivery time from event time."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_0005"
down_revision: str | None = "20260914_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reminders", sa.Column("event_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reminders", "event_at")
