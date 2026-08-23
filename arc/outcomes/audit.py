"""Bounded outcome and attribution audit events without provider payloads."""

from sqlalchemy.orm import Session

from arc.domain.models import (
    CaseEvent,
    RecoveryAttribution,
    RecoveryActionRecord,
    RecoveryOutcomeObservation,
)

OUTCOME_AUDIT_SOURCE = "RECOVERY_OBSERVER"


def append_outcome_audit(
    session: Session,
    observation: RecoveryOutcomeObservation,
    event_type: str,
    *,
    reason_code: str,
    attribution: RecoveryAttribution | None = None,
) -> None:
    """Append one sanitized fact containing no URL, PII, or raw response."""

    action = session.get(RecoveryActionRecord, observation.recovery_action_id)
    session.add(
        CaseEvent(
            case_id=observation.case_id,
            event_type=event_type,
            source=OUTCOME_AUDIT_SOURCE,
            event_data={
                "recovery_action_id": str(observation.recovery_action_id),
                "observation_id": str(observation.id),
                "attribution_id": (
                    str(attribution.id) if attribution is not None else None
                ),
                "provider": observation.provider,
                "provider_mode": observation.provider_mode.value,
                "provider_status": observation.provider_status,
                "provider_entity_id": (
                    action.external_reference_id if action is not None else None
                ),
                "provider_reference_id": (
                    action.external_reference if action is not None else None
                ),
                "provider_payment_id": observation.provider_payment_id,
                "expected_amount_minor": observation.amount_expected_minor,
                "amount_paid_minor": observation.amount_paid_minor,
                "recovered_amount_minor": (
                    attribution.recovered_amount_minor
                    if attribution is not None
                    else None
                ),
                "currency": observation.currency,
                "outcome_status": observation.outcome_status.value,
                "evidence_fingerprint": observation.evidence_fingerprint,
                "source": observation.source.value,
                "reason_code": reason_code,
            },
        )
    )
