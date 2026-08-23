"""add raw webhook body hash

Revision ID: a87c1e9d4f02
Revises: 002cdbacef93
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "a87c1e9d4f02"
down_revision: str | Sequence[str] | None = "002cdbacef93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add exact request-body integrity metadata without rewriting legacy rows."""

    op.add_column(
        "webhook_events",
        sa.Column(
            "raw_body_sha256",
            sa.String(length=64),
            nullable=True,
            comment="Exact request-body SHA-256; null only for pre-migration rows",
        ),
    )
    op.create_check_constraint(
        op.f("ck_webhook_events_raw_body_sha256_hex"),
        "webhook_events",
        "raw_body_sha256 IS NULL OR "
        "raw_body_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    """Remove exact request-body integrity metadata."""

    op.drop_constraint(
        op.f("ck_webhook_events_raw_body_sha256_hex"),
        "webhook_events",
        type_="check",
    )
    op.drop_column("webhook_events", "raw_body_sha256")
