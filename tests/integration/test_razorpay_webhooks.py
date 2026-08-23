"""PostgreSQL-backed API tests for secure Razorpay webhook ingress."""

import hashlib
import hmac
import json
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from arc.config import Settings
from arc.db.session import get_db_session
from arc.domain.enums import EventProcessingStatus
from arc.domain.models import WebhookEvent
from arc.integrations.razorpay import hash_raw_body
from services.api.main import create_app

TEST_WEBHOOK_SECRET = "ci_only_webhook_secret_for_integration_tests"
TEST_PREVIOUS_WEBHOOK_SECRET = "ci_only_previous_webhook_secret"


def _payload(
    event_type: str,
    *,
    include_identifiers: bool = True,
    delivery: int = 1,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entity": "event",
        "event": event_type,
        "contains": [],
        "payload": {},
        "created_at": 1_725_000_000,
        "delivery": delivery,
    }
    if include_identifiers:
        payload["account_id"] = "acc_test"
        if event_type.startswith("payment."):
            payload["contains"] = ["payment"]
            payload["payload"] = {
                "payment": {
                    "entity": {
                        "id": "pay_test",
                        "entity": "payment",
                        "customer_id": "cust_test",
                    }
                }
            }
        elif event_type.startswith("subscription."):
            payload["contains"] = ["subscription"]
            payload["payload"] = {
                "subscription": {
                    "entity": {
                        "id": "sub_test",
                        "entity": "subscription",
                        "customer_id": "cust_test",
                    }
                }
            }
        elif event_type.startswith("payment_link."):
            payload["contains"] = ["payment_link"]
            payload["payload"] = {
                "payment_link": {
                    "entity": {
                        "id": "plink_test",
                        "reference_id": "arc_test_reference",
                        "status": event_type.removeprefix("payment_link."),
                    }
                }
            }
    return payload


def _raw_body(
    event_type: str,
    *,
    include_identifiers: bool = True,
    delivery: int = 1,
) -> bytes:
    return json.dumps(
        _payload(
            event_type,
            include_identifiers=include_identifiers,
            delivery=delivery,
        ),
        separators=(",", ":"),
    ).encode("utf-8")


def _signature(raw_body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()


def _headers(
    raw_body: bytes,
    event_id: str = "evt_test",
    secret: str = TEST_WEBHOOK_SECRET,
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": _signature(raw_body, secret),
        "x-razorpay-event-id": event_id,
    }


@pytest.fixture
def webhook_client(
    migrated_engine: Engine,
    db_session: Session,
) -> Generator[TestClient, None, None]:
    del db_session  # The fixture safely clears the PostgreSQL test tables.
    settings = Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        environment="test",
        razorpay_webhook_secret=TEST_WEBHOOK_SECRET,
        razorpay_webhook_previous_secret=TEST_PREVIOUS_WEBHOOK_SECRET,
    )
    application = create_app(settings)

    def override_db_session() -> Generator[Session, None, None]:
        with Session(migrated_engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session
    with TestClient(application) as client:
        yield client


def _stored_event(engine: Engine, event_id: str) -> WebhookEvent | None:
    with Session(engine, expire_on_commit=False) as session:
        return session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.razorpay_event_id == event_id
            )
        )


def _stored_count(engine: Engine) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count()).select_from(WebhookEvent)
        ) or 0


def test_valid_signed_payment_failed_inserts_once(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("payment.failed")

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_payment_failed"),
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "duplicate": False,
        "event_id": "evt_payment_failed",
    }
    stored = _stored_event(migrated_engine, "evt_payment_failed")
    assert stored is not None
    assert stored.event_type == "payment.failed"
    assert stored.account_id == "acc_test"
    assert stored.payment_id == "pay_test"
    assert stored.customer_id == "cust_test"
    assert stored.processing_status is EventProcessingStatus.RECEIVED


def test_valid_signed_payment_link_paid_is_accepted_for_processing(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("payment_link.paid")

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_payment_link_paid"),
    )

    assert response.status_code == 202
    stored = _stored_event(migrated_engine, "evt_payment_link_paid")
    assert stored is not None
    assert stored.event_type == "payment_link.paid"
    assert stored.processing_status is EventProcessingStatus.RECEIVED


def test_duplicate_delivery_succeeds_and_stores_one_event(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("payment.failed")
    headers = _headers(body, "evt_duplicate")

    first = webhook_client.post("/webhooks/razorpay", content=body, headers=headers)
    duplicate = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=headers,
    )

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert _stored_count(migrated_engine) == 1


