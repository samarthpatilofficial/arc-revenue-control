"""Authoritative external-state reconciliation for ARC cases."""

from arc.reconciliation.errors import (
    WebhookEventNotFoundError,
    WebhookProcessingError,
)
from arc.reconciliation.service import (
    WebhookEventProcessor,
    WebhookProcessingResult,
    process_webhook_event,
)
from arc.reconciliation.state_machine import (
    TERMINAL_CASE_STATES,
    CaseTransitionResult,
    InvalidCaseTransition,
    can_transition,
    transition_case,
)

__all__ = [
    "TERMINAL_CASE_STATES",
    "CaseTransitionResult",
    "InvalidCaseTransition",
    "WebhookEventNotFoundError",
    "WebhookEventProcessor",
    "WebhookProcessingError",
    "WebhookProcessingResult",
    "can_transition",
    "process_webhook_event",
    "transition_case",
]
