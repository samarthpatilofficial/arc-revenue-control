"""Razorpay webhook and read-only REST integration primitives."""

from arc.integrations.razorpay.client import (
    RECOGNIZED_PAYMENT_STATUSES,
    RECOGNIZED_SUBSCRIPTION_STATUSES,
    PaymentSnapshot,
    RazorpayAuthenticationError,
    RazorpayClient,
    RazorpayClientError,
    RazorpayConfigurationError,
    RazorpayEntityReader,
    RazorpayInvalidResponseError,
    RazorpayNotFoundError,
    RazorpayRateLimitError,
    RazorpayUnavailableError,
    SubscriptionSnapshot,
)

from arc.integrations.razorpay.webhook_payload import (
    SUPPORTED_RAZORPAY_EVENTS,
    InvalidWebhookPayload,
    NormalizedWebhookEvent,
    normalize_webhook_payload,
)
from arc.integrations.razorpay.webhook_security import (
    hash_raw_body,
    verify_webhook_signature,
    verify_webhook_signature_with_rotation,
)

__all__ = [
    "RECOGNIZED_PAYMENT_STATUSES",
    "RECOGNIZED_SUBSCRIPTION_STATUSES",
    "SUPPORTED_RAZORPAY_EVENTS",
    "InvalidWebhookPayload",
    "NormalizedWebhookEvent",
    "PaymentSnapshot",
    "RazorpayAuthenticationError",
    "RazorpayClient",
    "RazorpayClientError",
    "RazorpayConfigurationError",
    "RazorpayEntityReader",
    "RazorpayInvalidResponseError",
    "RazorpayNotFoundError",
    "RazorpayRateLimitError",
    "RazorpayUnavailableError",
    "SubscriptionSnapshot",
    "hash_raw_body",
    "normalize_webhook_payload",
    "verify_webhook_signature",
    "verify_webhook_signature_with_rotation",
]
