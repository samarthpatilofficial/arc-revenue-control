"""Authoritative recovery outcome evidence and revenue attribution models."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arc.db.base import Base
from arc.domain.enums import (
    OutcomeObservationSource,
    ProviderMode,
    RecoveryOutcomeStatus,
)

if TYPE_CHECKING:
    from arc.domain.models.payment_case import PaymentCase
    from arc.domain.models.recovery_action import RecoveryActionRecord


provider_mode_type = SqlEnum(
    ProviderMode,
    name="provider_mode",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=8,
)

outcome_observation_source_type = SqlEnum(
    OutcomeObservationSource,
    name="outcome_observation_source",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=24,
)

recovery_outcome_status_type = SqlEnum(
    RecoveryOutcomeStatus,
    name="recovery_outcome_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=24,
)


class RecoveryOutcomeObservation(Base):
    """One normalized, append-friendly authoritative provider observation."""

    __tablename__ = "recovery_outcome_observations"
    __table_args__ = (
        UniqueConstraint(
            "recovery_action_id",
            "evidence_fingerprint",
            name="uq_recovery_outcome_observations_action_evidence",
        ),
        CheckConstraint("provider = 'RAZORPAY'", name="provider"),
        CheckConstraint(
            "provider_mode IN ('TEST', 'LIVE')", name="provider_mode"
        ),
        CheckConstraint(
            "source IN ('POLL', 'WEBHOOK_TRIGGERED')", name="source"
        ),
        CheckConstraint(
            "outcome_status IN ('PENDING', 'RECOVERED', 'EXPIRED', "
            "'CANCELLED', 'REVIEW_REQUIRED')",
            name="outcome_status",
        ),
        CheckConstraint(
            "amount_expected_minor >= 0",
            name="amount_expected_non_negative",
        ),
        CheckConstraint(
            "amount_paid_minor >= 0", name="amount_paid_minor_non_negative"
        ),
        CheckConstraint(
            "evidence_fingerprint ~ '^[0-9a-f]{64}$'",
            name="evidence_sha256_hex",
        ),
        Index(
            "ix_recovery_outcome_observations_case_observed",
            "case_id",
            "observed_at",
        ),
        Index(
            "ix_recovery_outcome_observations_action_observed",
            "recovery_action_id",
            "observed_at",
        ),
        Index(
            "ix_recovery_outcome_observations_mode_currency",
            "provider_mode",
            "currency",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_cases.id", ondelete="RESTRICT"), nullable=False
    )
    recovery_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("recovery_actions.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[OutcomeObservationSource] = mapped_column(
        outcome_observation_source_type, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_mode: Mapped[ProviderMode] = mapped_column(
        provider_mode_type, nullable=False
    )
    provider_status: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_status: Mapped[RecoveryOutcomeStatus] = mapped_column(
        recovery_outcome_status_type, nullable=False
    )
    amount_expected_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    amount_paid_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100))
    provider_payment_status: Mapped[str | None] = mapped_column(String(64))
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    case: Mapped["PaymentCase"] = relationship(
        back_populates="outcome_observations"
    )
    recovery_action: Mapped["RecoveryActionRecord"] = relationship(
        back_populates="outcome_observations"
    )
    attribution: Mapped["RecoveryAttribution | None"] = relationship(
        back_populates="outcome_observation", uselist=False
    )


class RecoveryAttribution(Base):
    """One strictly evidenced recovered-revenue attribution."""

    __tablename__ = "recovery_attributions"
    __table_args__ = (
        UniqueConstraint(
            "recovery_action_id", name="uq_recovery_attributions_action"
        ),
        UniqueConstraint(
            "outcome_observation_id",
            name="uq_recovery_attributions_observation",
        ),
        UniqueConstraint(
            "provider_payment_id",
            name="uq_recovery_attributions_provider_payment",
        ),
        CheckConstraint("provider = 'RAZORPAY'", name="provider"),
        CheckConstraint(
            "provider_mode IN ('TEST', 'LIVE')", name="provider_mode"
        ),
        CheckConstraint(
            "recovered_amount_minor > 0",
            name="recovered_amount_minor_positive",
        ),
        CheckConstraint(
            "attribution_reason_code = 'ARC_PAYMENT_LINK_CAPTURED'",
            name="reason_code",
        ),
        CheckConstraint(
            "evidence_fingerprint ~ '^[0-9a-f]{64}$'",
            name="evidence_fingerprint_sha256_hex",
        ),
        Index(
            "ix_recovery_attributions_case_attributed",
            "case_id",
            "attributed_at",
        ),
        Index(
            "ix_recovery_attributions_mode_currency",
            "provider_mode",
            "currency",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_cases.id", ondelete="RESTRICT"), nullable=False
    )
    recovery_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("recovery_actions.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_observation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "recovery_outcome_observations.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_mode: Mapped[ProviderMode] = mapped_column(
        provider_mode_type, nullable=False
    )
    provider_payment_link_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    provider_reference_id: Mapped[str] = mapped_column(
        String(40), nullable=False
    )
    provider_payment_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    recovered_amount_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    attribution_reason_code: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    attributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    case: Mapped["PaymentCase"] = relationship(back_populates="attributions")
    recovery_action: Mapped["RecoveryActionRecord"] = relationship(
        back_populates="attribution"
    )
    outcome_observation: Mapped["RecoveryOutcomeObservation"] = relationship(
        back_populates="attribution"
    )
