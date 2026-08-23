"""Transactional application service for eligibility and failure diagnosis."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from arc.diagnosis import FailureDiagnosis, classify_failure
from arc.domain.enums import (
    CaseState,
    EligibilityDecision,
    FailureCategory,
    RecoveryDisposition,
)
from arc.domain.models import CaseEvent, PaymentCase
from arc.policy import EligibilityResult, assess_eligibility
from arc.reconciliation.state_machine import transition_case

ASSESSMENT_SOURCE = "DETERMINISTIC_ASSESSMENT"


class PaymentCaseNotFoundError(LookupError):
    """Raised when an assessment target does not exist."""


@dataclass(frozen=True, slots=True)
class CaseAssessmentResult:
    """Current persisted deterministic assessment projection."""

    case_id: UUID
    case_state: CaseState
    eligibility_status: EligibilityDecision
    eligibility_reason_code: str
    failure_category: FailureCategory | None
    recovery_disposition: RecoveryDisposition | None
    diagnosis_reason_code: str | None
    assessment_fingerprint: str
    idempotent: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CaseAssessmentService:
    """Assess one row-locked reconciled case without external calls."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def assess_case(self, case_id: UUID) -> CaseAssessmentResult:
        """Persist one idempotent current assessment and bounded audit trail."""

        with self._session_factory() as session:
            payment_case = session.scalar(
                select(PaymentCase)
                .where(PaymentCase.id == case_id)
                .with_for_update()
            )
            if payment_case is None:
                raise PaymentCaseNotFoundError("Payment case was not found")

            assessed_at = self._clock()
            eligibility = assess_eligibility(
                payment_case,
                clock=lambda: assessed_at,
            )
            diagnosis = (
                classify_failure(payment_case)
                if eligibility.decision is EligibilityDecision.ELIGIBLE
                else None
            )
            if _is_fully_assessed(payment_case, eligibility, diagnosis):
                return _to_result(payment_case, idempotent=True)

            previous_state = payment_case.current_state
            previously_diagnosed = (
                payment_case.diagnosed_at is not None
                or previous_state is CaseState.DIAGNOSED
            )
            _persist_eligibility(payment_case, eligibility, assessed_at)
            _append_eligibility_audit(
                session,
                payment_case,
                eligibility,
                previous_state,
            )

            if eligibility.decision is not EligibilityDecision.ELIGIBLE:
                _clear_diagnosis(payment_case)
                session.commit()
                return _to_result(payment_case, idempotent=False)

            if diagnosis is None:
                raise RuntimeError(
                    "Eligible case did not produce a deterministic diagnosis"
                )
            _persist_diagnosis(payment_case, diagnosis, assessed_at)
            if payment_case.current_state is CaseState.RECONCILING:
                transition_case(
                    session,
                    payment_case,
                    CaseState.DIAGNOSED,
                    reason_code="DETERMINISTIC_FAILURE_DIAGNOSED",
                    source=ASSESSMENT_SOURCE,
                    metadata={
                        "assessment_fingerprint": (
                            eligibility.assessment_fingerprint
                        ),
                    },
                )
            _append_diagnosis_audit(
                session,
                payment_case,
                diagnosis,
                eligibility.assessment_fingerprint,
                previous_state=previous_state,
                rediagnosed=previously_diagnosed,
            )
            session.commit()
            return _to_result(payment_case, idempotent=False)


def assess_case(
    case_id: UUID,
    *,
    session_factory: Callable[[], Session],
    clock: Callable[[], datetime] = _utc_now,
) -> CaseAssessmentResult:
    """Convenience entry point for direct application-service invocation."""

    return CaseAssessmentService(
        session_factory=session_factory,
        clock=clock,
    ).assess_case(case_id)


