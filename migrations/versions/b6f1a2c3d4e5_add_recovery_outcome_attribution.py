"""add recovery outcome attribution

Revision ID: b6f1a2c3d4e5
Revises: 9c3e5f7a1b20
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "b6f1a2c3d4e5"
down_revision: str | Sequence[str] | None = "9c3e5f7a1b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add append-friendly provider observations and strict attributions."""

    op.create_table(
        "recovery_outcome_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("recovery_action_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_mode", sa.String(length=8), nullable=False),
        sa.Column("provider_status", sa.String(length=64), nullable=False),
        sa.Column("outcome_status", sa.String(length=24), nullable=False),
        sa.Column("amount_expected_minor", sa.BigInteger(), nullable=False),
        sa.Column("amount_paid_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=True),
        sa.Column(
            "provider_payment_status", sa.String(length=64), nullable=True
        ),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_expected_minor >= 0",
            name=op.f(
                "ck_recovery_outcome_observations_amount_expected_minor_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "amount_paid_minor >= 0",
            name=op.f(
                "ck_recovery_outcome_observations_amount_paid_minor_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "evidence_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_recovery_outcome_observations_evidence_fingerprint_sha256_hex"
            ),
        ),
        sa.CheckConstraint(
            "outcome_status IN ('PENDING', 'RECOVERED', 'EXPIRED', "
            "'CANCELLED', 'REVIEW_REQUIRED')",
            name=op.f("ck_recovery_outcome_observations_outcome_status"),
        ),
        sa.CheckConstraint(
            "provider = 'RAZORPAY'",
            name=op.f("ck_recovery_outcome_observations_provider"),
        ),
        sa.CheckConstraint(
            "provider_mode IN ('TEST', 'LIVE')",
            name=op.f("ck_recovery_outcome_observations_provider_mode"),
        ),
        sa.CheckConstraint(
            "source IN ('POLL', 'WEBHOOK_TRIGGERED')",
            name=op.f("ck_recovery_outcome_observations_source"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["payment_cases.id"],
            name=op.f(
                "fk_recovery_outcome_observations_case_id_payment_cases"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_action_id"],
            ["recovery_actions.id"],
            name=op.f(
                "fk_recovery_outcome_observations_recovery_action_id_recovery_actions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_recovery_outcome_observations")
        ),
        sa.UniqueConstraint(
            "recovery_action_id",
            "evidence_fingerprint",
            name="uq_recovery_outcome_observations_action_evidence",
        ),
    )
    op.create_index(
        "ix_recovery_outcome_observations_action_observed",
        "recovery_outcome_observations",
        ["recovery_action_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_outcome_observations_case_observed",
        "recovery_outcome_observations",
        ["case_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_outcome_observations_mode_currency",
        "recovery_outcome_observations",
        ["provider_mode", "currency"],
        unique=False,
    )

    op.create_table(
        "recovery_attributions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("recovery_action_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_observation_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_mode", sa.String(length=8), nullable=False),
        sa.Column(
            "provider_payment_link_id", sa.String(length=100), nullable=False
        ),
        sa.Column(
            "provider_reference_id", sa.String(length=40), nullable=False
        ),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=False),
        sa.Column("recovered_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "attribution_reason_code", sa.String(length=100), nullable=False
        ),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("attributed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attribution_reason_code = 'ARC_PAYMENT_LINK_CAPTURED'",
            name=op.f("ck_recovery_attributions_reason_code"),
        ),
        sa.CheckConstraint(
            "evidence_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_recovery_attributions_evidence_fingerprint_sha256_hex"
            ),
        ),
        sa.CheckConstraint(
            "provider = 'RAZORPAY'",
            name=op.f("ck_recovery_attributions_provider"),
        ),
        sa.CheckConstraint(
            "provider_mode IN ('TEST', 'LIVE')",
            name=op.f("ck_recovery_attributions_provider_mode"),
        ),
        sa.CheckConstraint(
            "recovered_amount_minor > 0",
            name=op.f(
                "ck_recovery_attributions_recovered_amount_minor_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["payment_cases.id"],
            name=op.f("fk_recovery_attributions_case_id_payment_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outcome_observation_id"],
            ["recovery_outcome_observations.id"],
            name=op.f(
                "fk_recovery_attributions_outcome_observation_id_recovery_outcome_observations"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_action_id"],
            ["recovery_actions.id"],
            name=op.f(
                "fk_recovery_attributions_recovery_action_id_recovery_actions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_recovery_attributions")
        ),
        sa.UniqueConstraint(
            "recovery_action_id", name="uq_recovery_attributions_action"
        ),
        sa.UniqueConstraint(
            "outcome_observation_id",
            name="uq_recovery_attributions_observation",
        ),
        sa.UniqueConstraint(
            "provider_payment_id",
            name="uq_recovery_attributions_provider_payment",
        ),
    )
    op.create_index(
        "ix_recovery_attributions_case_attributed",
        "recovery_attributions",
        ["case_id", "attributed_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_attributions_mode_currency",
        "recovery_attributions",
        ["provider_mode", "currency"],
        unique=False,
    )


def downgrade() -> None:
    """Remove recovery attribution and outcome observation storage."""

    op.drop_index(
        "ix_recovery_attributions_mode_currency",
        table_name="recovery_attributions",
    )
    op.drop_index(
        "ix_recovery_attributions_case_attributed",
        table_name="recovery_attributions",
    )
    op.drop_table("recovery_attributions")
    op.drop_index(
        "ix_recovery_outcome_observations_mode_currency",
        table_name="recovery_outcome_observations",
    )
    op.drop_index(
        "ix_recovery_outcome_observations_case_observed",
        table_name="recovery_outcome_observations",
    )
    op.drop_index(
        "ix_recovery_outcome_observations_action_observed",
        table_name="recovery_outcome_observations",
    )
    op.drop_table("recovery_outcome_observations")
