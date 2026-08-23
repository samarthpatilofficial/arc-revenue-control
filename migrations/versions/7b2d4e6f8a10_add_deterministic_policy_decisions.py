"""add deterministic policy decisions

Revision ID: 7b2d4e6f8a10
Revises: d2f4a8c9e601
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "7b2d4e6f8a10"
down_revision: str | Sequence[str] | None = "d2f4a8c9e601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add contact projection and append-friendly authorization history."""

    op.add_column(
        "payment_cases",
        sa.Column(
            "contact_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_payment_cases_contact_attempt_count_non_negative"),
        "payment_cases",
        "contact_attempt_count >= 0",
    )

    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_proposal_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_policy_id", sa.Uuid(), nullable=True),
        sa.Column(
            "strategy_input_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "policy_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "authorization_input_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("result", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("explanation", sa.String(length=300), nullable=False),
        sa.Column(
            "recovery_window_ends_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("approval_threshold_minor", sa.BigInteger(), nullable=True),
        sa.Column("high_value_threshold_minor", sa.BigInteger(), nullable=True),
        sa.Column("observed_high_value", sa.Boolean(), nullable=True),
        sa.Column("observed_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("observed_attempt_count", sa.Integer(), nullable=False),
        sa.Column(
            "observed_contact_attempt_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "superseded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "approval_threshold_minor IS NULL OR "
            "approval_threshold_minor >= 0",
            name=op.f("ck_policy_decisions_approval_threshold_non_negative"),
        ),
        sa.CheckConstraint(
            "authorization_input_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_policy_decisions_authorization_input_fingerprint_sha256_hex"
            ),
        ),
        sa.CheckConstraint(
            "high_value_threshold_minor IS NULL OR "
            "high_value_threshold_minor >= 0",
            name=op.f(
                "ck_policy_decisions_high_value_threshold_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "observed_amount_minor IS NULL OR observed_amount_minor >= 0",
            name=op.f("ck_policy_decisions_observed_amount_non_negative"),
        ),
        sa.CheckConstraint(
            "observed_attempt_count >= 0",
            name=op.f(
                "ck_policy_decisions_observed_attempt_count_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "observed_contact_attempt_count >= 0",
            name=op.f(
                "ck_policy_decisions_observed_contact_attempt_count_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_policy_decisions_policy_fingerprint_sha256_hex"),
        ),
        sa.CheckConstraint(
            "result IN ('AUTHORIZED', 'REQUIRES_APPROVAL', 'BLOCKED')",
            name=op.f("ck_policy_decisions_result"),
        ),
        sa.CheckConstraint(
            "strategy_input_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_policy_decisions_strategy_input_fingerprint_sha256_hex"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["payment_cases.id"],
            name=op.f("fk_policy_decisions_case_id_payment_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_policy_id"],
            ["merchant_policies.id"],
            name=op.f(
                "fk_policy_decisions_merchant_policy_id_merchant_policies"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_proposal_id"],
            ["strategy_proposals.id"],
            name=op.f(
                "fk_policy_decisions_strategy_proposal_id_strategy_proposals"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_decisions")),
        sa.UniqueConstraint(
            "case_id",
            "authorization_input_fingerprint",
            name="uq_policy_decisions_case_authorization_input",
        ),
    )
    op.create_index(
        "ix_policy_decisions_case_id_evaluated_at",
        "policy_decisions",
        ["case_id", "evaluated_at"],
        unique=False,
    )
    op.create_index(
        "ix_policy_decisions_merchant_policy_id",
        "policy_decisions",
        ["merchant_policy_id"],
        unique=False,
    )
    op.create_index(
        "ix_policy_decisions_strategy_proposal_id",
        "policy_decisions",
        ["strategy_proposal_id"],
        unique=False,
    )
    op.create_index(
        "uq_policy_decisions_current_case",
        "policy_decisions",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    """Remove deterministic authorization history and contact projection."""

    op.drop_index(
        "uq_policy_decisions_current_case",
        table_name="policy_decisions",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.drop_index(
        "ix_policy_decisions_strategy_proposal_id",
        table_name="policy_decisions",
    )
    op.drop_index(
        "ix_policy_decisions_merchant_policy_id",
        table_name="policy_decisions",
    )
    op.drop_index(
        "ix_policy_decisions_case_id_evaluated_at",
        table_name="policy_decisions",
    )
    op.drop_table("policy_decisions")
    op.drop_constraint(
        op.f("ck_payment_cases_contact_attempt_count_non_negative"),
        "payment_cases",
        type_="check",
    )
    op.drop_column("payment_cases", "contact_attempt_count")
