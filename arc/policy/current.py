"""Shared recomputation of current deterministic authorization inputs."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from arc.diagnosis import classify_failure
from arc.domain.enums import EligibilityDecision
from arc.domain.models import MerchantPolicy, PaymentCase, StrategyProposal
from arc.intelligence.context import required_assessment_fingerprint
from arc.policy.authorization import (
    AuthorizationEvaluation,
    AuthorizationFacts,
    evaluate_authorization,
)
from arc.policy.eligibility import assess_eligibility
from arc.policy.fingerprint import (
    build_authorization_input_fingerprint,
    build_policy_fingerprint,
)
from arc.policy.schemas import (
    PolicyConfiguration,
    PolicyConfigurationError,
    validate_policy,
)


class CurrentAuthorizationError(ValueError):
    """Raised when proposal or assessment truth is no longer current."""


@dataclass(frozen=True, slots=True)
class CurrentAuthorizationInputs:
    """Recomputed policy facts and fingerprints with execution authority."""

    merchant_policy: MerchantPolicy | None
    configuration: PolicyConfiguration | None
    assessment_fingerprint: str
    policy_fingerprint: str
    authorization_input_fingerprint: str
    evaluation: AuthorizationEvaluation


def recompute_current_authorization_inputs(
    session: Session,
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    *,
    evaluated_at: datetime,
    lock_policy: bool,
) -> CurrentAuthorizationInputs:
    """Revalidate deterministic truth and recompute all policy authority."""

    _require_aware(evaluated_at, "Authorization clock")
    _require_aware(payment_case.detected_at, "Case detected_at")
    _validate_current_proposal(payment_case, proposal, evaluated_at)

    query = select(MerchantPolicy).where(
        MerchantPolicy.merchant_id == payment_case.merchant_id
    )
    if lock_policy:
        query = query.with_for_update()
    merchant_policy = session.scalar(query)
    configuration = _validate_if_present(merchant_policy)
    policy_fingerprint = build_policy_fingerprint(
        merchant_policy,
        configuration,
    )
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
    assessment_fingerprint = required_assessment_fingerprint(payment_case)
    authorization_fingerprint = build_authorization_input_fingerprint(
        strategy_proposal_id=proposal.id,
        strategy_input_fingerprint=proposal.strategy_input_fingerprint,
        assessment_fingerprint=assessment_fingerprint,
        policy_fingerprint=policy_fingerprint,
        action=proposal.action,
        attempt_count=payment_case.attempt_count,
        contact_attempt_count=payment_case.contact_attempt_count,
        amount_minor=payment_case.amount,
        failure_category=payment_case.failure_category,
        payment_method=payment_case.razorpay_payment_method,
        recovery_window_ends_at=evaluation.recovery_window_ends_at,
        recovery_window_expired=evaluation.recovery_window_expired,
    )
    return CurrentAuthorizationInputs(
        merchant_policy=merchant_policy,
        configuration=configuration,
        assessment_fingerprint=assessment_fingerprint,
        policy_fingerprint=policy_fingerprint,
        authorization_input_fingerprint=authorization_fingerprint,
        evaluation=evaluation,
    )


def _validate_current_proposal(
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    evaluated_at: datetime,
) -> None:
    if proposal.case_id != payment_case.id or proposal.superseded_at is not None:
        raise CurrentAuthorizationError(
            "Strategy proposal does not belong to the current case"
        )
    assessment_fingerprint = payment_case.assessment_fingerprint
    if (
        assessment_fingerprint is None
        or proposal.assessment_fingerprint != assessment_fingerprint
    ):
        raise CurrentAuthorizationError("Strategy proposal assessment is stale")

    eligibility = assess_eligibility(
        payment_case,
        clock=lambda: evaluated_at,
    )
    if (
        eligibility.decision is not EligibilityDecision.ELIGIBLE
        or eligibility.assessment_fingerprint != assessment_fingerprint
        or payment_case.eligibility_status is not EligibilityDecision.ELIGIBLE
        or payment_case.eligibility_reason_code != eligibility.reason_code
    ):
        raise CurrentAuthorizationError(
            "Strategy proposal no longer matches current eligibility"
        )
    diagnosis = classify_failure(payment_case)
    if (
        diagnosis.failure_category is not payment_case.failure_category
        or diagnosis.recovery_disposition
        is not payment_case.recovery_disposition
        or diagnosis.diagnosis_reason_code
        != payment_case.diagnosis_reason_code
    ):
        raise CurrentAuthorizationError(
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


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CurrentAuthorizationError(f"{name} must be timezone-aware")