def _is_fully_assessed(
    payment_case: PaymentCase,
    eligibility: EligibilityResult,
    diagnosis: FailureDiagnosis | None,
) -> bool:
    if (
        payment_case.assessment_fingerprint
        != eligibility.assessment_fingerprint
        or payment_case.eligibility_status is not eligibility.decision
        or payment_case.eligibility_reason_code != eligibility.reason_code
        or payment_case.eligibility_evaluated_at is None
    ):
        return False
    if eligibility.decision is EligibilityDecision.ELIGIBLE:
        return (
            diagnosis is not None
            and payment_case.failure_category is diagnosis.failure_category
            and payment_case.recovery_disposition
            is diagnosis.recovery_disposition
            and payment_case.diagnosis_reason_code
            == diagnosis.diagnosis_reason_code
            and payment_case.diagnosed_at is not None
        )
    return all(
        value is None
        for value in (
            payment_case.failure_category,
            payment_case.recovery_disposition,
            payment_case.diagnosis_reason_code,
            payment_case.diagnosed_at,
        )
    )


def _persist_eligibility(
    payment_case: PaymentCase,
    eligibility: EligibilityResult,
    assessed_at: datetime,
) -> None:
    payment_case.eligibility_status = eligibility.decision
    payment_case.eligibility_reason_code = eligibility.reason_code
    payment_case.eligibility_evaluated_at = assessed_at
    payment_case.assessment_fingerprint = eligibility.assessment_fingerprint


def _clear_diagnosis(payment_case: PaymentCase) -> None:
    payment_case.failure_category = None
    payment_case.recovery_disposition = None
    payment_case.diagnosis_reason_code = None
    payment_case.diagnosed_at = None


def _persist_diagnosis(
    payment_case: PaymentCase,
    diagnosis: FailureDiagnosis,
    assessed_at: datetime,
) -> None:
    payment_case.failure_category = diagnosis.failure_category
    payment_case.recovery_disposition = diagnosis.recovery_disposition
    payment_case.diagnosis_reason_code = diagnosis.diagnosis_reason_code
    payment_case.diagnosed_at = assessed_at


def _external_status(payment_case: PaymentCase) -> str | None:
    return (
        payment_case.razorpay_payment_status
        or payment_case.razorpay_subscription_status
    )


def _append_eligibility_audit(
    session: Session,
    payment_case: PaymentCase,
    eligibility: EligibilityResult,
    previous_state: CaseState,
) -> None:
    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type="ELIGIBILITY_EVALUATED",
            source=ASSESSMENT_SOURCE,
            event_data={
                "eligibility_decision": eligibility.decision.value,
                "eligibility_reason": eligibility.reason_code,
                "external_status": _external_status(payment_case),
                "assessment_fingerprint": eligibility.assessment_fingerprint,
                "previous_state": previous_state.value,
                "new_state": payment_case.current_state.value,
            },
        )
    )


def _append_diagnosis_audit(
    session: Session,
    payment_case: PaymentCase,
    diagnosis: FailureDiagnosis,
    assessment_fingerprint: str,
    *,
    previous_state: CaseState,
    rediagnosed: bool,
) -> None:
    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type=(
                "FAILURE_REDIAGNOSED" if rediagnosed else "FAILURE_DIAGNOSED"
            ),
            source=ASSESSMENT_SOURCE,
            event_data={
                "failure_category": diagnosis.failure_category.value,
                "recovery_disposition": diagnosis.recovery_disposition.value,
                "diagnosis_reason": diagnosis.diagnosis_reason_code,
                "evidence": diagnosis.evidence,
                "external_status": _external_status(payment_case),
                "assessment_fingerprint": assessment_fingerprint,
                "previous_state": previous_state.value,
                "new_state": payment_case.current_state.value,
            },
        )
    )


def _to_result(
    payment_case: PaymentCase,
    *,
    idempotent: bool,
) -> CaseAssessmentResult:
    eligibility_status = payment_case.eligibility_status
    eligibility_reason_code = payment_case.eligibility_reason_code
    assessment_fingerprint = payment_case.assessment_fingerprint
    if (
        eligibility_status is None
        or eligibility_reason_code is None
        or assessment_fingerprint is None
    ):
        raise RuntimeError("Case assessment projection is incomplete")
    return CaseAssessmentResult(
        case_id=payment_case.id,
        case_state=payment_case.current_state,
        eligibility_status=eligibility_status,
        eligibility_reason_code=eligibility_reason_code,
        failure_category=payment_case.failure_category,
        recovery_disposition=payment_case.recovery_disposition,
        diagnosis_reason_code=payment_case.diagnosis_reason_code,
        assessment_fingerprint=assessment_fingerprint,
        idempotent=idempotent,
    )
