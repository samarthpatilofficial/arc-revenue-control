"""Explicit safe workflow for one genuine OpenAI strategy evidence case."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arc.approval import HumanApprovalService
from arc.assessment import CaseAssessmentService
from arc.config import Settings, get_settings
from arc.db.session import get_session_factory
from arc.demo.markers import (
    OFFLINE_DEMO_STRATEGY_MODEL,
    OPENAI_EVIDENCE_CASE_REFERENCE,
    OPENAI_EVIDENCE_EVENT_SOURCE,
    OPENAI_EVIDENCE_EVENT_TYPE,
    OPENAI_EVIDENCE_SCENARIO,
)
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    PolicyDecisionResult,
    RecoveryAction,
    StrategySource,
)
from arc.domain.models import (
    ApprovalRequest,
    CaseEvent,
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
    RecoveryActionRecord,
    RecoveryAttribution,
    StrategyProposal,
)
from arc.intelligence.schemas import StrategyModelClient
from arc.intelligence.service import StrategyService
from arc.persistence import append_case_event, create_payment_case
from arc.policy.service import MerchantAuthorizationService
from arc.reconciliation.state_machine import transition_case

_EVIDENCE_MERCHANT_ID = "synthetic_openai_evidence_merchant_v1"
_EVIDENCE_PAYMENT_ID = "synthetic_openai_evidence_payment_v1"
_EXTERNAL_ACTIONS = (
    RecoveryAction.REQUEST_RETRY,
    RecoveryAction.CREATE_RECOVERY_LINK,
    RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
)
_SAFE_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")


class OpenAIEvidenceError(RuntimeError):
    """Base sanitized workflow failure."""

    reason_code = "OPENAI_EVIDENCE_FAILED"


class OpenAIEvidenceConfigurationError(OpenAIEvidenceError):
    """Raised before database access when the private key is unavailable."""

    reason_code = "OPENAI_EVIDENCE_NOT_CONFIGURED"


class OpenAIEvidenceConflictError(OpenAIEvidenceError):
    """Raised when reserved synthetic identities contain unexpected data."""

    reason_code = "OPENAI_EVIDENCE_CONFLICT"


@dataclass(frozen=True, slots=True)
class OpenAIEvidenceResult:
    """Sanitized proof returned to the explicit operator script."""

    case_reference: str
    model: str
    action: RecoveryAction
    confidence: float
    policy_result: PolicyDecisionResult
    final_state: CaseState
    approval_pending: bool
    idempotent: bool


def create_openai_evidence_case(
    *,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
    model_client: StrategyModelClient | None = None,
) -> OpenAIEvidenceResult:
    """Persist one synthetic-input model proposal and stop before execution."""

    resolved_settings = settings or get_settings()
    if model_client is None:
        key = resolved_settings.openai_api_key
        if key is None or not key.get_secret_value().strip():
            raise OpenAIEvidenceConfigurationError(
                "OpenAI evidence credentials are not configured"
            )

    factory = session_factory or get_session_factory()
    case_id, created = _ensure_synthetic_case(factory)
    state = _case_state(factory, case_id)

    if state is CaseState.RECONCILING:
        CaseAssessmentService(session_factory=factory).assess_case(case_id)
        state = _case_state(factory, case_id)
    if state is CaseState.DIAGNOSED:
        StrategyService(
            session_factory=factory,
            model_client=model_client,
            settings=resolved_settings,
        ).generate_strategy(case_id)
        state = _case_state(factory, case_id)
    if state is CaseState.DECISIONED:
        MerchantAuthorizationService(session_factory=factory).evaluate_policy(
            case_id
        )
        state = _case_state(factory, case_id)

    decision = _current_decision(factory, case_id)
    if decision.result is PolicyDecisionResult.REQUIRES_APPROVAL:
        HumanApprovalService(session_factory=factory).ensure_approval_request(
            decision.id
        )
    elif decision.result is PolicyDecisionResult.AUTHORIZED:
        proposal = _current_proposal(factory, case_id)
        if proposal.action not in {
            RecoveryAction.NO_ACTION,
            RecoveryAction.WAIT,
            RecoveryAction.ESCALATE_TO_HUMAN,
        }:
            raise OpenAIEvidenceConflictError(
                "OpenAI evidence did not reach a safe non-execution policy state"
            )
    elif state not in {CaseState.EXHAUSTED, CaseState.ESCALATED}:
        raise OpenAIEvidenceConflictError(
            "OpenAI evidence policy state is invalid"
        )

    return _verified_result(factory, case_id, created=created)


def _ensure_synthetic_case(
    session_factory: Callable[[], Session],
) -> tuple[UUID, bool]:
    try:
        with session_factory() as session:
            existing = _existing_case(session)
            if existing is not None:
                return existing.id, False
            _ensure_policy(session)
            now = datetime.now(UTC)
            payment_case = create_payment_case(
                session,
                PaymentCase(
                    case_reference=OPENAI_EVIDENCE_CASE_REFERENCE,
                    merchant_id=_EVIDENCE_MERCHANT_ID,
                    payment_id=_EVIDENCE_PAYMENT_ID,
                    amount=2_500_000,
                    currency="INR",
                    razorpay_payment_status="failed",
                    razorpay_payment_method="card",
                    error_source="customer",
                    error_step="payment_authorization",
                    error_reason="insufficient_funds",
                    attempt_count=0,
                    contact_attempt_count=0,
                    detected_at=now - timedelta(seconds=2),
                    last_reconciled_at=now - timedelta(seconds=1),
                ),
            )
            append_case_event(
                session,
                CaseEvent(
                    case_id=payment_case.id,
                    event_type=OPENAI_EVIDENCE_EVENT_TYPE,
                    source=OPENAI_EVIDENCE_EVENT_SOURCE,
                    event_data={
                        "scenario_key": OPENAI_EVIDENCE_SCENARIO,
                        "synthetic": True,
                    },
                    created_at=now - timedelta(seconds=3),
                ),
            )
            append_case_event(
                session,
                CaseEvent(
                    case_id=payment_case.id,
                    event_type="CASE_DETECTED",
                    source=OPENAI_EVIDENCE_EVENT_SOURCE,
                    event_data={"reason_code": "CASE_DETECTED"},
                    created_at=now - timedelta(seconds=2),
                ),
            )
            transition_case(
                session,
                payment_case,
                CaseState.RECONCILING,
                reason_code="AUTHORITATIVE_RECONCILIATION_STARTED",
                source=OPENAI_EVIDENCE_EVENT_SOURCE,
            )
            append_case_event(
                session,
                CaseEvent(
                    case_id=payment_case.id,
                    event_type="RECONCILIATION_CONFIRMED_FAILURE",
                    source=OPENAI_EVIDENCE_EVENT_SOURCE,
                    event_data={
                        "reason_code": "RECONCILIATION_CONFIRMED_FAILURE"
                    },
                    created_at=now - timedelta(seconds=1),
                ),
            )
            session.commit()
            return payment_case.id, True
    except IntegrityError as error:
        with session_factory() as session:
            existing = _existing_case(session)
            if existing is not None:
                return existing.id, False
        raise OpenAIEvidenceConflictError(
            "OpenAI evidence identities conflicted"
        ) from error


def _ensure_policy(session: Session) -> None:
    allowed = [action.value for action in _EXTERNAL_ACTIONS]
    stopping_rules = {
        "require_approval_actions": allowed,
    }
    existing = session.scalar(
        select(MerchantPolicy).where(
            MerchantPolicy.merchant_id == _EVIDENCE_MERCHANT_ID
        )
    )
    expected = {
        "automation_enabled": True,
        "allowed_actions": allowed,
        "max_automated_attempts": 3,
        "max_contact_attempts": 3,
        "recovery_window_minutes": 1_440,
        "high_value_threshold_minor": 1_000_000,
        "require_approval_above_minor": 2_500_000,
        "stopping_rules": stopping_rules,
    }
    if existing is None:
        session.add(MerchantPolicy(merchant_id=_EVIDENCE_MERCHANT_ID, **expected))
        session.flush()
        return
    if any(getattr(existing, key) != value for key, value in expected.items()):
        raise OpenAIEvidenceConflictError(
            "Reserved OpenAI evidence policy contains unexpected data"
        )


def _existing_case(session: Session) -> PaymentCase | None:
    payment_case = session.scalar(
        select(PaymentCase).where(
            PaymentCase.case_reference == OPENAI_EVIDENCE_CASE_REFERENCE
        )
    )
    if payment_case is None:
        return None
    marker = session.scalar(
        select(CaseEvent).where(
            CaseEvent.case_id == payment_case.id,
            CaseEvent.event_type == OPENAI_EVIDENCE_EVENT_TYPE,
            CaseEvent.source == OPENAI_EVIDENCE_EVENT_SOURCE,
        )
    )
    if marker is None or marker.event_data != {
        "scenario_key": OPENAI_EVIDENCE_SCENARIO,
        "synthetic": True,
    }:
        raise OpenAIEvidenceConflictError(
            "Reserved OpenAI evidence case contains unexpected data"
        )
    return payment_case


def _verified_result(
    session_factory: Callable[[], Session],
    case_id: UUID,
    *,
    created: bool,
) -> OpenAIEvidenceResult:
    with session_factory() as session:
        payment_case = session.get(PaymentCase, case_id)
        proposal = session.scalar(
            select(StrategyProposal).where(
                StrategyProposal.case_id == case_id,
                StrategyProposal.superseded_at.is_(None),
            )
        )
        decision = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.case_id == case_id,
                PolicyDecision.superseded_at.is_(None),
            )
        )
        action_count = session.scalar(
            select(func.count()).select_from(RecoveryActionRecord).where(
                RecoveryActionRecord.case_id == case_id
            )
        )
        attribution_count = session.scalar(
            select(func.count()).select_from(RecoveryAttribution).where(
                RecoveryAttribution.case_id == case_id
            )
        )
        if (
            payment_case is None
            or proposal is None
            or decision is None
            or proposal.source is not StrategySource.AI
            or proposal.model in {None, OFFLINE_DEMO_STRATEGY_MODEL}
            or _SAFE_MODEL_NAME.fullmatch(proposal.model or "") is None
            or proposal.confidence is None
            or action_count != 0
            or attribution_count != 0
            or payment_case.current_state
            not in {
                CaseState.POLICY_VALIDATED,
                CaseState.ESCALATED,
                CaseState.EXHAUSTED,
            }
        ):
            raise OpenAIEvidenceConflictError(
                "OpenAI evidence verification failed safely"
            )
        approval_pending = (
            session.scalar(
                select(func.count()).select_from(ApprovalRequest).where(
                    ApprovalRequest.policy_decision_id == decision.id,
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                )
            )
            == 1
        )
        if (
            decision.result is PolicyDecisionResult.REQUIRES_APPROVAL
            and not approval_pending
        ):
            raise OpenAIEvidenceConflictError(
                "Required OpenAI evidence approval request is missing"
            )
        return OpenAIEvidenceResult(
            case_reference=payment_case.case_reference,
            model=proposal.model,
            action=proposal.action,
            confidence=proposal.confidence,
            policy_result=decision.result,
            final_state=payment_case.current_state,
            approval_pending=approval_pending,
            idempotent=not created,
        )


def _case_state(
    session_factory: Callable[[], Session],
    case_id: UUID,
) -> CaseState:
    with session_factory() as session:
        payment_case = session.get(PaymentCase, case_id)
        if payment_case is None:
            raise OpenAIEvidenceConflictError(
                "OpenAI evidence case was not found"
            )
        return payment_case.current_state


def _current_proposal(
    session_factory: Callable[[], Session],
    case_id: UUID,
) -> StrategyProposal:
    with session_factory() as session:
        proposal = session.scalar(
            select(StrategyProposal).where(
                StrategyProposal.case_id == case_id,
                StrategyProposal.superseded_at.is_(None),
            )
        )
        if proposal is None:
            raise OpenAIEvidenceConflictError(
                "OpenAI evidence proposal is missing"
            )
        session.expunge(proposal)
        return proposal


def _current_decision(
    session_factory: Callable[[], Session],
    case_id: UUID,
) -> PolicyDecision:
    with session_factory() as session:
        decision = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.case_id == case_id,
                PolicyDecision.superseded_at.is_(None),
            )
        )
        if decision is None:
            raise OpenAIEvidenceConflictError(
                "OpenAI evidence policy decision is missing"
            )
        session.expunge(decision)
        return decision


__all__ = [
    "OpenAIEvidenceConfigurationError",
    "OpenAIEvidenceConflictError",
    "OpenAIEvidenceError",
    "OpenAIEvidenceResult",
    "create_openai_evidence_case",
]
