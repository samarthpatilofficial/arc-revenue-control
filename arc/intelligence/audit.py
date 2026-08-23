"""Bounded strategy audit events without prompts, raw output, or secrets."""

from sqlalchemy.orm import Session

from arc.domain.enums import CaseState, RecoveryAction, StrategySource
from arc.domain.models import CaseEvent, PaymentCase, StrategyProposal
from arc.intelligence.prompt import STRATEGY_PROMPT_VERSION

STRATEGY_AUDIT_SOURCE = "STRATEGY_ENGINE"
STRATEGY_INCOMPATIBLE_REASON = "STRATEGY_INCOMPATIBLE_WITH_DIAGNOSIS"


def append_generation_failure(
    session: Session,
    payment_case: PaymentCase,
    *,
    assessment_fingerprint: str,
    strategy_input_fingerprint: str,
    model: str | None,
    failure_reason_code: str,
) -> None:
    """Append one sanitized provider/configuration failure."""

    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type="STRATEGY_GENERATION_FAILED",
            source=STRATEGY_AUDIT_SOURCE,
            event_data={
                "reason_code": failure_reason_code,
                "assessment_fingerprint": assessment_fingerprint,
                "strategy_input_fingerprint": strategy_input_fingerprint,
                "model": model,
                "prompt_version": STRATEGY_PROMPT_VERSION,
                "case_state": payment_case.current_state.value,
            },
        )
    )


def append_generated(
    session: Session,
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    *,
    previous_state: CaseState,
) -> None:
    """Append one accepted initial or regenerated proposal audit event."""

    if previous_state is CaseState.DECISIONED:
        event_type = "STRATEGY_REGENERATED"
    elif proposal.source is StrategySource.RULE:
        event_type = "STRATEGY_RULE_GENERATED"
    else:
        event_type = "STRATEGY_GENERATED"
    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type=event_type,
            source=STRATEGY_AUDIT_SOURCE,
            event_data=_proposal_audit_data(
                proposal,
                previous_state=previous_state,
                new_state=payment_case.current_state,
            ),
        )
    )


def append_rejected(
    session: Session,
    payment_case: PaymentCase,
    *,
    assessment_fingerprint: str,
    strategy_input_fingerprint: str,
    source: StrategySource,
    action: RecoveryAction,
    model: str | None,
) -> None:
    """Append one deterministic compatibility rejection."""

    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type="STRATEGY_PROPOSAL_REJECTED",
            source=STRATEGY_AUDIT_SOURCE,
            event_data={
                "reason_code": STRATEGY_INCOMPATIBLE_REASON,
                "source": source.value,
                "action": action.value,
                "assessment_fingerprint": assessment_fingerprint,
                "strategy_input_fingerprint": strategy_input_fingerprint,
                "model": model,
                "prompt_version": STRATEGY_PROMPT_VERSION,
                "case_state": payment_case.current_state.value,
            },
        )
    )


def append_stale_context(
    session: Session,
    payment_case: PaymentCase,
    *,
    assessment_fingerprint: str,
    strategy_input_fingerprint: str,
    source: StrategySource,
    action: RecoveryAction | None,
    model: str | None,
) -> None:
    """Record that an otherwise bounded proposal lost its context fence."""

    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type="STRATEGY_DISCARDED_STALE_CONTEXT",
            source=STRATEGY_AUDIT_SOURCE,
            event_data={
                "reason_code": "STRATEGY_DISCARDED_STALE_CONTEXT",
                "source": source.value,
                "action": action.value if action is not None else None,
                "assessment_fingerprint": assessment_fingerprint,
                "strategy_input_fingerprint": strategy_input_fingerprint,
                "model": model,
                "prompt_version": STRATEGY_PROMPT_VERSION,
                "case_state": payment_case.current_state.value,
            },
        )
    )


def _proposal_audit_data(
    proposal: StrategyProposal,
    *,
    previous_state: CaseState,
    new_state: CaseState,
) -> dict[str, object]:
    return {
        "proposal_id": str(proposal.id),
        "source": proposal.source.value,
        "action": proposal.action.value,
        "reason_code": proposal.reason_code,
        "assessment_fingerprint": proposal.assessment_fingerprint,
        "strategy_input_fingerprint": proposal.strategy_input_fingerprint,
        "model": proposal.model,
        "prompt_version": proposal.prompt_version,
        "confidence": proposal.confidence,
        "latency_ms": proposal.latency_ms,
        "input_tokens": proposal.input_tokens,
        "output_tokens": proposal.output_tokens,
        "total_tokens": proposal.total_tokens,
        "previous_state": previous_state.value,
        "new_state": new_state.value,
    }
