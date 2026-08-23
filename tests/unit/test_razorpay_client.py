"""Contract tests for the read-only Razorpay REST client."""

import base64
from collections.abc import Callable

import httpx
import pytest

from arc.config import Settings
from arc.integrations.razorpay import (
    RazorpayAuthenticationError,
    RazorpayClient,
    RazorpayConfigurationError,
    RazorpayInvalidResponseError,
    RazorpayNotFoundError,
    RazorpayRateLimitError,
    RazorpayUnavailableError,
)

TEST_KEY_ID = "rzp_test_unit_only"
TEST_KEY_SECRET = "unit_only_secret"


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> RazorpayClient:
    return RazorpayClient(
        key_id=TEST_KEY_ID,
        key_secret=TEST_KEY_SECRET,
        base_url="https://api.razorpay.test",
        transport=httpx.MockTransport(handler),
    )


def _payment_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "pay_current",
        "entity": "payment",
        "status": "failed",
        "amount": 18_501,
        "currency": "inr",
        "customer_id": "cust_current",
        "order_id": "order_current",
        "subscription_id": "sub_current",
        "method": "card",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Payment failed",
        "error_source": "customer",
        "error_step": "payment_authentication",
        "error_reason": "incorrect_otp",
        "created_at": 1_725_000_000,
        "future_field": "ignored",
    }
    payload.update(overrides)
    return payload


def _subscription_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "sub_current",
        "entity": "subscription",
        "status": "pending",
        "customer_id": "cust_current",
        "current_start": 1_725_000_000,
        "current_end": 1_727_592_000,
        "charge_at": 1_725_086_400,
        "paid_count": 2,
        "remaining_count": 4,
        "customer_notify": True,
        "payment_method": "card",
        "created_at": 1_720_000_000,
        "future_field": {"ignored": True},
    }
    payload.update(overrides)
    return payload


def test_fetch_payment_parses_minimal_authoritative_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/payments/pay_current"
        return httpx.Response(200, json=_payment_payload())

    with _client(handler) as client:
        payment = client.fetch_payment("pay_current")

    assert payment.id == "pay_current"
    assert payment.status == "failed"
    assert payment.amount == 18_501
    assert payment.currency == "INR"
    assert payment.subscription_id == "sub_current"
    assert payment.error_reason == "incorrect_otp"


def test_fetch_subscription_parses_minimal_authoritative_fields() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_subscription_payload())

    with _client(handler) as client:
        subscription = client.fetch_subscription("sub_current")

    assert subscription.id == "sub_current"
    assert subscription.status == "pending"
    assert subscription.customer_id == "cust_current"
    assert subscription.paid_count == 2
    assert subscription.remaining_count == 4


def test_basic_auth_is_generated_without_exposing_credentials() -> None:
    observed = {"authenticated": False}
    expected = "Basic " + base64.b64encode(
        f"{TEST_KEY_ID}:{TEST_KEY_SECRET}".encode("ascii")
    ).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authenticated"] = (
            request.headers.get("Authorization") == expected
        )
        return httpx.Response(200, json=_payment_payload())

    with _client(handler) as client:
        client.fetch_payment("pay_current")

    assert observed["authenticated"] is True


def test_authentication_error_is_sanitized() -> None:
    with _client(lambda _request: httpx.Response(401)) as client:
        with pytest.raises(
            RazorpayAuthenticationError,
            match="authentication failed",
        ) as captured:
            client.fetch_payment("pay_current")

    assert TEST_KEY_ID not in str(captured.value)
    assert TEST_KEY_SECRET not in str(captured.value)


def test_not_found_error_is_sanitized() -> None:
    with _client(lambda _request: httpx.Response(404)) as client:
        with pytest.raises(RazorpayNotFoundError, match="not found"):
            client.fetch_payment("pay_missing")


def test_rate_limit_error_is_sanitized() -> None:
    with _client(lambda _request: httpx.Response(429)) as client:
        with pytest.raises(RazorpayRateLimitError, match="rate limit"):
            client.fetch_subscription("sub_current")


def test_server_error_maps_to_unavailable() -> None:
    with _client(lambda _request: httpx.Response(503)) as client:
        with pytest.raises(RazorpayUnavailableError, match="unavailable"):
            client.fetch_payment("pay_current")


def test_timeout_maps_to_unavailable_without_raw_exception() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private transport detail", request=request)

    with _client(timeout) as client:
        with pytest.raises(RazorpayUnavailableError) as captured:
            client.fetch_payment("pay_current")

    assert "private transport detail" not in str(captured.value)


def test_network_error_maps_to_unavailable_without_raw_exception() -> None:
    def disconnect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private network detail", request=request)

    with _client(disconnect) as client:
        with pytest.raises(RazorpayUnavailableError) as captured:
            client.fetch_subscription("sub_current")

    assert "private network detail" not in str(captured.value)


def test_malformed_entity_maps_to_invalid_response() -> None:
    malformed = _payment_payload(amount="18501")
    with _client(
        lambda _request: httpx.Response(200, json=malformed)
    ) as client:
        with pytest.raises(RazorpayInvalidResponseError, match="invalid"):
            client.fetch_payment("pay_current")


def test_new_external_status_is_preserved_for_safe_future_handling() -> None:
    payload = _payment_payload(status="future_status")
    with _client(
        lambda _request: httpx.Response(200, json=payload)
    ) as client:
        payment = client.fetch_payment("pay_current")

    assert payment.status == "future_status"


def test_missing_api_credentials_fail_only_when_client_is_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    settings = Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        _env_file=None,
    )

    assert settings.razorpay_key_id is None
    assert settings.razorpay_key_secret is None
    with pytest.raises(RazorpayConfigurationError, match="not configured"):
        RazorpayClient.from_settings(settings)
