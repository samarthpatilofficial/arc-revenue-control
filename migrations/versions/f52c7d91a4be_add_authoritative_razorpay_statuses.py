"""add authoritative Razorpay statuses

Revision ID: f52c7d91a4be
Revises: a87c1e9d4f02
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "f52c7d91a4be"
down_revision: str | Sequence[str] | None = "a87c1e9d4f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store external payment and subscription truth separately from ARC state."""

    op.add_column(
        "payment_cases",
        sa.Column("razorpay_payment_status", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payment_cases",
        sa.Column(
            "razorpay_subscription_status",
            sa.String(length=64),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the external status snapshots."""

    op.drop_column("payment_cases", "razorpay_subscription_status")
    op.drop_column("payment_cases", "razorpay_payment_status")
