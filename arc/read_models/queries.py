"""Read-only SQLAlchemy projections that never return persistence entities."""

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import TypeVar

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, selectinload

from arc.demo.markers import (
    DEMO_EVENT_SOURCE,
    DEMO_EVENT_TYPE,
    OFFLINE_DEMO_STRATEGY_MODEL,
    OPENAI_EVIDENCE_EVENT_SOURCE,
    OPENAI_EVIDENCE_EVENT_TYPE,
)
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    EligibilityDecision,
    FailureCategory,
    PolicyDecisionResult,
    ProviderMode,
    RecoveryExecutionStatus,
    RecoveryDisposition,
    RecoveryOutcomeStatus,
    StrategySource,
)
from arc.domain.models import (
    ApprovalRequest,
    CaseEvent,
    PaymentCase,
    PolicyDecision,
    RecoveryActionRecord,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
    StrategyProposal,
)
from arc.read_models.schemas import (
    ApprovalProjection,
    ApprovalQueueItem,
    AttributionProjection,
    CaseDetail,
    CaseListItem,
    CaseProjection,
    DataOrigin,
    DiagnosisProjection,
    ExecutionProjection,
    OutcomeProjection,
    PolicyProjection,
    RecoveryActionItem,
    ResolutionKind,
    StrategyProjection,
    StrategyProvenance,
    TimelineItem,
)

T = TypeVar("T")

_CASE_OPTIONS = (
    selectinload(PaymentCase.case_events),
    selectinload(PaymentCase.strategy_proposals),
    selectinload(PaymentCase.policy_decisions),
    selectinload(PaymentCase.approval_requests),
    selectinload(PaymentCase.recovery_actions),
    selectinload(PaymentCase.outcome_observations),
    selectinload(PaymentCase.attributions),
)


def list_case_summaries(
    session: Session,
    *,
    state: CaseState | None,
    failure_category: FailureCategory | None,
    provider_mode: ProviderMode | None,
    limit: int,
    offset: int,
) -> list[CaseListItem]:
    """Return bounded case projections with only current display-safe facts."""

    statement = select(PaymentCase).options(*_CASE_OPTIONS)
    if state is not None:
        statement = statement.where(PaymentCase.current_state == state)
    if failure_category is not None:
        statement = statement.where(
            PaymentCase.failure_category == failure_category
        )
    if provider_mode is not None:
        statement = statement.where(
            exists(
                select(RecoveryOutcomeObservation.id).where(
                    RecoveryOutcomeObservation.case_id == PaymentCase.id,
                    RecoveryOutcomeObservation.provider_mode == provider_mode,
                )
            )
        )
    statement = statement.order_by(
        PaymentCase.detected_at.desc(),
        PaymentCase.case_reference,
    ).limit(limit).offset(offset)
    return [_case_list_item(item) for item in session.scalars(statement)]


def get_case_detail(
    session: Session,
    case_reference: str,
) -> CaseDetail | None:
    """Return one aggregate sanitized projection by public case reference."""

    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.case_reference == case_reference)
        .options(*_CASE_OPTIONS)
    )
    if payment_case is None:
        return None
    proposal = _current(payment_case.strategy_proposals, "superseded_at")
    decision = _current(payment_case.policy_decisions, "superseded_at")
    approval = _approval_for_decision(payment_case, decision)
    action = _latest(payment_case.recovery_actions, "created_at")
    outcome = _latest(payment_case.outcome_observations, "observed_at")
    attribution = _latest(payment_case.attributions, "attributed_at")
    origin = _data_origin(payment_case, outcome, attribution)
    resolution = _resolution_kind(
        payment_case,
        action=action,
        attribution=attribution,
        decision=decision,
    )
    return CaseDetail(
        data_origin=origin,
        case=CaseProjection(
            case_reference=payment_case.case_reference,
            amount_minor=payment_case.amount,
            currency=payment_case.currency,
            current_state=payment_case.current_state,
            resolution_kind=resolution,
            payment_method=payment_case.razorpay_payment_method,
            attempt_count=payment_case.attempt_count,
            contact_attempt_count=payment_case.contact_attempt_count,
            detected_at=payment_case.detected_at,
            resolved_at=payment_case.resolved_at,
        ),
        diagnosis=DiagnosisProjection(
            eligibility_status=payment_case.eligibility_status,
            eligibility_reason_code=payment_case.eligibility_reason_code,
            failure_category=payment_case.failure_category,
            recovery_disposition=payment_case.recovery_disposition,
            diagnosis_reason_code=payment_case.diagnosis_reason_code,
            diagnosed_at=payment_case.diagnosed_at,
        ),
        strategy=_strategy_projection(proposal),
        policy=_policy_projection(decision),
        approval=_approval_projection(approval),
        execution=_execution_projection(action),
        outcome=_outcome_projection(outcome),
        attribution=_attribution_projection(attribution),
    )


