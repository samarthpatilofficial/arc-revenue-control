"""add governed recovery execution

Revision ID: 9c3e5f7a1b20
Revises: 7b2d4e6f8a10
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "9c3e5f7a1b20"
down_revision: str | Sequence[str] | None = "7b2d4e6f8a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add decision-scoped approvals and crash-safe recovery actions."""

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL AND "
            "decided_by IS NULL) OR "
            "(status IN ('APPROVED', 'REJECTED') AND "
            "decided_at IS NOT NULL AND decided_by IS NOT NULL)",
            name=op.f("ck_approval_requests_decision_metadata"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name=op.f("ck_approval_requests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["payment_cases.id"],
            name=op.f("fk_approval_requests_case_id_payment_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decisions.id"],
            name=op.f(
                "fk_approval_requests_policy_decision_id_policy_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        sa.UniqueConstraint(
            "policy_decision_id",
            name="uq_approval_requests_policy_decision_id",
        ),
    )
    op.create_index(
        "ix_approval_requests_case_id_requested_at",
        "approval_requests",
        ["case_id", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_approval_requests_status",
        "approval_requests",
        ["status"],
        unique=False,
    )

    op.create_table(
        "recovery_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_proposal_id", sa.Uuid(), nullable=False),
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("approval_request_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column(
            "execution_status",
            sa.String(length=24),
            server_default="PREPARED",
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "request_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column(
            "external_reference_id",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "external_reference",
            sa.String(length=40),
            nullable=True,
        ),
        sa.Column(
            "external_status",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "external_url",
            sa.String(length=500),
            nullable=True,
        ),
        sa.Column(
            "external_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "execution_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "execution_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "next_evaluation_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('NO_ACTION', 'WAIT', 'REQUEST_RETRY', "
            "'CREATE_RECOVERY_LINK', 'REQUEST_PAYMENT_METHOD_UPDATE', "
            "'ESCALATE_TO_HUMAN')",
            name=op.f("ck_recovery_actions_action"),
        ),
        sa.CheckConstraint(
            "execution_attempt_count >= 0",
            name=op.f(
                "ck_recovery_actions_execution_attempt_count_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "execution_status IN ('PREPARED', 'IN_PROGRESS', 'SUCCEEDED', "
            "'FAILED', 'INDETERMINATE', 'CANCELLED', "
            "'COMPENSATION_REQUIRED')",
            name=op.f("ck_recovery_actions_execution_status"),
        ),
        sa.CheckConstraint(
            "external_reference IS NULL OR "
            "char_length(external_reference) <= 40",
            name=op.f("ck_recovery_actions_external_reference_length"),
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_recovery_actions_idempotency_key_sha256_hex"),
        ),
        sa.CheckConstraint(
            "provider IN ('INTERNAL', 'RAZORPAY')",
            name=op.f("ck_recovery_actions_provider"),
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_recovery_actions_request_fingerprint_sha256_hex"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["approval_request_id"],
            ["approval_requests.id"],
            name=op.f(
                "fk_recovery_actions_approval_request_id_approval_requests"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["payment_cases.id"],
            name=op.f("fk_recovery_actions_case_id_payment_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decisions.id"],
            name=op.f(
                "fk_recovery_actions_policy_decision_id_policy_decisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_proposal_id"],
            ["strategy_proposals.id"],
            name=op.f(
                "fk_recovery_actions_strategy_proposal_id_strategy_proposals"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_actions")),
        sa.UniqueConstraint(
            "external_reference",
            name="uq_recovery_actions_external_reference",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_recovery_actions_idempotency_key",
        ),
        sa.UniqueConstraint(
            "policy_decision_id",
            name="uq_recovery_actions_policy_decision_id",
        ),
    )
    op.create_index(
        "ix_recovery_actions_approval_request_id",
        "recovery_actions",
        ["approval_request_id"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_actions_case_id_created_at",
        "recovery_actions",
        ["case_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_actions_execution_status",
        "recovery_actions",
        ["execution_status"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_actions_strategy_proposal_id",
        "recovery_actions",
        ["strategy_proposal_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove governed recovery execution and human approvals."""

    op.drop_index(
        "ix_recovery_actions_strategy_proposal_id",
        table_name="recovery_actions",
    )
    op.drop_index(
        "ix_recovery_actions_execution_status",
        table_name="recovery_actions",
    )
    op.drop_index(
        "ix_recovery_actions_case_id_created_at",
        table_name="recovery_actions",
    )
    op.drop_index(
        "ix_recovery_actions_approval_request_id",
        table_name="recovery_actions",
    )
    op.drop_table("recovery_actions")
    op.drop_index(
        "ix_approval_requests_status",
        table_name="approval_requests",
    )
    op.drop_index(
        "ix_approval_requests_case_id_requested_at",
        table_name="approval_requests",
    )
    op.drop_table("approval_requests")
