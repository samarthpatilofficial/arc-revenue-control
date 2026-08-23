"""Bounded recovery execution audit events without provider payloads."""

from typing import Any

from sqlalchemy.orm import Session

from arc.domain.models import CaseEvent, RecoveryActionRecord

EXECUTION_AUDIT_SOURCE = "RECOVERY_EXECUTOR"


def append_execution_audit(
    session: Session,
    record: RecoveryActionRecord,
    event_type: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one sanitized ledger lifecycle event."""

    event_data: dict[str, Any] = {
        "recovery_action_id": str(record.id),
        "policy_decision_id": str(record.policy_decision_id),
        "strategy_proposal_id": str(record.strategy_proposal_id),
        "approval_request_id": (
            str(record.approval_request_id)
            if record.approval_request_id is not None
            else None
        ),
        "action": record.action.value,
        "execution_status": record.execution_status.value,
        "provider": record.provider,
        "reference_id": record.external_reference,
        "provider_entity_id": record.external_reference_id,
        "provider_status": record.external_status,
        "attempt_count": record.execution_attempt_count,
    }
    event_data.update(metadata or {})
    session.add(
        CaseEvent(
            case_id=record.case_id,
            event_type=event_type,
            source=EXECUTION_AUDIT_SOURCE,
            event_data=event_data,
        )
    )