def test_same_event_id_with_different_body_returns_conflict(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    original_body = _raw_body("payment.failed", delivery=1)
    changed_body = _raw_body("payment.failed", delivery=2)

    first = webhook_client.post(
        "/webhooks/razorpay",
        content=original_body,
        headers=_headers(original_body, "evt_integrity"),
    )
    conflict = webhook_client.post(
        "/webhooks/razorpay",
        content=changed_body,
        headers=_headers(changed_body, "evt_integrity"),
    )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert _stored_count(migrated_engine) == 1
    stored = _stored_event(migrated_engine, "evt_integrity")
    assert stored is not None
    assert stored.raw_body_sha256 == hash_raw_body(original_body)
    assert stored.raw_payload["delivery"] == 1


def test_invalid_signature_creates_no_ledger_row(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("payment.failed")
    headers = _headers(body, "evt_invalid_signature")
    headers["X-Razorpay-Signature"] = "0" * 64

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=headers,
    )

    assert response.status_code == 401
    assert _stored_count(migrated_engine) == 0


def test_missing_signature_creates_no_ledger_row(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("payment.failed")

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-razorpay-event-id": "evt_missing_signature",
        },
    )

    assert response.status_code == 401
    assert _stored_count(migrated_engine) == 0


def test_missing_event_id_creates_no_ledger_row(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("payment.failed")

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": _signature(body),
        },
    )

    assert response.status_code == 400
    assert _stored_count(migrated_engine) == 0


def test_malformed_json_creates_no_ledger_row(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = b'{"event":"payment.failed","payload":'

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_malformed"),
    )

    assert response.status_code == 400
    assert _stored_count(migrated_engine) == 0


@pytest.mark.parametrize(
    "event_type",
    [
        "payment.captured",
        "subscription.pending",
        "subscription.halted",
    ],
)
def test_other_supported_events_are_accepted(
    webhook_client: TestClient,
    migrated_engine: Engine,
    event_type: str,
) -> None:
    event_id = f"evt_{event_type.replace('.', '_')}"
    body = _raw_body(event_type)

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, event_id),
    )

    assert response.status_code == 202
    stored = _stored_event(migrated_engine, event_id)
    assert stored is not None
    assert stored.event_type == event_type
    assert stored.processing_status is EventProcessingStatus.RECEIVED
    if event_type.startswith("subscription."):
        assert stored.subscription_id == "sub_test"


def test_unknown_signed_event_is_persisted_as_unsupported(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("refund.failed", include_identifiers=False)

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_unsupported"),
    )

    assert response.status_code == 202
    stored = _stored_event(migrated_engine, "evt_unsupported")
    assert stored is not None
    assert stored.processing_status is EventProcessingStatus.UNSUPPORTED


def test_raw_body_hash_matches_exact_received_bytes(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = b'{\n  "event": "payment.failed", "payload": {}\n}'

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_exact_body"),
    )

    assert response.status_code == 202
    stored = _stored_event(migrated_engine, "evt_exact_body")
    assert stored is not None
    assert stored.raw_body_sha256 == hashlib.sha256(body).hexdigest()


def test_parsed_json_round_trips_to_jsonb(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    expected_payload = _payload("payment.failed")
    body = json.dumps(expected_payload, indent=2).encode("utf-8")

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_json_round_trip"),
    )

    assert response.status_code == 202
    stored = _stored_event(migrated_engine, "evt_json_round_trip")
    assert stored is not None
    assert stored.raw_payload == expected_payload


def test_optional_identifiers_can_be_absent(
    webhook_client: TestClient,
    migrated_engine: Engine,
) -> None:
    body = _raw_body("payment.failed", include_identifiers=False)

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_no_identifiers"),
    )

    assert response.status_code == 202
    stored = _stored_event(migrated_engine, "evt_no_identifiers")
    assert stored is not None
    assert stored.account_id is None
    assert stored.payment_id is None
    assert stored.subscription_id is None
    assert stored.customer_id is None


def test_endpoint_response_does_not_expose_secret_or_payload(
    webhook_client: TestClient,
) -> None:
    body = json.dumps(
        {
            "event": "payment.failed",
            "payload": {},
            "sensitive_marker": "must_not_be_echoed",
        }
    ).encode("utf-8")

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(body, "evt_minimal_response"),
    )

    assert response.status_code == 202
    response_text = response.text
    assert TEST_WEBHOOK_SECRET not in response_text
    assert "must_not_be_echoed" not in response_text
    assert "payload" not in response_text


def test_previous_secret_is_accepted_by_endpoint(
    webhook_client: TestClient,
) -> None:
    body = _raw_body("payment.failed")

    response = webhook_client.post(
        "/webhooks/razorpay",
        content=body,
        headers=_headers(
            body,
            "evt_previous_secret",
            TEST_PREVIOUS_WEBHOOK_SECRET,
        ),
    )

    assert response.status_code == 202


def test_database_failure_returns_generic_server_error() -> None:
    class FailingSession:
        rolled_back = False

        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("statement", {}, Exception("unavailable"))

        def rollback(self) -> None:
            self.rolled_back = True

    failing_session = FailingSession()
    settings = Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        environment="test",
        razorpay_webhook_secret=TEST_WEBHOOK_SECRET,
    )
    application = create_app(settings)

    def override_db_session() -> Generator[FailingSession, None, None]:
        yield failing_session

    application.dependency_overrides[get_db_session] = override_db_session
    body = _raw_body("payment.failed")
    with TestClient(application) as client:
        response = client.post(
            "/webhooks/razorpay",
            content=body,
            headers=_headers(body, "evt_database_failure"),
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Webhook persistence unavailable"}
    assert failing_session.rolled_back is True
    assert TEST_WEBHOOK_SECRET not in response.text
