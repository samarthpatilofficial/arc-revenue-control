"""Unit tests for Razorpay raw-body signature verification."""

import hashlib
import hmac

from arc.integrations.razorpay import (
    verify_webhook_signature,
    verify_webhook_signature_with_rotation,
)

CURRENT_SECRET = "unit_test_current_webhook_secret"
PREVIOUS_SECRET = "unit_test_previous_webhook_secret"
RAW_BODY = b'{"event":"payment.failed","payload":{}}'


def _signature(raw_body: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()


def test_valid_hmac_signature() -> None:
    signature = _signature(RAW_BODY, CURRENT_SECRET)

    assert verify_webhook_signature(RAW_BODY, signature, CURRENT_SECRET) is True


def test_invalid_hmac_signature() -> None:
    assert verify_webhook_signature(RAW_BODY, "0" * 64, CURRENT_SECRET) is False


def test_modified_raw_body_fails_signature_verification() -> None:
    signature = _signature(RAW_BODY, CURRENT_SECRET)

    assert (
        verify_webhook_signature(
            RAW_BODY + b" ",
            signature,
            CURRENT_SECRET,
        )
        is False
    )


def test_current_secret_works_during_rotation() -> None:
    signature = _signature(RAW_BODY, CURRENT_SECRET)

    assert (
        verify_webhook_signature_with_rotation(
            RAW_BODY,
            signature,
            CURRENT_SECRET,
            PREVIOUS_SECRET,
        )
        is True
    )


def test_previous_secret_works_during_rotation() -> None:
    signature = _signature(RAW_BODY, PREVIOUS_SECRET)

    assert (
        verify_webhook_signature_with_rotation(
            RAW_BODY,
            signature,
            CURRENT_SECRET,
            PREVIOUS_SECRET,
        )
        is True
    )
