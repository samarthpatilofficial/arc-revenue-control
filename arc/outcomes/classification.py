"""Pure fail-safe classification of authoritative Payment Link evidence."""

from dataclasses import dataclass
from uuid import UUID

from arc.domain.enums import RecoveryOutcomeStatus
from arc.integrations.razorpay.payment_links import PaymentLinkSnapshot


@dataclass(frozen=True, slots=True)
class ExpectedPaymentLinkEvidence:
    """Financial and provider identity facts frozen before the external read."""

    recovery_action_id: UUID
    payment_link_id: str
    reference_id: str
    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class OutcomeClassification:
    """Bounded classification with only attribution-relevant payment evidence."""

    outcome_status: RecoveryOutcomeStatus
    reason_code: str
    provider_payment_id: str | None = None
    provider_payment_status: str | None = None


def classify_payment_link_outcome(
    expected: ExpectedPaymentLinkEvidence,
    snapshot: PaymentLinkSnapshot,
) -> OutcomeClassification:
    """Classify exact provider truth; any financial ambiguity requires review."""

    if (
        snapshot.id != expected.payment_link_id
        or snapshot.reference_id != expected.reference_id
        or snapshot.amount != expected.amount_minor
        or snapshot.currency != expected.currency.strip().upper()
    ):
        return _review("RECOVERY_OUTCOME_IDENTITY_OR_AMOUNT_MISMATCH")

    if any(
        payment.payment_link_id is not None
        and payment.payment_link_id != expected.payment_link_id
        for payment in snapshot.payments
    ):
        return _review("RECOVERY_OUTCOME_PAYMENT_LINK_MISMATCH")

    status = snapshot.status
    if status in {"created", "issued"}:
        if snapshot.amount_paid != 0 or snapshot.payments:
            return _review("RECOVERY_OUTCOME_PENDING_EVIDENCE_CONFLICT")
        return OutcomeClassification(
            RecoveryOutcomeStatus.PENDING,
            "RECOVERY_PAYMENT_LINK_PENDING",
        )

    if status == "paid":
        if snapshot.amount_paid != expected.amount_minor:
            return _review("RECOVERY_OUTCOME_AMOUNT_PAID_MISMATCH")
        if len(snapshot.payments) != 1:
            return _review("RECOVERY_OUTCOME_CAPTURE_AMBIGUOUS")
        payment = snapshot.payments[0]
        if (
            payment.status != "captured"
            or payment.amount != expected.amount_minor
        ):
            return _review("RECOVERY_OUTCOME_CAPTURE_MISMATCH")
        return OutcomeClassification(
            RecoveryOutcomeStatus.RECOVERED,
            "RECOVERY_PAYMENT_CAPTURED",
            provider_payment_id=payment.payment_id,
            provider_payment_status=payment.status,
        )

    if status == "expired":
        if snapshot.amount_paid != 0 or snapshot.payments:
            return _review("RECOVERY_OUTCOME_EXPIRED_EVIDENCE_CONFLICT")
        return OutcomeClassification(
            RecoveryOutcomeStatus.EXPIRED,
            "RECOVERY_PAYMENT_LINK_EXPIRED",
        )

    if status == "cancelled":
        if snapshot.amount_paid != 0 or snapshot.payments:
            return _review("RECOVERY_OUTCOME_CANCELLED_EVIDENCE_CONFLICT")
        return OutcomeClassification(
            RecoveryOutcomeStatus.CANCELLED,
            "RECOVERY_PAYMENT_LINK_CANCELLED",
        )

    if status == "partially_paid":
        return _review("RECOVERY_OUTCOME_PARTIAL_PAYMENT_UNSUPPORTED")
    return _review("RECOVERY_OUTCOME_PROVIDER_STATUS_UNKNOWN")


def _review(reason_code: str) -> OutcomeClassification:
    return OutcomeClassification(
        RecoveryOutcomeStatus.REVIEW_REQUIRED,
        reason_code,
    )
