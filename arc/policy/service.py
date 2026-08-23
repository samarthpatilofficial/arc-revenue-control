"""Transactional deterministic merchant policy authorization service."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from arc.domain.enums import (
    CaseState,
    EligibilityDecision,
    PolicyDecisionResult,
    RecoveryAction,
)
from arc.domain.models import (
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
    StrategyProposal,
)
from arc.diagnosis import classify_failure
from arc.intelligence.context import required_assessment_fingerprint
from arc.policy.audit import POLICY_AUDIT_SOURCE, append_policy_audit
from arc.policy.authorization import (
    AuthorizationEvaluation,
    AuthorizationFacts,
    evaluate_authorization,
)
from arc.policy.fingerprint import (
    build_authorization_input_fingerprint,
    build_policy_fingerprint,
)
from arc.policy.eligibility import assess_eligibility
from arc.policy.schemas import (
    PolicyConfiguration,
    PolicyConfigurationError,
    validate_policy,
)
from arc.reconciliation.state_machine import transition_case


class PolicyCaseNotFoundError(LookupError):
    """Raised when the requested payment case does not exist."""

    reason_code = "POLICY_CASE_NOT_FOUND"


class PolicyEvaluationNotAllowedError(ValueError):
    """Raised when current case state cannot be policy evaluated."""

    reason_code = "POLICY_EVALUATION_NOT_ALLOWED"


class PolicyProposalNotCurrentError(ValueError):
    """Raised when no current strategy proposal safely matches case truth."""

    reason_code = "POLICY_STRATEGY_PROPOSAL_NOT_CURRENT"


@dataclass(frozen=True, slots=True)
class PolicyEvaluationResult:
    """Sanitized current deterministic policy decision projection."""

    policy_decision_id: UUID
    case_id: UUID
    strategy_proposal_id: UUID
    case_state: CaseState
    action: RecoveryAction
    result: PolicyDecisionResult
    reason_code: str
    explanation: str
    policy_fingerprint: str
    authorization_input_fingerprint: str
    idempotent: bool


_HARD_STOP_REASONS = frozenset(
    {
        "MAX_AUTOMATED_ATTEMPTS_REACHED",
        "MAX_CUSTOMER_CONTACTS_REACHED",
        "RECOVERY_WINDOW_EXPIRED",
        "STOPPING_RULE_FAILURE_CATEGORY",
        "STOPPING_RULE_PAYMENT_METHOD",
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MerchantAuthorizationService:
    """Evaluate current proposal and policy in one row-locked transaction."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def evaluate_policy(
        self,
        case_id: UUID,
        *,
        strategy_proposal_id: UUID | None = None,
    ) -> PolicyEvaluationResult:
        """Persist or idempotently return one deterministic authorization."""

        with self._session_factory() as session:
            payment_case = _lock_case(session, case_id)
            _validate_case_state(payment_case)
            proposal = _load_current_proposal(session, payment_case)
            if (
                strategy_proposal_id is not None
                and proposal.id != strategy_proposal_id
            ):
                raise PolicyProposalNotCurrentError(
                    "Only the current strategy proposal may be evaluated"
                )
            _validate_current_proposal(payment_case, proposal, clock=self._clock)

            merchant_policy = session.scalar(
                select(MerchantPolicy)
                .where(MerchantPolicy.merchant_id == payment_case.merchant_id)
                .with_for_update()
            )
            configuration = _validate_if_present(merchant_policy)
            policy_fingerprint = build_policy_fingerprint(
                merchant_policy,
                configuration,
            )
            evaluated_at = self._clock()
            _require_aware_datetime(evaluated_at, "Policy clock")
            _require_aware_datetime(payment_case.detected_at, "Case detected_at")
            evaluation = evaluate_authorization(
                AuthorizationFacts(
                    action=proposal.action,
                    amount_minor=payment_case.amount,
                    attempt_count=payment_case.attempt_count,
                    contact_attempt_count=payment_case.contact_attempt_count,
                    detected_at=payment_case.detected_at,
                    failure_category=payment_case.failure_category,
                    payment_method=payment_case.razorpay_payment_method,
                    evaluated_at=evaluated_at,
                ),
                policy_present=merchant_policy is not None,
                configuration=configuration,
            )
            assessment_fingerprint = required_assessment_fingerprint(
                payment_case
            )
            authorization_fingerprint = (
                build_authorization_input_fingerprint(
                    strategy_proposal_id=proposal.id,
                    strategy_input_fingerprint=(
                        proposal.strategy_input_fingerprint
                    ),
                    assessment_fingerprint=assessment_fingerprint,
                    policy_fingerprint=policy_fingerprint,
                    action=proposal.action,
                    attempt_count=payment_case.attempt_count,
                    contact_attempt_count=(
                        payment_case.contact_attempt_count
                    ),
                    amount_minor=payment_case.amount,
                    failure_category=payment_case.failure_category,
                    payment_method=payment_case.razorpay_payment_method,
                    recovery_window_ends_at=(
                        evaluation.recovery_window_ends_at
                    ),
                    recovery_window_expired=(
                        evaluation.recovery_window_expired
                    ),
                )
            )
            existing = _find_identical_decision(
                session,
                payment_case.id,
                authorization_fingerprint,
            )
            if existing is not None and existing.superseded_at is None:
                return _to_result(
                    existing,
                    payment_case,
                    proposal.action,
                    idempotent=True,
                )

            previous_state = payment_case.current_state
            current_decision = _find_current_decision(session, payment_case.id)
            reevaluated = current_decision is not None
            if current_decision is not None:
                current_decision.superseded_at = evaluated_at

            if existing is not None:
                existing.superseded_at = None
                decision = existing
            else:
                decision = _build_decision(
                    payment_case,
                    proposal,
                    merchant_policy,
                    evaluation,
                    policy_fingerprint=policy_fingerprint,
                    authorization_fingerprint=authorization_fingerprint,
                    evaluated_at=evaluated_at,
                )
                session.add(decision)
                session.flush()

            _apply_policy_transition(session, payment_case, decision)
            append_policy_audit(
                session,
                payment_case,
                decision,
                action=proposal.action,
                previous_state=previous_state,
                reevaluated=reevaluated,
            )
            result = _to_result(
                decision,
                payment_case,
                proposal.action,
                idempotent=False,
            )
            session.commit()
            return result


