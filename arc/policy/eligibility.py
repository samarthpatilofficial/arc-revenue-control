"""Deterministic preconditions for considering recovery reasoning."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from arc.domain.enums import CaseState, EligibilityDecision
from arc.domain.models import PaymentCase

RECONCILIATION_FRESHNESS_SECONDS = 300
RECONCILIATION_FRESHNESS = timedelta(
    seconds=RECONCILIATION_FRESHNESS_SECONDS
)
ASSESSMENT_RULESET_VERSION = "task5-v1"

_TERMINAL_REASONS = {
    CaseState.RECOVERED: "STOP_ALREADY_RECOVERED",
    CaseState.EXHAUSTED: "STOP_ALREADY_EXHAUSTED",
    CaseState.ESCALATED: "STOP_ALREADY_ESCALATED",
}


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """Bounded precondition result based only on persisted reconciled facts."""

    decision: EligibilityDecision
    reason_code: str
    explanation: str
    assessment_fingerprint: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def build_assessment_fingerprint(payment_case: PaymentCase) -> str:
    """Hash assessment inputs without including mutable assessment outputs."""

    terminal_state = (
        payment_case.current_state.value
        if payment_case.current_state in _TERMINAL_REASONS
        else None
    )
    reconciled_at = payment_case.last_reconciled_at
    facts = {
        "ruleset_version": ASSESSMENT_RULESET_VERSION,
        "terminal_case_state": terminal_state,
        "payment_id": payment_case.payment_id,
        "subscription_id": payment_case.subscription_id,
        "razorpay_payment_status": _normalized(
            payment_case.razorpay_payment_status
        ),
        "razorpay_subscription_status": _normalized(
            payment_case.razorpay_subscription_status
        ),
        "error_code": _normalized(payment_case.error_code),
        "error_source": _normalized(payment_case.error_source),
        "error_step": _normalized(payment_case.error_step),
        "error_reason": _normalized(payment_case.error_reason),
        "payment_method": _normalized(payment_case.razorpay_payment_method),
        "amount": payment_case.amount,
        "currency": (
            payment_case.currency.strip().upper()
            if payment_case.currency is not None
            else None
        ),
        "last_reconciled_at": (
            reconciled_at.isoformat() if reconciled_at is not None else None
        ),
    }
    serialized = json.dumps(
        facts,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def assess_eligibility(
    payment_case: PaymentCase,
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> EligibilityResult:
    """Evaluate recovery-reasoning preconditions without choosing an action."""

    fingerprint = build_assessment_fingerprint(payment_case)

    terminal_reason = _TERMINAL_REASONS.get(payment_case.current_state)
    if terminal_reason is not None:
        return _result(
            EligibilityDecision.STOP,
            terminal_reason,
            "The ARC case is terminal and cannot be reopened.",
            fingerprint,
        )

    if not payment_case.payment_id and not payment_case.subscription_id:
        return _result(
            EligibilityDecision.REVIEW,
            "CASE_IDENTITY_MISSING",
            "The case has no payment or subscription identity.",
            fingerprint,
        )

    reconciled_at = payment_case.last_reconciled_at
    if reconciled_at is None:
        return _result(
            EligibilityDecision.WAIT,
            "RECONCILIATION_REQUIRED",
            "Authoritative reconciliation must complete before assessment.",
            fingerprint,
        )

    now = clock()
    if reconciled_at.utcoffset() is None or now.utcoffset() is None:
        return _result(
            EligibilityDecision.REVIEW,
            "MALFORMED_RECONCILIATION_TIMESTAMP",
            "The reconciliation timestamp is not timezone-aware.",
            fingerprint,
        )
    if reconciled_at > now:
        return _result(
            EligibilityDecision.REVIEW,
            "RECONCILIATION_TIMESTAMP_IN_FUTURE",
            "The reconciliation timestamp is later than the assessment clock.",
            fingerprint,
        )
    if now - reconciled_at > RECONCILIATION_FRESHNESS:
        return _result(
            EligibilityDecision.WAIT,
            "RECONCILIATION_STALE",
            "Authoritative financial truth is outside the freshness window.",
            fingerprint,
        )

    payment_status = _normalized(payment_case.razorpay_payment_status)
    subscription_status = _normalized(
        payment_case.razorpay_subscription_status
    )
    if payment_status is not None and subscription_status is not None:
        return _result(
            EligibilityDecision.REVIEW,
            "CONFLICTING_EXTERNAL_STATUSES",
            "The case contains conflicting payment and subscription truth.",
            fingerprint,
        )
    if payment_status is None and subscription_status is None:
        return _result(
            EligibilityDecision.REVIEW,
            "AUTHORITATIVE_STATUS_MISSING",
            "Reconciliation did not produce a usable external status.",
            fingerprint,
        )

    if payment_status is not None:
        if not payment_case.payment_id:
            return _result(
                EligibilityDecision.REVIEW,
                "PAYMENT_IDENTITY_MISSING",
                "Payment truth exists without a payment identity.",
                fingerprint,
            )
        return _assess_payment_status(payment_case, payment_status, fingerprint)

    if not payment_case.subscription_id:
        return _result(
            EligibilityDecision.REVIEW,
            "SUBSCRIPTION_IDENTITY_MISSING",
            "Subscription truth exists without a subscription identity.",
            fingerprint,
        )
    if payment_case.payment_id is not None:
        return _result(
            EligibilityDecision.REVIEW,
            "CONFLICTING_CASE_IDENTITY",
            "A subscription case contains an unexpected payment identity.",
            fingerprint,
        )
    return _assess_subscription_status(
        payment_case,
        subscription_status,
        fingerprint,
    )


def _assess_payment_status(
    payment_case: PaymentCase,
    status: str,
    fingerprint: str,
) -> EligibilityResult:
    if status == "captured":
        return _result(
            EligibilityDecision.STOP,
            "PAYMENT_ALREADY_CAPTURED",
            "The authoritative payment status is captured.",
            fingerprint,
        )
    if status == "refunded":
        return _result(
            EligibilityDecision.STOP,
            "PAYMENT_REFUNDED",
            "The authoritative payment status is refunded.",
            fingerprint,
        )
    if status in {"created", "authorized"}:
        return _result(
            EligibilityDecision.WAIT,
            "PAYMENT_NOT_FINAL",
            "The payment has not reached a final failure state.",
            fingerprint,
        )
    if status == "failed":
        if payment_case.current_state is CaseState.DETECTED:
            return _result(
                EligibilityDecision.REVIEW,
                "CASE_STATE_NOT_RECONCILED",
                "A confirmed failure is not in a reconciled ARC state.",
                fingerprint,
            )
        return _result(
            EligibilityDecision.ELIGIBLE,
            "PAYMENT_FAILURE_CONFIRMED",
            "Authoritative payment failure is eligible for diagnosis.",
            fingerprint,
        )
    return _result(
        EligibilityDecision.REVIEW,
        "UNRECOGNIZED_PAYMENT_STATUS",
        "The authoritative payment status is not recognized.",
        fingerprint,
    )


def _assess_subscription_status(
    payment_case: PaymentCase,
    status: str | None,
    fingerprint: str,
) -> EligibilityResult:
    if status == "pending":
        return _result(
            EligibilityDecision.WAIT,
            "PLATFORM_RETRY_ACTIVE",
            "Razorpay subscription retries remain active.",
            fingerprint,
        )
    if status == "halted":
        if payment_case.current_state is CaseState.DETECTED:
            return _result(
                EligibilityDecision.REVIEW,
                "CASE_STATE_NOT_RECONCILED",
                "A halted subscription is not in a reconciled ARC state.",
                fingerprint,
            )
        return _result(
            EligibilityDecision.ELIGIBLE,
            "SUBSCRIPTION_RETRIES_EXHAUSTED",
            "Automatic subscription retries are exhausted.",
            fingerprint,
        )
    if status == "active":
        return _result(
            EligibilityDecision.STOP,
            "SUBSCRIPTION_ACTIVE",
            "The subscription is active and requires no recovery reasoning.",
            fingerprint,
        )
    if status == "paused":
        return _result(
            EligibilityDecision.WAIT,
            "SUBSCRIPTION_PAUSED",
            "The subscription is paused.",
            fingerprint,
        )
    if status in {"created", "authenticated"}:
        return _result(
            EligibilityDecision.WAIT,
            "SUBSCRIPTION_NOT_RECOVERY_READY",
            "The subscription is not ready for recovery reasoning.",
            fingerprint,
        )
    if status in {"cancelled", "completed", "expired"}:
        return _result(
            EligibilityDecision.STOP,
            "SUBSCRIPTION_TERMINAL",
            "The subscription is in a non-recoverable terminal state.",
            fingerprint,
        )
    return _result(
        EligibilityDecision.REVIEW,
        "UNRECOGNIZED_SUBSCRIPTION_STATUS",
        "The authoritative subscription status is not recognized.",
        fingerprint,
    )


def _result(
    decision: EligibilityDecision,
    reason_code: str,
    explanation: str,
    fingerprint: str,
) -> EligibilityResult:
    return EligibilityResult(
        decision=decision,
        reason_code=reason_code,
        explanation=explanation,
        assessment_fingerprint=fingerprint,
    )
