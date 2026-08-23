"""Safe normalization of the minimal Razorpay webhook envelope."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SUPPORTED_RAZORPAY_EVENTS = frozenset(
    {
        "payment.failed",
        "payment.captured",
        "subscription.pending",
        "subscription.halted",
    }
)


class InvalidWebhookPayload(ValueError):
    """Raised when signed JSON does not contain a usable webhook envelope."""


@dataclass(frozen=True, slots=True)
class NormalizedWebhookEvent:
    """Minimal metadata extracted without assuming optional entities exist."""

    event_type: str
    account_id: str | None
    payment_id: str | None
    subscription_id: str | None
    customer_id: str | None
    raw_payload: dict[str, Any]

    @property
    def supported(self) -> bool:
        """Return whether ARC recognizes this event for later processing."""

        return self.event_type in SUPPORTED_RAZORPAY_EVENTS


def _entity(payload: Mapping[str, Any], entity_name: str) -> Mapping[str, Any]:
    payload_section = payload.get("payload")
    if not isinstance(payload_section, Mapping):
        return {}
    entity_wrapper = payload_section.get(entity_name)
    if not isinstance(entity_wrapper, Mapping):
        return {}
    entity = entity_wrapper.get("entity")
    if not isinstance(entity, Mapping):
        return {}
    return entity


def _identifier(value: object, *, max_length: int = 100) -> str | None:
    if not isinstance(value, str) or not value or len(value) > max_length:
        return None
    return value


def normalize_webhook_payload(payload: object) -> NormalizedWebhookEvent:
    """Validate the basic envelope and extract identifiers when present."""

    if not isinstance(payload, Mapping):
        raise InvalidWebhookPayload("Webhook JSON must be an object")

    event_type = payload.get("event")
    if not isinstance(event_type, str) or not event_type or len(event_type) > 100:
        raise InvalidWebhookPayload("Webhook event must be a non-empty string")

    payload_section = payload.get("payload")
    if not isinstance(payload_section, Mapping):
        raise InvalidWebhookPayload("Webhook payload must be an object")

    payment = _entity(payload, "payment")
    subscription = _entity(payload, "subscription")
    customer = _entity(payload, "customer")

    customer_id = (
        _identifier(payment.get("customer_id"))
        or _identifier(subscription.get("customer_id"))
        or _identifier(customer.get("id"))
    )

    return NormalizedWebhookEvent(
        event_type=event_type,
        account_id=_identifier(payload.get("account_id")),
        payment_id=_identifier(payment.get("id")),
        subscription_id=(
            _identifier(subscription.get("id"))
            or _identifier(payment.get("subscription_id"))
        ),
        customer_id=customer_id,
        raw_payload=dict(payload),
    )