def get_case_timeline(
    session: Session,
    case_reference: str,
) -> list[TimelineItem] | None:
    """Normalize persisted audit and domain rows into a chronological trace."""

    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.case_reference == case_reference)
        .options(*_CASE_OPTIONS)
    )
    if payment_case is None:
        return None
    outcome = _latest(payment_case.outcome_observations, "observed_at")
    attribution = _latest(payment_case.attributions, "attributed_at")
    origin = _data_origin(payment_case, outcome, attribution)
    ordered: list[tuple[datetime, int, TimelineItem]] = []
    sequence = 0

    def add(timestamp: datetime, item: TimelineItem) -> None:
        nonlocal sequence
        ordered.append((timestamp, sequence, item))
        sequence += 1

    mapped_detection = False
    for event in payment_case.case_events:
        normalized = _timeline_from_case_event(event, origin)
        if normalized is None:
            continue
        mapped_detection = mapped_detection or event.event_type == "CASE_DETECTED"
        add(event.created_at, normalized)
    if not mapped_detection:
        add(
            payment_case.detected_at,
            TimelineItem(
                stage="DETECTED",
                title="Revenue risk detected",
                status="complete",
                timestamp=payment_case.detected_at,
                authority="ARC_CONTROL_PLANE",
                data_origin=origin,
            ),
        )

    for proposal in payment_case.strategy_proposals:
        provenance = _strategy_provenance(proposal)
        add(
            proposal.created_at,
            TimelineItem(
                stage="STRATEGY",
                title="Recovery strategy proposed",
                status="complete",
                timestamp=proposal.created_at,
                detail=proposal.reason_code,
                action=proposal.action,
                authority=provenance.value,
                strategy_provenance=provenance,
                strategy_model=_safe_strategy_model(proposal),
                data_origin=origin,
            ),
        )
    for decision in payment_case.policy_decisions:
        add(
            decision.evaluated_at,
            TimelineItem(
                stage="POLICY",
                title="Merchant policy evaluated",
                status=(
                    "blocked"
                    if decision.result is PolicyDecisionResult.BLOCKED
                    else "complete"
                ),
                timestamp=decision.evaluated_at,
                detail=decision.reason_code,
                authority="DETERMINISTIC_POLICY",
                result=decision.result.value,
                data_origin=origin,
            ),
        )
    for approval in payment_case.approval_requests:
        add(
            approval.requested_at,
            TimelineItem(
                stage="APPROVAL",
                title="Human approval requested",
                status="pending",
                timestamp=approval.requested_at,
                authority="HUMAN_APPROVAL",
                result="PENDING",
                data_origin=origin,
            ),
        )
        if approval.decided_at is not None:
            add(
                approval.decided_at,
                TimelineItem(
                    stage="APPROVAL",
                    title="Human approval decided",
                    status=(
                        "blocked"
                        if approval.status is ApprovalStatus.REJECTED
                        else "complete"
                    ),
                    timestamp=approval.decided_at,
                    authority="HUMAN_APPROVAL",
                    result=approval.status.value,
                    data_origin=origin,
                ),
            )
    for action in payment_case.recovery_actions:
        action_timestamp = action.executed_at or action.created_at
        add(
            action_timestamp,
            TimelineItem(
                stage="EXECUTION",
                title="Governed recovery action recorded",
                status=_execution_timeline_status(action.execution_status),
                timestamp=action_timestamp,
                detail=action.external_status,
                action=action.action,
                authority="GOVERNED_EXECUTOR",
                result=action.execution_status.value,
                data_origin=origin,
            ),
        )
    for observation in payment_case.outcome_observations:
        add(
            observation.observed_at,
            TimelineItem(
                stage="OUTCOME",
                title="Authoritative recovery outcome observed",
                status=_outcome_timeline_status(observation.outcome_status),
                timestamp=observation.observed_at,
                detail=observation.provider_status,
                authority="AUTHORITATIVE_PROVIDER_EVIDENCE",
                result=observation.outcome_status.value,
                amount_minor=observation.amount_paid_minor,
                currency=observation.currency,
                provider_mode=observation.provider_mode,
                data_origin=origin,
            ),
        )
    for item in payment_case.attributions:
        add(
            item.attributed_at,
            TimelineItem(
                stage="ATTRIBUTION",
                title="Revenue recovered",
                status="complete",
                timestamp=item.attributed_at,
                detail=item.attribution_reason_code,
                authority="EVIDENCE_BACKED_ATTRIBUTION",
                result="ATTRIBUTED",
                amount_minor=item.recovered_amount_minor,
                currency=item.currency,
                provider_mode=item.provider_mode,
                data_origin=origin,
            ),
        )
    ordered.sort(
        key=lambda entry: (
            entry[0],
            _TIMELINE_STAGE_ORDER.get(entry[2].stage, 99),
            entry[1],
        )
    )
    return [entry[2] for entry in ordered]


