"""Canonical evidence fingerprint for idempotent outcome observation."""

import hashlib
import json
from uuid import UUID

from arc.integrations.razorpay.payment_links import PaymentLinkSnapshot

OUTCOME_OBSERVER_VERSION = "payment-link-outcome-v1"


def build_outcome_evidence_fingerprint(
    recovery_action_id: UUID,
    snapshot: PaymentLinkSnapshot,
) -> str:
    """Hash only normalized provider evidence, never PII or provider URLs."""

    payments = sorted(
        (
            {
                "payment_id": payment.payment_id,
                "amount": payment.amount,
                "status": payment.status,
                "method": payment.method,
                "created_at": payment.created_at,
                "payment_link_id": payment.payment_link_id,
            }
            for payment in snapshot.payments
        ),
        key=lambda item: (
            str(item["payment_id"]),
            int(item["amount"]),
            str(item["status"]),
        ),
    )
    evidence = {
        "observer_version": OUTCOME_OBSERVER_VERSION,
        "recovery_action_id": str(recovery_action_id),
        "payment_link_id": snapshot.id,
        "reference_id": snapshot.reference_id,
        "status": snapshot.status,
        "amount": snapshot.amount,
        "amount_paid": snapshot.amount_paid,
        "currency": snapshot.currency,
        "payments": payments,
        "updated_at": snapshot.updated_at,
        "expire_by": snapshot.expire_by,
        "expired_at": snapshot.expired_at,
        "cancelled_at": snapshot.cancelled_at,
    }
    canonical = json.dumps(
        evidence, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
