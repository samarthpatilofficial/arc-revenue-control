"""Governed Razorpay Standard Payment Link write and outcome-read client."""

from typing import Any, Literal, Protocol, Self
from urllib.parse import quote

import httpx
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from arc.config import Settings
from arc.domain.enums import ProviderMode
from arc.integrations.razorpay.client import (
    DEFAULT_RAZORPAY_API_BASE_URL,
    DEFAULT_RAZORPAY_TIMEOUT,
)

PAYMENT_LINK_DESCRIPTION = "ARC recovery payment"
PAYMENT_LINK_STATUSES = frozenset(
    {"created", "issued", "partially_paid", "expired", "cancelled", "paid"}
)


class PaymentLinkError(RuntimeError):
    """Base failure whose text and reason code are safe to persist."""

    reason_code = "RAZORPAY_PAYMENT_LINK_ERROR"


class PaymentLinkConfigurationError(PaymentLinkError):
    reason_code = "RAZORPAY_CONFIGURATION_ERROR"


class PaymentLinkAuthenticationError(PaymentLinkError):
    reason_code = "RAZORPAY_AUTHENTICATION_FAILED"


class PaymentLinkRateLimitError(PaymentLinkError):
    reason_code = "RAZORPAY_RATE_LIMITED"


class PaymentLinkRejectedError(PaymentLinkError):
    reason_code = "RAZORPAY_PAYMENT_LINK_REJECTED"


class PaymentLinkUnavailableError(PaymentLinkError):
    reason_code = "RAZORPAY_PAYMENT_LINK_UNAVAILABLE"


class PaymentLinkInvalidResponseError(PaymentLinkError):
    reason_code = "RAZORPAY_PAYMENT_LINK_INVALID_RESPONSE"


class PaymentLinkUncertainError(PaymentLinkInvalidResponseError):
    """Creation may have happened and must be recovered by stable lookup."""

    reason_code = "RAZORPAY_PAYMENT_LINK_OUTCOME_UNCERTAIN"


class PaymentLinkNotification(BaseModel):
    """Notifications are permanently disabled for this executor."""

    model_config = ConfigDict(extra="forbid", strict=True)

    sms: Literal[False] = False
    email: Literal[False] = False