def list_approval_queue(
    session: Session,
    *,
    status: ApprovalStatus,
    limit: int,
    offset: int,
) -> list[ApprovalQueueItem]:
    """Return decision-scoped approval requests without operator or PII data."""

    rows = session.execute(
        select(ApprovalRequest, PaymentCase, PolicyDecision, StrategyProposal)
        .join(PaymentCase, PaymentCase.id == ApprovalRequest.case_id)
        .join(
            PolicyDecision,
            PolicyDecision.id == ApprovalRequest.policy_decision_id,
        )
        .join(
            StrategyProposal,
            StrategyProposal.id == PolicyDecision.strategy_proposal_id,
        )
        .where(ApprovalRequest.status == status)
        .order_by(ApprovalRequest.requested_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items: list[ApprovalQueueItem] = []
    for approval, payment_case, decision, proposal in rows:
        origin = _origin_for_case_id(session, payment_case.id)
        items.append(
            ApprovalQueueItem(
                approval_request_id=approval.id,
                case_reference=payment_case.case_reference,
                amount_minor=payment_case.amount,
                currency=payment_case.currency,
                strategy_action=proposal.action,
                strategy_provenance=_strategy_provenance(proposal),
                policy_reason_code=decision.reason_code,
                approval_status=approval.status,
                requested_at=approval.requested_at,
                decided_at=approval.decided_at,
                data_origin=origin,
            )
        )
    return items


def list_recovery_actions(
    session: Session,
    *,
    limit: int,
    offset: int,
) -> list[RecoveryActionItem]:
    """Return governed execution projections without keys, URLs, or identifiers."""

    rows = session.execute(
        select(RecoveryActionRecord, PaymentCase)
        .join(PaymentCase, PaymentCase.id == RecoveryActionRecord.case_id)
        .options(selectinload(RecoveryActionRecord.outcome_observations))
        .options(selectinload(RecoveryActionRecord.strategy_proposal))
        .order_by(RecoveryActionRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items: list[RecoveryActionItem] = []
    for action, payment_case in rows:
        outcome = _latest(action.outcome_observations, "observed_at")
        origin = _origin_for_case_id(
            session,
            payment_case.id,
            provider_mode=(outcome.provider_mode if outcome else None),
        )
        items.append(
            RecoveryActionItem(
                case_reference=payment_case.case_reference,
                action=action.action,
                strategy_provenance=_strategy_provenance(
                    action.strategy_proposal
                ),
                execution_status=action.execution_status,
                provider=action.provider,
                external_status=action.external_status,
                execution_attempt_count=action.execution_attempt_count,
                executed_at=action.executed_at,
                next_evaluation_at=action.next_evaluation_at,
                outcome_status=(outcome.outcome_status if outcome else None),
                provider_mode=(outcome.provider_mode if outcome else None),
                data_origin=origin,
            )
        )
    return items


def _case_list_item(payment_case: PaymentCase) -> CaseListItem:
    proposal = _current(payment_case.strategy_proposals, "superseded_at")
    decision = _current(payment_case.policy_decisions, "superseded_at")
    approval = _approval_for_decision(payment_case, decision)
    action = _latest(payment_case.recovery_actions, "created_at")
    outcome = _latest(payment_case.outcome_observations, "observed_at")
    attribution = _latest(payment_case.attributions, "attributed_at")
    resolution = _resolution_kind(
        payment_case,
        action=action,
        attribution=attribution,
        decision=decision,
    )
    return CaseListItem(
        case_reference=payment_case.case_reference,
        amount_minor=payment_case.amount,
        currency=payment_case.currency,
        current_state=payment_case.current_state,
        resolution_kind=resolution,
        payment_method=payment_case.razorpay_payment_method,
        failure_category=payment_case.failure_category,
        recovery_disposition=payment_case.recovery_disposition,
        eligibility_status=payment_case.eligibility_status,
        detected_at=payment_case.detected_at,
        resolved_at=payment_case.resolved_at,
        strategy_action=(proposal.action if proposal else None),
        strategy_provenance=_strategy_provenance(proposal),
        policy_result=(decision.result if decision else None),
        approval_status=(approval.status if approval else None),
        recovery_execution_status=(
            action.execution_status if action else None
        ),
        outcome_status=(outcome.outcome_status if outcome else None),
        recovered_amount_minor=(
            attribution.recovered_amount_minor if attribution else None
        ),
        provider_mode=(
            attribution.provider_mode
            if attribution
            else outcome.provider_mode
            if outcome
            else None
        ),
        data_origin=_data_origin(payment_case, outcome, attribution),
    )


def _strategy_projection(
    proposal: StrategyProposal | None,
) -> StrategyProjection | None:
    if proposal is None:
        return None
    return StrategyProjection(
        action=proposal.action,
        source=proposal.source,
        provenance=_strategy_provenance(proposal),
        model=_safe_strategy_model(proposal),
        reason_code=proposal.reason_code,
        explanation=proposal.explanation,
        confidence=proposal.confidence,
        confidence_authority=(
            "MODEL_OBSERVABILITY_ONLY"
            if proposal.source is StrategySource.AI
            else None
        ),
        created_at=proposal.created_at,
    )


def _policy_projection(
    decision: PolicyDecision | None,
) -> PolicyProjection | None:
    if decision is None:
        return None
    return PolicyProjection(
        result=decision.result,
        reason_code=decision.reason_code,
        explanation=decision.explanation,
        approval_threshold_minor=decision.approval_threshold_minor,
        evaluated_at=decision.evaluated_at,
    )


def _approval_projection(
    approval: ApprovalRequest | None,
) -> ApprovalProjection | None:
    if approval is None:
        return None
    return ApprovalProjection(
        approval_request_id=approval.id,
        approval_status=approval.status,
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
    )


def _execution_projection(
    action: RecoveryActionRecord | None,
) -> ExecutionProjection | None:
    if action is None:
        return None
    return ExecutionProjection(
        action=action.action,
        execution_status=action.execution_status,
        provider=action.provider,
        external_status=action.external_status,
        execution_attempt_count=action.execution_attempt_count,
        executed_at=action.executed_at,
        next_evaluation_at=action.next_evaluation_at,
    )


def _outcome_projection(
    outcome: RecoveryOutcomeObservation | None,
) -> OutcomeProjection | None:
    if outcome is None:
        return None
    return OutcomeProjection(
        outcome_status=outcome.outcome_status,
        provider_mode=outcome.provider_mode,
        provider_status=outcome.provider_status,
        amount_expected_minor=outcome.amount_expected_minor,
        amount_paid_minor=outcome.amount_paid_minor,
        currency=outcome.currency,
        observed_at=outcome.observed_at,
    )


def _attribution_projection(
    attribution: RecoveryAttribution | None,
) -> AttributionProjection | None:
    if attribution is None:
        return None
    return AttributionProjection(
        provider_mode=attribution.provider_mode,
        recovered_amount_minor=attribution.recovered_amount_minor,
        currency=attribution.currency,
        reason_code=attribution.attribution_reason_code,
        attributed_at=attribution.attributed_at,
    )


def _approval_for_decision(
    payment_case: PaymentCase,
    decision: PolicyDecision | None,
) -> ApprovalRequest | None:
    if decision is None:
        return None
    return next(
        (
            item
            for item in reversed(payment_case.approval_requests)
            if item.policy_decision_id == decision.id
        ),
        None,
    )


def _current(items: Iterable[T], attribute: str) -> T | None:
    return next(
        (item for item in reversed(list(items)) if getattr(item, attribute) is None),
        None,
    )


def _latest(items: Iterable[T], attribute: str) -> T | None:
    values = list(items)
    if not values:
        return None
    return max(
        values,
        key=lambda item: (
            getattr(item, attribute),
            getattr(item, "created_at", getattr(item, attribute)),
        ),
    )


def _is_synthetic(payment_case: PaymentCase) -> bool:
    return any(
        event.event_type == DEMO_EVENT_TYPE and event.source == DEMO_EVENT_SOURCE
        for event in payment_case.case_events
    )


def _is_synthetic_input(payment_case: PaymentCase) -> bool:
    return any(
        event.event_type == OPENAI_EVIDENCE_EVENT_TYPE
        and event.source == OPENAI_EVIDENCE_EVENT_SOURCE
        for event in payment_case.case_events
    )


def _data_origin(
    payment_case: PaymentCase,
    outcome: RecoveryOutcomeObservation | None,
    attribution: RecoveryAttribution | None,
) -> DataOrigin | None:
    if _is_synthetic_input(payment_case):
        return DataOrigin.SYNTHETIC_INPUT
    if _is_synthetic(payment_case):
        return DataOrigin.SYNTHETIC_DEMO
    mode = (
        attribution.provider_mode
        if attribution is not None
        else outcome.provider_mode
        if outcome is not None
        else None
    )
    return _origin_from_mode(mode)


def _origin_for_case_id(
    session: Session,
    case_id: object,
    *,
    provider_mode: ProviderMode | None = None,
) -> DataOrigin | None:
    synthetic = session.scalar(
        select(
            exists().where(
                CaseEvent.case_id == case_id,
                CaseEvent.event_type == DEMO_EVENT_TYPE,
                CaseEvent.source == DEMO_EVENT_SOURCE,
            )
        )
    )
    if synthetic:
        return DataOrigin.SYNTHETIC_DEMO
    synthetic_input = session.scalar(
        select(
            exists().where(
                CaseEvent.case_id == case_id,
                CaseEvent.event_type == OPENAI_EVIDENCE_EVENT_TYPE,
                CaseEvent.source == OPENAI_EVIDENCE_EVENT_SOURCE,
            )
        )
    )
    if synthetic_input:
        return DataOrigin.SYNTHETIC_INPUT
    return _origin_from_mode(provider_mode)


def _strategy_provenance(
    proposal: StrategyProposal | None,
) -> StrategyProvenance:
    if proposal is None:
        return StrategyProvenance.BYPASSED
    if proposal.source is StrategySource.RULE:
        return StrategyProvenance.DETERMINISTIC_RULE
    if proposal.model == OFFLINE_DEMO_STRATEGY_MODEL:
        return StrategyProvenance.OFFLINE_SIMULATION
    return StrategyProvenance.OPENAI


def _safe_strategy_model(proposal: StrategyProposal) -> str | None:
    model = proposal.model
    if proposal.source is StrategySource.RULE or model is None:
        return None
    normalized = model.strip()
    if _STRATEGY_MODEL_NAME.fullmatch(normalized) is None:
        return None
    return normalized


def _resolution_kind(
    payment_case: PaymentCase,
    *,
    action: RecoveryActionRecord | None,
    attribution: RecoveryAttribution | None,
    decision: PolicyDecision | None,
) -> ResolutionKind:
    if attribution is not None:
        return ResolutionKind.ARC_RECOVERED
    already_captured = any(
        event.event_type == "RECONCILIATION_FOUND_ALREADY_CAPTURED"
        for event in payment_case.case_events
    )
    if (
        already_captured
        and action is None
        and payment_case.current_state is CaseState.RECOVERED
    ):
        return ResolutionKind.ALREADY_CAPTURED
    if payment_case.current_state is CaseState.EXHAUSTED:
        return ResolutionKind.EXHAUSTED
    if payment_case.current_state is CaseState.ESCALATED:
        return ResolutionKind.ESCALATED
    if (
        decision is not None
        and decision.result is PolicyDecisionResult.REQUIRES_APPROVAL
    ):
        return ResolutionKind.REQUIRES_APPROVAL
    if payment_case.current_state is CaseState.WAITING_FOR_OUTCOME:
        return ResolutionKind.AWAITING_OUTCOME
    return ResolutionKind.PENDING


def _origin_from_mode(mode: ProviderMode | None) -> DataOrigin | None:
    if mode is ProviderMode.TEST:
        return DataOrigin.TEST_MODE
    if mode is ProviderMode.LIVE:
        return DataOrigin.LIVE_MODE
    return None


_RECONCILIATION_TIMELINE: dict[str, tuple[str, str]] = {
    "RECONCILIATION_CONFIRMED_FAILURE": (
        "Razorpay state reconciled",
        "Payment confirmed failed",
    ),
    "RECONCILIATION_FOUND_ALREADY_CAPTURED": (
        "Razorpay state reconciled",
        "Payment confirmed captured",
    ),
    "PAYMENT_CAPTURE_SIGNAL_NOT_CONFIRMED": (
        "Razorpay state reconciled",
        "Capture signal was not confirmed",
    ),
    "PAYMENT_STATE_NOT_RECOVERY_READY": (
        "Razorpay state reconciled",
        "Payment is not recovery-ready",
    ),
    "PAYMENT_REFUNDED": (
        "Razorpay state reconciled",
        "Payment was refunded",
    ),
}

_TIMELINE_STAGE_ORDER = {
    "DEMO": 0,
    "DETECTED": 1,
    "RECONCILED": 2,
    "ELIGIBILITY": 3,
    "DIAGNOSED": 4,
    "STRATEGY": 5,
    "POLICY": 6,
    "APPROVAL": 7,
    "EXECUTION": 8,
    "OUTCOME": 9,
    "ATTRIBUTION": 10,
}

_ELIGIBILITY_TIMELINE_VALUES = frozenset(
    decision.value for decision in EligibilityDecision
)
_FAILURE_CATEGORY_TIMELINE_VALUES = frozenset(
    category.value for category in FailureCategory
)
_RECOVERY_DISPOSITION_TIMELINE_VALUES = frozenset(
    disposition.value for disposition in RecoveryDisposition
)
_TIMELINE_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,99}")
_STRATEGY_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")


def _bounded_event_value(
    event_data: Mapping[str, object],
    key: str,
    allowed_values: frozenset[str],
) -> str | None:
    value = event_data.get(key)
    if not isinstance(value, str) or value not in allowed_values:
        return None
    return value


def _bounded_event_reason(
    event_data: Mapping[str, object],
    key: str,
) -> str | None:
    value = event_data.get(key)
    if (
        not isinstance(value, str)
        or _TIMELINE_REASON_CODE.fullmatch(value) is None
    ):
        return None
    return value


def _timeline_from_case_event(
    event: CaseEvent,
    origin: DataOrigin | None,
) -> TimelineItem | None:
    if (
        event.event_type == OPENAI_EVIDENCE_EVENT_TYPE
        and event.source == OPENAI_EVIDENCE_EVENT_SOURCE
    ):
        return TimelineItem(
            stage="DEMO",
            title="Synthetic input case created",
            status="complete",
            timestamp=event.created_at,
            detail="No provider payment or customer interaction",
            authority="CONTROLLED_SYNTHETIC_INPUT",
            data_origin=DataOrigin.SYNTHETIC_INPUT,
        )
    if event.event_type == DEMO_EVENT_TYPE and event.source == DEMO_EVENT_SOURCE:
        return TimelineItem(
            stage="DEMO",
            title="Synthetic demo scenario seeded",
            status="complete",
            timestamp=event.created_at,
            detail="Controlled offline scenario",
            authority="CONTROLLED_SIMULATION",
            data_origin=DataOrigin.SYNTHETIC_DEMO,
        )
    if event.event_type == "CASE_DETECTED":
        return TimelineItem(
            stage="DETECTED",
            title="Revenue risk detected",
            status="complete",
            timestamp=event.created_at,
            authority="ARC_CONTROL_PLANE",
            data_origin=origin,
        )
    if (
        origin is DataOrigin.SYNTHETIC_INPUT
        and event.event_type == "RECONCILIATION_CONFIRMED_FAILURE"
    ):
        return TimelineItem(
            stage="RECONCILED",
            title="Synthetic case truth established",
            status="complete",
            timestamp=event.created_at,
            detail="Controlled failed-payment input",
            authority="CONTROLLED_SYNTHETIC_INPUT",
            data_origin=origin,
        )
    reconciliation = _RECONCILIATION_TIMELINE.get(event.event_type)
    if reconciliation is not None:
        title, detail = reconciliation
        return TimelineItem(
            stage="RECONCILED",
            title=title,
            status="complete",
            timestamp=event.created_at,
            detail=detail,
            authority="AUTHORITATIVE_RECONCILIATION",
            data_origin=origin,
        )
    if event.event_type == "ELIGIBILITY_EVALUATED":
        decision = _bounded_event_value(
            event.event_data,
            "eligibility_decision",
            _ELIGIBILITY_TIMELINE_VALUES,
        )
        reason = _bounded_event_reason(
            event.event_data,
            "eligibility_reason",
        )
        return TimelineItem(
            stage="ELIGIBILITY",
            title="Recovery eligibility evaluated",
            status="complete",
            timestamp=event.created_at,
            detail=reason or "Historical eligibility detail unavailable",
            authority="DETERMINISTIC_PRECONDITIONS",
            result=decision,
            data_origin=origin,
        )
    if event.event_type in {"FAILURE_DIAGNOSED", "FAILURE_REDIAGNOSED"}:
        category = _bounded_event_value(
            event.event_data,
            "failure_category",
            _FAILURE_CATEGORY_TIMELINE_VALUES,
        )
        disposition = _bounded_event_value(
            event.event_data,
            "recovery_disposition",
            _RECOVERY_DISPOSITION_TIMELINE_VALUES,
        )
        reason = _bounded_event_reason(
            event.event_data,
            "diagnosis_reason",
        )
        detail = " / ".join(
            value for value in (category, disposition) if value is not None
        )
        return TimelineItem(
            stage="DIAGNOSED",
            title="Failure diagnosed",
            status="complete",
            timestamp=event.created_at,
            detail=detail or "Historical diagnosis detail unavailable",
            authority="DETERMINISTIC_DIAGNOSIS",
            result=reason,
            data_origin=origin,
        )
    return None


def _execution_timeline_status(
    status: RecoveryExecutionStatus,
) -> str:
    if status in {
        RecoveryExecutionStatus.PREPARED,
        RecoveryExecutionStatus.IN_PROGRESS,
    }:
        return "pending"
    if status in {
        RecoveryExecutionStatus.FAILED,
        RecoveryExecutionStatus.INDETERMINATE,
        RecoveryExecutionStatus.COMPENSATION_REQUIRED,
    }:
        return "blocked"
    return "complete"


def _outcome_timeline_status(status: RecoveryOutcomeStatus) -> str:
    if status is RecoveryOutcomeStatus.PENDING:
        return "pending"
    if status is RecoveryOutcomeStatus.REVIEW_REQUIRED:
        return "blocked"
    return "complete"
