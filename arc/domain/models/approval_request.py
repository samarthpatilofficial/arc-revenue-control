"""Append-friendly human approval records bound to exact policy decisions."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
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
from arc.domain.enums import ApprovalStatus

if TYPE_CHECKING:
    from arc.domain.models.payment_case import PaymentCase
    from arc.domain.models.policy_decision import PolicyDecision
    from arc.domain.models.recovery_action import RecoveryActionRecord


approval_status_type = SqlEnum(
    ApprovalStatus,
    name="approval_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=16,
)


class ApprovalRequest(Base):
    """One operator decision whose authority cannot transfer on reevaluation."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint(
            "policy_decision_id",
            name="uq_approval_requests_policy_decision_id",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL AND "
            "decided_by IS NULL) OR "
            "(status IN ('APPROVED', 'REJECTED') AND "
            "decided_at IS NOT NULL AND decided_by IS NOT NULL)",
            name="decision_metadata",
        ),
        Index(
            "ix_approval_requests_case_id_requested_at",
            "case_id",
            "requested_at",
        ),
        Index("ix_approval_requests_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        approval_status_type,
        nullable=False,
        default=ApprovalStatus.PENDING,
        server_default=ApprovalStatus.PENDING.value,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    case: Mapped["PaymentCase"] = relationship(
        back_populates="approval_requests"
    )
    policy_decision: Mapped["PolicyDecision"] = relationship(
        back_populates="approval_request"
    )
    recovery_actions: Mapped[list["RecoveryActionRecord"]] = relationship(
        back_populates="approval_request",
        order_by="RecoveryActionRecord.created_at",
    )
