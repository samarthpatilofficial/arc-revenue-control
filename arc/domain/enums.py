"""Stable controlled values used by ARC persistence models.

These enums are stored as strings with database CHECK constraints instead of
native PostgreSQL enum types. This keeps values explicit while allowing safer
schema evolution and portable SQLAlchemy metadata.
"""

from enum import StrEnum


class CaseState(StrEnum):
    """Lifecycle states for a reconciled ARC payment case."""

    DETECTED = "DETECTED"
    RECONCILING = "RECONCILING"
    DIAGNOSED = "DIAGNOSED"
    DECISIONED = "DECISIONED"
    POLICY_VALIDATED = "POLICY_VALIDATED"
    ACTIONED = "ACTIONED"
    WAITING_FOR_OUTCOME = "WAITING_FOR_OUTCOME"
    RECOVERED = "RECOVERED"
    EXHAUSTED = "EXHAUSTED"
    ESCALATED = "ESCALATED"


class EventProcessingStatus(StrEnum):
    """Operational processing states for an immutable webhook event."""

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
