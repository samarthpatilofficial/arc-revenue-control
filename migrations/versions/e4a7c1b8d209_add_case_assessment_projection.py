"""add case assessment projection

Revision ID: e4a7c1b8d209
Revises: c81f6e2a9d34
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "e4a7c1b8d209"
down_revision: str | Sequence[str] | None = "c81f6e2a9d34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add current deterministic eligibility and diagnosis projection fields."""

    op.add_column(
        "payment_cases",
        sa.Column("razorpay_payment_method", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payment_cases",
        sa.Column("eligibility_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "payment_cases",
        sa.Column(
            "eligibility_reason_code",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_cases",
        sa.Column(
            "eligibility_evaluated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_cases",
        sa.Column("failure_category", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "payment_cases",
        sa.Column("recovery_disposition", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "payment_cases",
        sa.Column(
            "diagnosis_reason_code",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_cases",
        sa.Column("diagnosed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_cases",
        sa.Column(
            "assessment_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        op.f("ck_payment_cases_eligibility_status"),
        "payment_cases",
        "eligibility_status IS NULL OR eligibility_status IN "
        "('ELIGIBLE', 'WAIT', 'STOP', 'REVIEW')",
    )
    op.create_check_constraint(
        op.f("ck_payment_cases_failure_category"),
        "payment_cases",
        "failure_category IS NULL OR failure_category IN "
        "('CUSTOMER_AUTHENTICATION', 'CUSTOMER_FUNDS', "
        "'CUSTOMER_INTERRUPTION', "
        "'CUSTOMER_OR_INSTRUMENT_RESTRICTION', 'BANK_OR_ISSUER', "
        "'GATEWAY_OR_NETWORK', 'MERCHANT_CONFIGURATION', "
        "'RAZORPAY_OR_PLATFORM', 'SUBSCRIPTION_RETRY_EXHAUSTED', "
        "'UNKNOWN')",
    )
    op.create_check_constraint(
        op.f("ck_payment_cases_recovery_disposition"),
        "payment_cases",
        "recovery_disposition IS NULL OR recovery_disposition IN "
        "('CUSTOMER_ACTION_REQUIRED', 'RETRY_LATER', "
        "'ALTERNATE_METHOD_PREFERRED', 'MERCHANT_FIX_REQUIRED', "
        "'RECOVERY_STRATEGY_REQUIRED', 'MANUAL_REVIEW', 'UNKNOWN')",
    )
    op.create_check_constraint(
        op.f("ck_payment_cases_assessment_fingerprint_sha256_hex"),
        "payment_cases",
        "assessment_fingerprint IS NULL OR "
        "assessment_fingerprint ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    """Remove the current assessment projection."""

    for constraint_name in (
        "ck_payment_cases_assessment_fingerprint_sha256_hex",
        "ck_payment_cases_recovery_disposition",
        "ck_payment_cases_failure_category",
        "ck_payment_cases_eligibility_status",
    ):
        op.drop_constraint(
            op.f(constraint_name),
            "payment_cases",
            type_="check",
        )

    for column_name in (
        "assessment_fingerprint",
        "diagnosed_at",
        "diagnosis_reason_code",
        "recovery_disposition",
        "failure_category",
        "eligibility_evaluated_at",
        "eligibility_reason_code",
        "eligibility_status",
        "razorpay_payment_method",
    ):
        op.drop_column("payment_cases", column_name)