def evaluate_policy(
    case_id: UUID,
    *,
    session_factory: Callable[[], Session],
    strategy_proposal_id: UUID | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> PolicyEvaluationResult:
    """Convenience entry point for deterministic merchant authorization."""

    return MerchantAuthorizationService(
        session_factory=session_factory,
        clock=clock,
    ).evaluate_policy(
        case_id,
        strategy_proposal_id=strategy_proposal_id,
    )


def _lock_case(session: Session, case_id: UUID) -> PaymentCase:
    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.id == case_id)
        .with_for_update()
    )
    if payment_case is None:
        raise PolicyCaseNotFoundError("Payment case was not found")
    return payment_case


def _validate_case_state(payment_case: PaymentCase) -> None:
    if payment_case.current_state not in {
        CaseState.DECISIONED,
        CaseState.POLICY_VALIDATED,
    }:
        raise PolicyEvaluationNotAllowedError(
            "Case state does not allow merchant policy evaluation"
        )


def _load_current_proposal(
    session: Session,
    payment_case: PaymentCase,
) -> StrategyProposal:
    proposal = session.scalar(
        select(StrategyProposal).where(
            StrategyProposal.case_id == payment_case.id,
            StrategyProposal.superseded_at.is_(None),
        )
    )
    if proposal is None:
        raise PolicyProposalNotCurrentError(
            "A current strategy proposal is required"
        )
    return proposal


def _validate_current_proposal(
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    *,
    clock: Callable[[], datetime],
) -> None:
    if proposal.case_id != payment_case.id or proposal.superseded_at is not None:
        raise PolicyProposalNotCurrentError(
            "Strategy proposal does not belong to the current case"
        )
    assessment_fingerprint = payment_case.assessment_fingerprint
    if (
        assessment_fingerprint is None
        or proposal.assessment_fingerprint != assessment_fingerprint
    ):
        raise PolicyProposalNotCurrentError(
            "Strategy proposal assessment is stale"
        )
    eligibility = assess_eligibility(payment_case, clock=clock)
    if (
        eligibility.decision is not EligibilityDecision.ELIGIBLE
        or eligibility.assessment_fingerprint != assessment_fingerprint
        or payment_case.eligibility_status is not EligibilityDecision.ELIGIBLE
        or payment_case.eligibility_reason_code != eligibility.reason_code
    ):
        raise PolicyProposalNotCurrentError(
            "Strategy proposal no longer matches current eligibility"
        )
    diagnosis = classify_failure(payment_case)
    if (
        diagnosis.failure_category is not payment_case.failure_category
        or diagnosis.recovery_disposition is not payment_case.recovery_disposition
        or diagnosis.diagnosis_reason_code
        != payment_case.diagnosis_reason_code
    ):
        raise PolicyProposalNotCurrentError(
            "Strategy proposal no longer matches current diagnosis"
        )


