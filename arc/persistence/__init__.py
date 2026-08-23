"""Explicit persistence operations for ARC domain records."""

from arc.persistence.case_events import append_case_event
from arc.persistence.merchant_policies import create_merchant_policy
from arc.persistence.payment_cases import (
    CasePersistenceError,
    GetOrCreateCaseResult,
    create_payment_case,
    deterministic_case_reference,
    get_or_create_case,
    lock_case_by_identity,
)
from arc.persistence.webhook_events import (
    EventPersistenceError,
    RecordEventResult,
    hash_payload,
    record_event_once,
)

__all__ = [
    "RecordEventResult",
    "EventPersistenceError",
    "CasePersistenceError",
    "GetOrCreateCaseResult",
    "append_case_event",
    "create_merchant_policy",
    "create_payment_case",
    "deterministic_case_reference",
    "get_or_create_case",
    "hash_payload",
    "lock_case_by_identity",
    "record_event_once",
]
