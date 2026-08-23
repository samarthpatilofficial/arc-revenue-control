"""Sanitized application-service errors for webhook reconciliation."""


class WebhookProcessingError(RuntimeError):
    """Base processing error with an operator-safe message."""


class WebhookEventNotFoundError(WebhookProcessingError):
    """Raised when a requested ledger event does not exist."""