class PaymentLinkCreateRequest(BaseModel):
    """Minimal, PII-free Standard Payment Link creation contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    amount: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    accept_partial: Literal[False] = False
    reference_id: str = Field(min_length=1, max_length=40)
    description: Literal[PAYMENT_LINK_DESCRIPTION] = PAYMENT_LINK_DESCRIPTION
    expire_by: int = Field(gt=0)
    notify: PaymentLinkNotification = Field(
        default_factory=PaymentLinkNotification
    )
    reminder_enable: Literal[False] = False

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class CapturedPaymentProjection(BaseModel):
    """PII-free captured-payment evidence embedded in a Payment Link read."""

    model_config = ConfigDict(extra="ignore", strict=True)

    payment_id: str = Field(min_length=1, max_length=100)
    amount: int = Field(gt=0)
    status: str = Field(min_length=1, max_length=64)
    method: str | None = Field(default=None, max_length=64)
    created_at: int | None = Field(default=None, ge=0)
    payment_link_id: str | None = Field(default=None, max_length=100)

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.strip().lower()


class PaymentLinkSnapshot(BaseModel):
    """Only provider response fields ARC is permitted to retain."""

    model_config = ConfigDict(extra="ignore", strict=True)

    id: str = Field(min_length=1, max_length=100)
    reference_id: str = Field(min_length=1, max_length=40)
    amount: int = Field(gt=0)
    amount_paid: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: str = Field(min_length=1, max_length=64)
    short_url: AnyHttpUrl
    expire_by: int | None = Field(default=None, ge=0)
    expired_at: int | None = Field(default=None, ge=0)
    cancelled_at: int | None = Field(default=None, ge=0)
    updated_at: int | None = Field(default=None, ge=0)
    payments: list[CapturedPaymentProjection] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("payments", mode="before")
    @classmethod
    def normalize_missing_payments(cls, value: object) -> object:
        return [] if value is None else value


class _PaymentLinkCollection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    payment_links: list[PaymentLinkSnapshot] = Field(max_length=100)


class PaymentLinkGateway(Protocol):
    """Narrow Payment Link dependency used by execution and observation."""

    def lookup_by_reference(
        self,
        reference_id: str,
    ) -> list[PaymentLinkSnapshot]: ...

    def create(
        self,
        request: PaymentLinkCreateRequest,
    ) -> PaymentLinkSnapshot: ...

    def cancel(self, payment_link_id: str) -> PaymentLinkSnapshot: ...

    def fetch_by_id(self, payment_link_id: str) -> PaymentLinkSnapshot: ...


class RazorpayPaymentLinkClient:
    """Client exposing lookup, create, safe cancellation, and fetch by id."""

    def __init__(
        self,
        *,
        key_id: SecretStr | str,
        key_secret: SecretStr | str,
        base_url: str = DEFAULT_RAZORPAY_API_BASE_URL,
        timeout: httpx.Timeout | float = DEFAULT_RAZORPAY_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        protected_key_id = (
            key_id if isinstance(key_id, SecretStr) else SecretStr(key_id)
        )
        protected_secret = (
            key_secret
            if isinstance(key_secret, SecretStr)
            else SecretStr(key_secret)
        )
        if (
            not protected_key_id.get_secret_value()
            or not protected_secret.get_secret_value()
        ):
            raise PaymentLinkConfigurationError(
                "Razorpay Payment Link credentials are not configured"
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
        if (
            settings.razorpay_key_id is None
            or settings.razorpay_key_secret is None
        ):
            raise PaymentLinkConfigurationError(
                "Razorpay Payment Link credentials are not configured"
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
        self._http.close()

    def lookup_by_reference(
        self,
        reference_id: str,
    ) -> list[PaymentLinkSnapshot]:
        reference = _bounded_identifier(reference_id, maximum=40)
        response = self._request(
            "GET",
            "/v1/payment_links",
            operation="lookup",
            params={"reference_id": reference},
        )
        try:
            collection = _PaymentLinkCollection.model_validate(response.json())
        except (ValueError, TypeError, ValidationError):
            raise PaymentLinkInvalidResponseError(
                "Razorpay returned an invalid Payment Link lookup"
            ) from None
        return collection.payment_links

    def create(
        self,
        request: PaymentLinkCreateRequest,
    ) -> PaymentLinkSnapshot:
        response = self._request(
            "POST",
            "/v1/payment_links",
            operation="create",
            json=request.model_dump(mode="json"),
        )
        try:
            snapshot = PaymentLinkSnapshot.model_validate(response.json())
        except (ValueError, TypeError, ValidationError):
            raise PaymentLinkUncertainError(
                "Razorpay Payment Link creation returned an uncertain response"
            ) from None
        if (
            snapshot.reference_id != request.reference_id
            or snapshot.amount != request.amount
            or snapshot.currency != request.currency
        ):
            raise PaymentLinkUncertainError(
                "Razorpay Payment Link creation returned mismatched fields"
            )
        return snapshot

    def cancel(self, payment_link_id: str) -> PaymentLinkSnapshot:
        identifier = _bounded_identifier(payment_link_id, maximum=100)
        response = self._request(
            "POST",
            f"/v1/payment_links/{quote(identifier, safe='')}/cancel",
            operation="cancel",
        )
        try:
            snapshot = PaymentLinkSnapshot.model_validate(response.json())
        except (ValueError, TypeError, ValidationError):
            raise PaymentLinkInvalidResponseError(
                "Razorpay returned an invalid Payment Link cancellation"
            ) from None
        if snapshot.id != identifier:
            raise PaymentLinkInvalidResponseError(
                "Razorpay returned a mismatched Payment Link cancellation"
            )
        return snapshot

    def fetch_by_id(self, payment_link_id: str) -> PaymentLinkSnapshot:
        identifier = _bounded_identifier(payment_link_id, maximum=100)
        response = self._request(
            "GET",
            f"/v1/payment_links/{quote(identifier, safe='')}",
            operation="fetch",
        )
        try:
            snapshot = PaymentLinkSnapshot.model_validate(response.json())
        except (ValueError, TypeError, ValidationError):
            raise PaymentLinkInvalidResponseError(
                "Razorpay returned an invalid Payment Link fetch"
            ) from None
        if snapshot.id != identifier:
            raise PaymentLinkInvalidResponseError(
                "Razorpay returned a mismatched Payment Link fetch"
            )
        return snapshot

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: Literal["lookup", "create", "cancel", "fetch"],
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = self._http.request(
                method,
                path,
                params=params,
                json=json,
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            if operation == "create":
                raise PaymentLinkUncertainError(
                    "Razorpay Payment Link creation outcome is uncertain"
                ) from None
            raise PaymentLinkUnavailableError(
                "Razorpay Payment Link API is temporarily unavailable"
            ) from None
        except httpx.RequestError:
            if operation == "create":
                raise PaymentLinkUncertainError(
                    "Razorpay Payment Link creation outcome is uncertain"
                ) from None
            raise PaymentLinkUnavailableError(
                "Razorpay Payment Link request failed safely"
            ) from None

        _raise_for_status(response.status_code, operation=operation)
        return response


def _bounded_identifier(identifier: str, *, maximum: int) -> str:
    normalized = identifier.strip() if isinstance(identifier, str) else ""
    if not normalized or len(normalized) > maximum:
        raise PaymentLinkInvalidResponseError(
            "Razorpay Payment Link identifier is invalid"
        )
    return normalized


def _raise_for_status(
    status_code: int,
    *,
    operation: Literal["lookup", "create", "cancel", "fetch"],
) -> None:
    if 200 <= status_code < 300:
        return
    if status_code in {401, 403}:
        raise PaymentLinkAuthenticationError(
            "Razorpay Payment Link authentication failed"
        )
    if status_code == 429:
        raise PaymentLinkRateLimitError(
            "Razorpay Payment Link rate limit was reached"
        )
    if status_code >= 500:
        if operation == "create":
            raise PaymentLinkUncertainError(
                "Razorpay Payment Link creation outcome is uncertain"
            )
        raise PaymentLinkUnavailableError(
            "Razorpay Payment Link API is temporarily unavailable"
        )
    raise PaymentLinkRejectedError(
        "Razorpay rejected the Payment Link request"
    )


def derive_razorpay_provider_mode(settings: Settings) -> ProviderMode:
    """Derive mode from the private key prefix without retaining the key."""

    if settings.razorpay_key_id is None:
        raise PaymentLinkConfigurationError(
            "Razorpay Payment Link credentials are not configured"
        )
    key_id = settings.razorpay_key_id.get_secret_value()
    if key_id.startswith("rzp_test_"):
        return ProviderMode.TEST
    if key_id.startswith("rzp_live_"):
        return ProviderMode.LIVE
    raise PaymentLinkConfigurationError(
        "Razorpay credential mode could not be determined safely"
    )
