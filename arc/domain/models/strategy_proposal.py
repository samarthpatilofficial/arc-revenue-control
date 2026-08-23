"""Append-friendly bounded strategy proposal persistence model."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    Float,
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
from arc.domain.enums import RecoveryAction, StrategySource

if TYPE_CHECKING:
    from arc.domain.models.payment_case import PaymentCase
    from arc.domain.models.policy_decision import PolicyDecision

strategy_source_type = SqlEnum(
    StrategySource,
    name="strategy_source",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=8,
)

recovery_action_type = SqlEnum(
    RecoveryAction,
    name="recovery_action",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=40,
)


class StrategyProposal(Base):
    """One immutable strategy recommendation plus supersession metadata."""

    __tablename__ = "strategy_proposals"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "strategy_input_fingerprint",
            name="uq_strategy_proposals_case_input_fingerprint",
        ),
        CheckConstraint("source IN ('RULE', 'AI')", name="source"),
        CheckConstraint(
            "action IN ('NO_ACTION', 'WAIT', 'REQUEST_RETRY', "
            "'CREATE_RECOVERY_LINK', 'REQUEST_PAYMENT_METHOD_UPDATE', "
            "'ESCALATE_TO_HUMAN')",
            name="action",
        ),
        CheckConstraint(
            "assessment_fingerprint ~ '^[0-9a-f]{64}$'",
            name="assessment_fingerprint_sha256_hex",
        ),
        CheckConstraint(
            "strategy_input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="strategy_input_fingerprint_sha256_hex",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "re_evaluate_after_seconds IS NULL OR "
            "(re_evaluate_after_seconds >= 0 AND "
            "re_evaluate_after_seconds <= 86400)",
            name="re_evaluate_after_seconds_range",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="input_tokens_non_negative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="output_tokens_non_negative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="total_tokens_non_negative",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="latency_ms_non_negative",
        ),
        CheckConstraint(
            "(source = 'AI' AND model IS NOT NULL AND "
            "provider_response_id IS NOT NULL AND confidence IS NOT NULL) OR "
            "(source = 'RULE' AND model IS NULL AND "
            "provider_response_id IS NULL AND confidence IS NULL AND "
            "input_tokens IS NULL AND output_tokens IS NULL AND "
            "total_tokens IS NULL AND latency_ms IS NULL)",
            name="source_metadata",
        ),
        Index(
            "ix_strategy_proposals_case_id_created_at",
            "case_id",
            "created_at",
        ),
        Index(
            "ix_strategy_proposals_assessment_fingerprint",
            "assessment_fingerprint",
        ),
        Index(
            "uq_strategy_proposals_current_case",
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
    assessment_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    strategy_input_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source: Mapped[StrategySource] = mapped_column(
        strategy_source_type,
        nullable=False,
    )
    action: Mapped[RecoveryAction] = mapped_column(
        recovery_action_type,
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    explanation: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    re_evaluate_after_seconds: Mapped[int | None] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    provider_response_id: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    case: Mapped["PaymentCase"] = relationship(
        back_populates="strategy_proposals"
    )
    policy_decisions: Mapped[list["PolicyDecision"]] = relationship(
        back_populates="strategy_proposal",
        order_by="PolicyDecision.evaluated_at",
    )
