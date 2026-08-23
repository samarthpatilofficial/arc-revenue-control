"""Append-only persistence operations for internal case events."""

from sqlalchemy.orm import Session

from arc.domain.models import CaseEvent


def append_case_event(session: Session, case_event: CaseEvent) -> CaseEvent:
    """Append one audit event inside the caller's transaction."""

    session.add(case_event)
    session.flush()
    return case_event
