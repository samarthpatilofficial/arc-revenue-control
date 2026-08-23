"""Read-only Razorpay REST client for authoritative entity reconciliation."""

from collections.abc import Callable
from typing import Any, Protocol, Self, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from arc.config import Settings

DEFAULT_RAZORPAY_API_BASE_URL = "https://api.razorpay.com"
DEFAULT_RAZORPAY_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

RECOGNIZED_PAYMENT_STATUSES = frozenset(
    {"created", "authorized", "captured", "refunded", "failed"}
)
RECOGNIZED_SUBSCRIPTION_STATUSES = frozenset(
    {
        "created",
        "authenticated",
        "active",
        "pending",
        "halted",
        "paused",
        "cancelled",
        "completed",
        "expired",
    }
)


class RazorpayClientError(RuntimeError):
    """Base error whose message is safe to persist or show to an operator."""


class RazorpayConfigurationError(RazorpayClientError):
    """Raised when read API credentials are not configured."""


class RazorpayAuthenticationError(RazorpayClientError):
    """Raised when Razorpay rejects the configured API credentials."""


class RazorpayNotFoundError(RazorpayClientError):
    """Raised when the requested Razorpay entity does not exist."""


class RazorpayRateLimitError(RazorpayClientError):
    """Raised when Razorpay throttles a read request."""


class RazorpayUnavailableError(RazorpayClientError):
    """Raised for timeouts, network failures, and upstream server errors."""


class RazorpayInvalidResponseError(RazorpayClientError):
    """Raised when a response cannot be safely interpreted."""


class _RazorpayEntity(BaseModel):
    """Common strict response behavior while tolerating new optional fields."""

    model_config = ConfigDict(extra="ignore", strict=True)

    id: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=64)

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        """Normalize documented status spelling without imposing an allowlist."""

        return value.strip().lower()


class PaymentSnapshot(_RazorpayEntity):
    """Minimal payment fields ARC consumes during reconciliation."""

    amount: int = Field(ge=0)
    currency: str = Field(min_length=1, max_length=3)
    customer_id: str | None = Field(default=None, max_length=100)
    order_id: str | None = Field(default=None, max_length=100)
    subscription_id: str | None = Field(default=None, max_length=100)
    method: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=100)
    error_description: str | None = None
    error_source: str | None = Field(default=None, max_length=100)
    error_step: str | None = Field(default=None, max_length=100)
    error_reason: str | None = Field(default=None, max_length=100)
    created_at: int | None = Field(default=None, ge=0)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class SubscriptionSnapshot(_RazorpayEntity):
    """Minimal subscription fields ARC consumes during reconciliation."""

    customer_id: str | None = Field(default=None, max_length=100)
    current_start: int | None = Field(default=None, ge=0)
    current_end: int | None = Field(default=None, ge=0)
    charge_at: int | None = Field(default=None, ge=0)
    paid_count: int | None = Field(default=None, ge=0)
    remaining_count: int | None = Field(default=None, ge=0)
    customer_notify: bool | None = None
    payment_method: str | None = Field(default=None, max_length=64)
    created_at: int | None = Field(default=None, ge=0)


EntitySnapshot = TypeVar(
    "EntitySnapshot",
    PaymentSnapshot,
    SubscriptionSnapshot,
)


class RazorpayEntityReader(Protocol):
    """Small dependency boundary used by the reconciliation service."""

    def fetch_payment(self, payment_id: str) -> PaymentSnapshot: ...

    def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot: ...


class RazorpayClient:
    """Authenticated client exposing only the two approved GET operations."""

    def __init__(
        self,
        *,
        key_id: SecretStr | str,
        key_secret: SecretStr | str,
        base_url: str = DEFAULT_RAZORPAY_API_BASE_URL,
        timeout: httpx.Timeout | float = DEFAULT_RAZORPAY_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        protected_key_id = key_id if isinstance(key_id, SecretStr) else SecretStr(key_id)
        protected_secret = (
            key_secret if isinstance(key_secret, SecretStr) else SecretStr(key_secret)
        )
        if not protected_key_id.get_secret_value() or not protected_secret.get_secret_value():
            raise RazorpayConfigurationError(
                "Razorpay read API credentials are not configured"
            )

        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=httpx.BasicAuth(
                protected_key_id.get_secret_value(),
                protected_secret.get_secret_value(),
            ),
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> Self:
        """Build a client without making credentials mandatory at app startup."""

        if settings.razorpay_key_id is None or settings.razorpay_key_secret is None:
            raise RazorpayConfigurationError(
                "Razorpay read API credentials are not configured"
            )
        return cls(
            key_id=settings.razorpay_key_id,
            key_secret=settings.razorpay_key_secret,
            base_url=str(settings.razorpay_api_base_url),
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the underlying connection pool."""

        self._http.close()

    def fetch_payment(self, payment_id: str) -> PaymentSnapshot:
        """Fetch current payment truth without modifying the payment."""

        return self._get_entity(
            f"/v1/payments/{_encoded_identifier(payment_id)}",
            PaymentSnapshot.model_validate,
        )

    def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        """Fetch current subscription truth without modifying the subscription."""

        return self._get_entity(
            f"/v1/subscriptions/{_encoded_identifier(subscription_id)}",
            SubscriptionSnapshot.model_validate,
        )

    def _get_entity(
        self,
        path: str,
        parser: Callable[[Any], EntitySnapshot],
    ) -> EntitySnapshot:
        try:
            response = self._http.get(path)
        except (httpx.TimeoutException, httpx.NetworkError):
            raise RazorpayUnavailableError(
                "Razorpay read API is temporarily unavailable"
            ) from None
        except httpx.RequestError:
            raise RazorpayUnavailableError(
                "Razorpay read API request failed"
            ) from None

        _raise_for_status(response.status_code)
        try:
            payload = response.json()
            return parser(payload)
        except (ValueError, ValidationError, TypeError):
            raise RazorpayInvalidResponseError(
                "Razorpay returned an invalid entity response"
            ) from None


def _encoded_identifier(identifier: str) -> str:
    if not identifier or len(identifier) > 100:
        raise RazorpayInvalidResponseError("Razorpay entity identifier is invalid")
    return quote(identifier, safe="")


def _raise_for_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code in {401, 403}:
        raise RazorpayAuthenticationError(
            "Razorpay read API authentication failed"
        )
    if status_code == 404:
        raise RazorpayNotFoundError("Razorpay entity was not found")
    if status_code == 429:
        raise RazorpayRateLimitError("Razorpay read API rate limit was reached")
    if status_code >= 500:
        raise RazorpayUnavailableError(
            "Razorpay read API is temporarily unavailable"
        )
    raise RazorpayInvalidResponseError(
        "Razorpay rejected the entity read request"
    )