def _validate_if_present(
    merchant_policy: MerchantPolicy | None,
) -> PolicyConfiguration | None:
    if merchant_policy is None:
        return None
    try:
        return validate_policy(merchant_policy)
    except PolicyConfigurationError:
        return None


def _require_aware_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PolicyEvaluationNotAllowedError(
            f"{name} must be timezone-aware"
        )


def _find_identical_decision(
    session: Session,
    case_id: UUID,
    authorization_fingerprint: str,
) -> PolicyDecision | None:
    return session.scalar(
        select(PolicyDecision).where(
            PolicyDecision.case_id == case_id,
            PolicyDecision.authorization_input_fingerprint
            == authorization_fingerprint,
        )
    )


def _find_current_decision(
    session: Session,
    case_id: UUID,
) -> PolicyDecision | None:
    return session.scalar(
        select(PolicyDecision).where(
            PolicyDecision.case_id == case_id,
            PolicyDecision.superseded_at.is_(None),
        )
    )


def _build_decision(
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    merchant_policy: MerchantPolicy | None,
    evaluation: AuthorizationEvaluation,
    *,
    policy_fingerprint: str,
    authorization_fingerprint: str,
    evaluated_at: datetime,
) -> PolicyDecision:
    return PolicyDecision(
        case_id=payment_case.id,
        strategy_proposal_id=proposal.id,
        merchant_policy_id=(
            merchant_policy.id if merchant_policy is not None else None
        ),
        strategy_input_fingerprint=proposal.strategy_input_fingerprint,
        policy_fingerprint=policy_fingerprint,
        authorization_input_fingerprint=authorization_fingerprint,
        result=evaluation.result,
        reason_code=evaluation.reason_code,
        explanation=evaluation.explanation,
        recovery_window_ends_at=evaluation.recovery_window_ends_at,
        approval_threshold_minor=evaluation.approval_threshold_minor,
        high_value_threshold_minor=evaluation.high_value_threshold_minor,
        observed_high_value=evaluation.observed_high_value,
        observed_amount_minor=payment_case.amount,
        observed_attempt_count=payment_case.attempt_count,
        observed_contact_attempt_count=payment_case.contact_attempt_count,
        evaluated_at=evaluated_at,
    )


def _apply_policy_transition(
    session: Session,
    payment_case: PaymentCase,
    decision: PolicyDecision,
) -> None:
    if decision.result is PolicyDecisionResult.AUTHORIZED:
        target = CaseState.POLICY_VALIDATED
        reason = "POLICY_AUTHORIZED"
    elif decision.result is PolicyDecisionResult.REQUIRES_APPROVAL:
        target = CaseState.POLICY_VALIDATED
        reason = "POLICY_REQUIRES_APPROVAL"
    elif decision.reason_code in _HARD_STOP_REASONS:
        target = CaseState.EXHAUSTED
        reason = decision.reason_code
    else:
        target = CaseState.ESCALATED
        reason = decision.reason_code
    transition_case(
        session,
        payment_case,
        target,
        reason_code=reason,
        source=POLICY_AUDIT_SOURCE,
        metadata={"policy_decision_id": str(decision.id)},
    )


def _to_result(
    decision: PolicyDecision,
    payment_case: PaymentCase,
    action: RecoveryAction,
    *,
    idempotent: bool,
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_decision_id=decision.id,
        case_id=decision.case_id,
        strategy_proposal_id=decision.strategy_proposal_id,
        case_state=payment_case.current_state,
        action=action,
        result=decision.result,
        reason_code=decision.reason_code,
        explanation=decision.explanation,
        policy_fingerprint=decision.policy_fingerprint,
        authorization_input_fingerprint=(
            decision.authorization_input_fingerprint
        ),
        idempotent=idempotent,
    )
