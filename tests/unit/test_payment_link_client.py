"""Offline contract tests for the write-scoped Razorpay Payment Link client."""

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from arc.integrations.razorpay.payment_links import (
    PaymentLinkAuthenticationError,
    PaymentLinkCreateRequest,
    PaymentLinkInvalidResponseError,
    PaymentLinkRateLimitError,
    PaymentLinkRejectedError,
    PaymentLinkUncertainError,
    PaymentLinkUnavailableError,
    RazorpayPaymentLinkClient,
)


def _payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "plink_test_123",
        "reference_id": "arc_0123456789abcdef0123456789abcdef",
        "amount": 1000,
        "currency": "INR",
        "status": "created",
        "short_url": "https://rzp.io/i/test123",
        "expire_by": 1_800_000_000,
    }
    values.update(overrides)
    return values


def _request(**overrides: object) -> PaymentLinkCreateRequest:
    values: dict[str, object] = {
        "amount": 1000,
        "currency": "INR",
        "reference_id": "arc_0123456789abcdef0123456789abcdef",
        "expire_by": 1_800_000_000,
    }
    values.update(overrides)
    return PaymentLinkCreateRequest.model_validate(values)


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> RazorpayPaymentLinkClient:
    return RazorpayPaymentLinkClient(
        key_id="rzp_test_ci_only",
        key_secret="ci_only_secret",
        transport=httpx.MockTransport(handler),
    )


def test_create_uses_exact_endpoint_minimal_fields_and_basic_auth() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["authorization"] = request.headers.get("authorization")
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json=_payload())

    with _client(handler) as client:
        result = client.create(_request())

    assert observed["method"] == "POST"
    assert observed["path"] == "/v1/payment_links"
    assert str(observed["authorization"]).startswith("Basic ")
    assert observed["body"] == {
        "amount": 1000,
        "currency": "INR",
        "accept_partial": False,
        "reference_id": "arc_0123456789abcdef0123456789abcdef",
        "description": "ARC recovery payment",
        "expire_by": 1_800_000_000,
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
    }
    assert result.id == "plink_test_123"


def test_create_request_excludes_customer_pii_and_internal_context() -> None:
    body = _request().model_dump(mode="json")

    assert set(body).isdisjoint(
        {
            "customer",
            "customer_id",
            "name",
            "phone",
            "contact",
            "email",
            "payment_id",
            "subscription_id",
            "account_id",
            "notes",
        }
    )


def test_notifications_reminders_and_partial_payment_are_disabled() -> None:
    request = _request()

    assert request.accept_partial is False
    assert request.notify.sms is False
    assert request.notify.email is False
    assert request.reminder_enable is False


def test_reference_id_is_bounded_to_40_characters() -> None:
    assert len(_request().reference_id) == 36
    with pytest.raises(ValidationError):
        _request(reference_id="x" * 41)


def test_lookup_filters_by_reference_id() -> None:
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["reference_id"] = request.url.params["reference_id"]
        return httpx.Response(200, json={"payment_links": [_payload()]})

    with _client(handler) as client:
        links = client.lookup_by_reference(_request().reference_id)

    assert observed == {
        "method": "GET",
        "path": "/v1/payment_links",
        "reference_id": _request().reference_id,
    }
    assert [link.id for link in links] == ["plink_test_123"]


def test_cancel_uses_bounded_cancellation_endpoint() -> None:
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        return httpx.Response(
            200,
            json=_payload(status="cancelled"),
        )

    with _client(handler) as client:
        result = client.cancel("plink_test_123")

    assert observed == {
        "method": "POST",
        "path": "/v1/payment_links/plink_test_123/cancel",
    }
    assert result.status == "cancelled"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_are_sanitized(status: int) -> None:
    with _client(
        lambda _request: httpx.Response(
            status,
            json={"error": {"description": "raw provider detail"}},
        )
    ) as client:
        with pytest.raises(
            PaymentLinkAuthenticationError,
            match="authentication failed",
        ) as error:
            client.lookup_by_reference(_request().reference_id)

    assert "raw provider detail" not in str(error.value)
    assert "ci_only_secret" not in str(error.value)


def test_rate_limit_is_sanitized() -> None:
    with _client(lambda _request: httpx.Response(429)) as client:
        with pytest.raises(PaymentLinkRateLimitError, match="rate limit"):
            client.create(_request())


def test_provider_5xx_on_lookup_is_unavailable() -> None:
    with _client(lambda _request: httpx.Response(503)) as client:
        with pytest.raises(PaymentLinkUnavailableError, match="unavailable"):
            client.lookup_by_reference(_request().reference_id)


def test_provider_5xx_on_create_is_uncertain() -> None:
    with _client(lambda _request: httpx.Response(503)) as client:
        with pytest.raises(PaymentLinkUncertainError, match="uncertain"):
            client.create(_request())


def test_timeout_on_create_is_uncertain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with _client(handler) as client:
        with pytest.raises(PaymentLinkUncertainError, match="uncertain"):
            client.create(_request())


def test_timeout_on_lookup_does_not_authorize_create() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("synthetic timeout", request=request)

    with _client(handler) as client:
        with pytest.raises(PaymentLinkUnavailableError, match="unavailable"):
            client.lookup_by_reference(_request().reference_id)


def test_definite_4xx_is_rejected_without_raw_body() -> None:
    with _client(
        lambda _request: httpx.Response(
            400,
            json={"error": {"description": "internal raw rejection"}},
        )
    ) as client:
        with pytest.raises(PaymentLinkRejectedError) as error:
            client.create(_request())

    assert "internal raw rejection" not in str(error.value)


def test_malformed_creation_response_is_uncertain() -> None:
    with _client(lambda _request: httpx.Response(200, json={"id": 42})) as client:
        with pytest.raises(PaymentLinkUncertainError):
            client.create(_request())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reference_id", "arc_other_reference"),
        ("amount", 999),
        ("currency", "USD"),
    ],
)
def test_mismatched_creation_fields_are_uncertain(
    field: str,
    value: object,
) -> None:
    with _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(**{field: value}),
        )
    ) as client:
        with pytest.raises(PaymentLinkUncertainError, match="mismatched"):
            client.create(_request())


def test_malformed_lookup_response_is_rejected() -> None:
    with _client(
        lambda _request: httpx.Response(200, json={"payment_links": "bad"})
    ) as client:
        with pytest.raises(PaymentLinkInvalidResponseError):
            client.lookup_by_reference(_request().reference_id)
