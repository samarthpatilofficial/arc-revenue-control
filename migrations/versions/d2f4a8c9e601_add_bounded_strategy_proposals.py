"""add bounded strategy proposals

Revision ID: d2f4a8c9e601
Revises: e4a7c1b8d209
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "d2f4a8c9e601"
down_revision: str | Sequence[str] | None = "e4a7c1b8d209"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create append-friendly bounded strategy proposal persistence."""

    op.create_table(
        "strategy_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column(
            "assessment_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "strategy_input_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("explanation", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("re_evaluate_after_seconds", sa.Integer(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("provider_response_id", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
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
            "action IN ('NO_ACTION', 'WAIT', 'REQUEST_RETRY', "
            "'CREATE_RECOVERY_LINK', 'REQUEST_PAYMENT_METHOD_UPDATE', "
            "'ESCALATE_TO_HUMAN')",
            name=op.f("ck_strategy_proposals_action"),
        ),
        sa.CheckConstraint(
            "assessment_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_strategy_proposals_assessment_fingerprint_sha256_hex"
            ),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_strategy_proposals_confidence_range"),
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name=op.f("ck_strategy_proposals_input_tokens_non_negative"),
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name=op.f("ck_strategy_proposals_latency_ms_non_negative"),
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("ck_strategy_proposals_output_tokens_non_negative"),
        ),
        sa.CheckConstraint(
            "re_evaluate_after_seconds IS NULL OR "
            "(re_evaluate_after_seconds >= 0 AND "
            "re_evaluate_after_seconds <= 86400)",
            name=op.f(
                "ck_strategy_proposals_re_evaluate_after_seconds_range"
            ),
        ),
        sa.CheckConstraint(
            "(source = 'AI' AND model IS NOT NULL AND "
            "provider_response_id IS NOT NULL AND confidence IS NOT NULL) OR "
            "(source = 'RULE' AND model IS NULL AND "
            "provider_response_id IS NULL AND confidence IS NULL AND "
            "input_tokens IS NULL AND output_tokens IS NULL AND "
            "total_tokens IS NULL AND latency_ms IS NULL)",
            name=op.f("ck_strategy_proposals_source_metadata"),
        ),
        sa.CheckConstraint(
            "source IN ('RULE', 'AI')",
            name=op.f("ck_strategy_proposals_source"),
        ),
        sa.CheckConstraint(
            "strategy_input_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_strategy_proposals_strategy_input_fingerprint_sha256_hex"
            ),
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name=op.f("ck_strategy_proposals_total_tokens_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["payment_cases.id"],
            name=op.f("fk_strategy_proposals_case_id_payment_cases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_strategy_proposals"),
        ),
        sa.UniqueConstraint(
            "case_id",
            "strategy_input_fingerprint",
            name="uq_strategy_proposals_case_input_fingerprint",
        ),
    )
    op.create_index(
        "ix_strategy_proposals_assessment_fingerprint",
        "strategy_proposals",
        ["assessment_fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_proposals_case_id_created_at",
        "strategy_proposals",
        ["case_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_strategy_proposals_current_case",
        "strategy_proposals",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    """Remove bounded strategy proposal persistence."""

    op.drop_index(
        "uq_strategy_proposals_current_case",
        table_name="strategy_proposals",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.drop_index(
        "ix_strategy_proposals_case_id_created_at",
        table_name="strategy_proposals",
    )
    op.drop_index(
        "ix_strategy_proposals_assessment_fingerprint",
        table_name="strategy_proposals",
    )
    op.drop_table("strategy_proposals")
