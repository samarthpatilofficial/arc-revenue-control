"""Append-only internal payment case audit event model."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from arc.db.base import Base

if TYPE_CHECKING:
    from arc.domain.models.payment_case import PaymentCase


class CaseEvent(Base):
    """One append-only entry in a payment case's internal timeline."""

    __tablename__ = "case_events"
    __table_args__ = (
        Index("ix_case_events_case_id_created_at", "case_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    event_data: Mapped[dict[str, Any]] = mapped_column(
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

    case: Mapped["PaymentCase"] = relationship(back_populates="case_events")


@event.listens_for(CaseEvent, "before_update")
def _prevent_case_event_update(
    _mapper: Mapper[CaseEvent],
    _connection: Connection,
    _target: CaseEvent,
) -> None:
    raise ValueError("Case audit events are append-only and cannot be updated")


@event.listens_for(CaseEvent, "before_delete")
def _prevent_case_event_delete(
    _mapper: Mapper[CaseEvent],
    _connection: Connection,
    _target: CaseEvent,
) -> None:
    raise ValueError("Case audit events are append-only and cannot be deleted")
