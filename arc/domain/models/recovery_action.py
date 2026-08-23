"""Crash-safe ledger for governed internal and external recovery actions."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arc.db.base import Base
from arc.domain.enums import RecoveryAction, RecoveryExecutionStatus
from arc.domain.models.strategy_proposal import recovery_action_type

if TYPE_CHECKING:
    from arc.domain.models.approval_request import ApprovalRequest
    from arc.domain.models.payment_case import PaymentCase
    from arc.domain.models.policy_decision import PolicyDecision
    from arc.domain.models.recovery_outcome import (
        RecoveryAttribution,
        RecoveryOutcomeObservation,
    )
    from arc.domain.models.strategy_proposal import StrategyProposal


recovery_execution_status_type = SqlEnum(
    RecoveryExecutionStatus,
    name="recovery_execution_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=24,
)


class RecoveryActionRecord(Base):
    """One idempotent execution intent and its sanitized provider outcome."""

    __tablename__ = "recovery_actions"
    __table_args__ = (
        UniqueConstraint(
            "policy_decision_id",
            name="uq_recovery_actions_policy_decision_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_recovery_actions_idempotency_key",
        ),
        UniqueConstraint(
            "external_reference",
            name="uq_recovery_actions_external_reference",
        ),
        CheckConstraint(
            "action IN ('NO_ACTION', 'WAIT', 'REQUEST_RETRY', "
            "'CREATE_RECOVERY_LINK', 'REQUEST_PAYMENT_METHOD_UPDATE', "
            "'ESCALATE_TO_HUMAN')",
            name="action",
        ),
        CheckConstraint(
            "execution_status IN ('PREPARED', 'IN_PROGRESS', 'SUCCEEDED', "
            "'FAILED', 'INDETERMINATE', 'CANCELLED', "
            "'COMPENSATION_REQUIRED')",
            name="execution_status",
        ),
        CheckConstraint(
            "provider IN ('INTERNAL', 'RAZORPAY')",
            name="provider",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'",
            name="idempotency_key_sha256_hex",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="request_fingerprint_sha256_hex",
        ),
        CheckConstraint(
            "execution_attempt_count >= 0",
            name="execution_attempt_count_non_negative",
        ),
        CheckConstraint(
            "external_reference IS NULL OR "
            "char_length(external_reference) <= 40",
            name="external_reference_length",
        ),
        Index(
            "ix_recovery_actions_case_id_created_at",
            "case_id",
            "created_at",
        ),
        Index(
            "ix_recovery_actions_execution_status",
            "execution_status",
        ),
        Index(
            "ix_recovery_actions_strategy_proposal_id",
            "strategy_proposal_id",
        ),
        Index(
            "ix_recovery_actions_approval_request_id",
            "approval_request_id",
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
    policy_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    action: Mapped[RecoveryAction] = mapped_column(
        recovery_action_type,
        nullable=False,
    )
    execution_status: Mapped[RecoveryExecutionStatus] = mapped_column(
        recovery_execution_status_type,
        nullable=False,
        default=RecoveryExecutionStatus.PREPARED,
        server_default=RecoveryExecutionStatus.PREPARED.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    external_reference_id: Mapped[str | None] = mapped_column(String(100))
    external_reference: Mapped[str | None] = mapped_column(String(40))
    external_status: Mapped[str | None] = mapped_column(String(64))
    external_url: Mapped[str | None] = mapped_column(String(500))
    external_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    execution_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    execution_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    next_evaluation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    case: Mapped["PaymentCase"] = relationship(
        back_populates="recovery_actions"
    )
    strategy_proposal: Mapped["StrategyProposal"] = relationship(
        back_populates="recovery_actions"
    )
    policy_decision: Mapped["PolicyDecision"] = relationship(
        back_populates="recovery_action"
    )
    approval_request: Mapped["ApprovalRequest | None"] = relationship(
        back_populates="recovery_actions"
    )
    outcome_observations: Mapped[list["RecoveryOutcomeObservation"]] = relationship(
        back_populates="recovery_action",
        order_by="RecoveryOutcomeObservation.observed_at",
    )
    attribution: Mapped["RecoveryAttribution | None"] = relationship(
        back_populates="recovery_action", uselist=False
    )
