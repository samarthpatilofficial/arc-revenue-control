"""Reconciled ARC payment case model."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arc.db.base import Base
from arc.domain.enums import CaseState

if TYPE_CHECKING:
    from arc.domain.models.case_event import CaseEvent

case_state_type = SqlEnum(
    CaseState,
    name="case_state",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=32,
)


class PaymentCase(Base):
    """Current reconciled state for revenue considered at risk."""

    __tablename__ = "payment_cases"
    __table_args__ = (
        UniqueConstraint("case_reference", name="uq_payment_cases_case_reference"),
        CheckConstraint(
            "current_state IN ('DETECTED', 'RECONCILING', 'DIAGNOSED', "
            "'DECISIONED', 'POLICY_VALIDATED', 'ACTIONED', "
            "'WAITING_FOR_OUTCOME', 'RECOVERED', 'EXHAUSTED', 'ESCALATED')",
            name="case_state",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="amount_non_negative",
        ),
        Index("ix_payment_cases_merchant_id", "merchant_id"),
        Index("ix_payment_cases_payment_id", "payment_id"),
        Index("ix_payment_cases_subscription_id", "subscription_id"),
        Index("ix_payment_cases_customer_id", "customer_id"),
        Index("ix_payment_cases_current_state", "current_state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String(100))
    subscription_id: Mapped[str | None] = mapped_column(String(100))
    razorpay_payment_status: Mapped[str | None] = mapped_column(String(64))
    razorpay_subscription_status: Mapped[str | None] = mapped_column(String(64))
    customer_id: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[int | None] = mapped_column(
        BigInteger,
        comment="Amount in currency minor units",
    )
    currency: Mapped[str | None] = mapped_column(String(3))
    current_state: Mapped[CaseState] = mapped_column(
        case_state_type,
        nullable=False,
        default=CaseState.DETECTED,
        server_default=CaseState.DETECTED.value,
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_description: Mapped[str | None] = mapped_column(Text)
    error_source: Mapped[str | None] = mapped_column(String(100))
    error_step: Mapped[str | None] = mapped_column(String(100))
    error_reason: Mapped[str | None] = mapped_column(String(100))
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    case_events: Mapped[list["CaseEvent"]] = relationship(
        back_populates="case",
        order_by="CaseEvent.created_at",
    )
