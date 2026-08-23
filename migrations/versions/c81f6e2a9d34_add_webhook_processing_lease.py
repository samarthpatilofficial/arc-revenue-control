"""add webhook processing lease

Revision ID: c81f6e2a9d34
Revises: f52c7d91a4be
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "c81f6e2a9d34"
down_revision: str | Sequence[str] | None = "f52c7d91a4be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add crash-recovery metadata to mutable event processing state."""

    op.add_column(
        "webhook_events",
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "webhook_events",
        sa.Column(
            "processing_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_webhook_events_processing_attempt_count_non_negative"),
        "webhook_events",
        "processing_attempt_count >= 0",
    )


def downgrade() -> None:
    """Remove event processing lease metadata."""

    op.drop_constraint(
        op.f("ck_webhook_events_processing_attempt_count_non_negative"),
        "webhook_events",
        type_="check",
    )
    op.drop_column("webhook_events", "processing_attempt_count")
    op.drop_column("webhook_events", "processing_started_at")
