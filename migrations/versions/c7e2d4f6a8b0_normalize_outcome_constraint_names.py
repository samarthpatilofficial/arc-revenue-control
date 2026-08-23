"""normalize outcome constraint names

Revision ID: c7e2d4f6a8b0
Revises: b6f1a2c3d4e5
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7e2d4f6a8b0"
down_revision: str | Sequence[str] | None = "b6f1a2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give two PostgreSQL-truncated CHECK names stable bounded names."""

    op.execute(
        "ALTER TABLE recovery_outcome_observations RENAME CONSTRAINT "
        "ck_recovery_outcome_observations_amount_expected_minor__281c TO "
        "ck_recovery_outcome_observations_amount_expected_non_negative"
    )
    op.execute(
        "ALTER TABLE recovery_outcome_observations RENAME CONSTRAINT "
        "ck_recovery_outcome_observations_evidence_fingerprint_s_b8f4 TO "
        "ck_recovery_outcome_observations_evidence_sha256_hex"
    )


def downgrade() -> None:
    """Restore the names produced by the original table migration."""

    op.execute(
        "ALTER TABLE recovery_outcome_observations RENAME CONSTRAINT "
        "ck_recovery_outcome_observations_evidence_sha256_hex TO "
        "ck_recovery_outcome_observations_evidence_fingerprint_s_b8f4"
    )
    op.execute(
        "ALTER TABLE recovery_outcome_observations RENAME CONSTRAINT "
        "ck_recovery_outcome_observations_amount_expected_non_negative TO "
        "ck_recovery_outcome_observations_amount_expected_minor__281c"
    )
