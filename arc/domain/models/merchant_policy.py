"""Merchant recovery-control configuration model."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arc.db.base import Base


class MerchantPolicy(Base):
    """Persisted deterministic limits for a merchant's future authorization rules."""

    __tablename__ = "merchant_policies"
    __table_args__ = (
        UniqueConstraint("merchant_id", name="uq_merchant_policies_merchant_id"),
        CheckConstraint(
            "max_automated_attempts >= 0",
            name="max_automated_attempts_non_negative",
        ),
        CheckConstraint(
            "max_contact_attempts >= 0",
            name="max_contact_attempts_non_negative",
        ),
        CheckConstraint(
            "recovery_window_minutes >= 0",
            name="recovery_window_non_negative",
        ),
        CheckConstraint(
            "high_value_threshold_minor >= 0",
            name="high_value_threshold_non_negative",
        ),
        CheckConstraint(
            "require_approval_above_minor IS NULL "
            "OR require_approval_above_minor >= 0",
            name="approval_threshold_non_negative",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    merchant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    automation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    allowed_actions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    max_automated_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_contact_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    recovery_window_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    high_value_threshold_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    require_approval_above_minor: Mapped[int | None] = mapped_column(BigInteger)
    stopping_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
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
