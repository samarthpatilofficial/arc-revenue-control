"""Pure strict-classification tests for Payment Link outcome evidence."""

from uuid import uuid4

import pytest

from arc.domain.enums import RecoveryOutcomeStatus
from arc.integrations.razorpay.payment_links import PaymentLinkSnapshot
from arc.outcomes.classification import (
    ExpectedPaymentLinkEvidence,
    classify_payment_link_outcome,
)


def _expected() -> ExpectedPaymentLinkEvidence:
    return ExpectedPaymentLinkEvidence(
        recovery_action_id=uuid4(),
        payment_link_id="plink_arc_test",
        reference_id="arc_0123456789abcdef0123456789abcdef",
        amount_minor=1000,
        currency="INR",
    )


def _snapshot(**overrides: object) -> PaymentLinkSnapshot:
    values: dict[str, object] = {
        "id": "plink_arc_test",
        "reference_id": "arc_0123456789abcdef0123456789abcdef",
        "amount": 1000,
        "amount_paid": 0,
        "currency": "INR",
        "status": "created",
        "short_url": "https://rzp.io/i/not-persisted",
        "expire_by": 1_800_000_000,
        "payments": [],
    }
    values.update(overrides)
    return PaymentLinkSnapshot.model_validate(values)


@pytest.mark.parametrize("status", ["created", "issued"])
def test_open_link_is_pending(status: str) -> None:
    result = classify_payment_link_outcome(
        _expected(), _snapshot(status=status)
    )

    assert result.outcome_status is RecoveryOutcomeStatus.PENDING


def test_exact_paid_evidence_is_recovered_candidate() -> None:
    result = classify_payment_link_outcome(
        _expected(),
        _snapshot(
            status="paid",
            amount_paid=1000,
            payments=[
                {
                    "payment_id": "pay_exact",
                    "amount": 1000,
                    "status": "captured",
                }
            ],
        ),
    )

    assert result.outcome_status is RecoveryOutcomeStatus.RECOVERED
    assert result.provider_payment_id == "pay_exact"


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": 999},
        {"reference_id": "arc_wrong"},
        {"id": "plink_wrong"},
        {"status": "paid", "amount_paid": 999},
        {"status": "paid", "amount_paid": 1000, "payments": []},
        {
            "status": "paid",
            "amount_paid": 1000,
            "payments": [
                {"payment_id": "pay_one", "amount": 1000, "status": "captured"},
                {"payment_id": "pay_two", "amount": 1000, "status": "captured"},
            ],
        },
        {"status": "partially_paid", "amount_paid": 400},
        {"status": "future_provider_state"},
    ],
)
def test_ambiguous_or_inconsistent_evidence_requires_review(
    overrides: dict[str, object],
) -> None:
    result = classify_payment_link_outcome(
        _expected(), _snapshot(**overrides)
    )

    assert result.outcome_status is RecoveryOutcomeStatus.REVIEW_REQUIRED


def test_expired_zero_paid_is_expired() -> None:
    result = classify_payment_link_outcome(
        _expected(), _snapshot(status="expired")
    )

    assert result.outcome_status is RecoveryOutcomeStatus.EXPIRED


def test_cancelled_zero_paid_is_cancelled() -> None:
    result = classify_payment_link_outcome(
        _expected(), _snapshot(status="cancelled")
    )

    assert result.outcome_status is RecoveryOutcomeStatus.CANCELLED


def test_cancelled_with_captured_evidence_requires_review() -> None:
    result = classify_payment_link_outcome(
        _expected(),
        _snapshot(
            status="cancelled",
            amount_paid=1000,
            payments=[
                {
                    "payment_id": "pay_conflict",
                    "amount": 1000,
                    "status": "captured",
                }
            ],
        ),
    )

    assert result.outcome_status is RecoveryOutcomeStatus.REVIEW_REQUIRED
