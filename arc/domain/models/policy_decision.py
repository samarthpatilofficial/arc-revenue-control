"""Append-friendly deterministic merchant authorization decisions."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arc.db.base import Base
from arc.domain.enums import PolicyDecisionResult

if TYPE_CHECKING:
    from arc.domain.models.merchant_policy import MerchantPolicy
    from arc.domain.models.payment_case import PaymentCase
    from arc.domain.models.strategy_proposal import StrategyProposal

policy_decision_result_type = SqlEnum(
    PolicyDecisionResult,
    name="policy_decision_result",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=24,
)


class PolicyDecision(Base):
    """One deterministic policy result plus bounded observed inputs."""

    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "authorization_input_fingerprint",
            name="uq_policy_decisions_case_authorization_input",
        ),
        CheckConstraint(
            "result IN ('AUTHORIZED', 'REQUIRES_APPROVAL', 'BLOCKED')",
            name="result",
        ),
        CheckConstraint(
            "strategy_input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="strategy_input_fingerprint_sha256_hex",
        ),
        CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$'",
            name="policy_fingerprint_sha256_hex",
        ),
        CheckConstraint(
            "authorization_input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="authorization_input_fingerprint_sha256_hex",
        ),
        CheckConstraint(
            "approval_threshold_minor IS NULL OR "
            "approval_threshold_minor >= 0",
            name="approval_threshold_non_negative",
        ),
        CheckConstraint(
            "high_value_threshold_minor IS NULL OR "
            "high_value_threshold_minor >= 0",
            name="high_value_threshold_non_negative",
        ),
        CheckConstraint(
            "observed_amount_minor IS NULL OR observed_amount_minor >= 0",
            name="observed_amount_non_negative",
        ),
        CheckConstraint(
            "observed_attempt_count >= 0",
            name="observed_attempt_count_non_negative",
        ),
        CheckConstraint(
            "observed_contact_attempt_count >= 0",
            name="observed_contact_attempt_count_non_negative",
        ),
        Index(
            "ix_policy_decisions_case_id_evaluated_at",
            "case_id",
            "evaluated_at",
        ),
        Index(
            "ix_policy_decisions_strategy_proposal_id",
            "strategy_proposal_id",
        ),
        Index(
            "ix_policy_decisions_merchant_policy_id",
            "merchant_policy_id",
        ),
        Index(
            "uq_policy_decisions_current_case",
            "case_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    strategy_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_proposals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    merchant_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("merchant_policies.id", ondelete="RESTRICT")
    )
    strategy_input_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_input_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    result: Mapped[PolicyDecisionResult] = mapped_column(
        policy_decision_result_type,
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    explanation: Mapped[str] = mapped_column(String(300), nullable=False)
    recovery_window_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    approval_threshold_minor: Mapped[int | None] = mapped_column(BigInteger)
    high_value_threshold_minor: Mapped[int | None] = mapped_column(BigInteger)
    observed_high_value: Mapped[bool | None] = mapped_column(Boolean)
    observed_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    observed_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    observed_contact_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    case: Mapped["PaymentCase"] = relationship(back_populates="policy_decisions")
    strategy_proposal: Mapped["StrategyProposal"] = relationship(
        back_populates="policy_decisions"
    )
    merchant_policy: Mapped["MerchantPolicy | None"] = relationship(
        back_populates="policy_decisions"
    )
