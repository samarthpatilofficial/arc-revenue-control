"""Cryptographic verification and integrity hashing for Razorpay webhooks."""

import hashlib
import hmac


def verify_webhook_signature(
    raw_body: bytes,
    received_signature: str,
    secret: str,
) -> bool:
    """Verify Razorpay's HMAC-SHA256 signature over the exact request bytes."""

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest().encode("ascii")
    try:
        received_signature_bytes = received_signature.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(expected_signature, received_signature_bytes)


def verify_webhook_signature_with_rotation(
    raw_body: bytes,
    received_signature: str,
    current_secret: str,
    previous_secret: str | None = None,
) -> bool:
    """Verify with the current secret and, when configured, the previous secret."""

    current_matches = verify_webhook_signature(
        raw_body,
        received_signature,
        current_secret,
    )
    previous_matches = (
        verify_webhook_signature(
            raw_body,
            received_signature,
            previous_secret,
        )
        if previous_secret
        else False
    )
    return current_matches or previous_matches


def hash_raw_body(raw_body: bytes) -> str:
    """Return the lowercase SHA-256 digest of the exact request bytes."""

    return hashlib.sha256(raw_body).hexdigest()
