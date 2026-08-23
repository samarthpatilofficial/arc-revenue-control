"""PostgreSQL integration tests for ARC's core persistence schema."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arc.domain.enums import CaseState, EventProcessingStatus
from arc.domain.models import CaseEvent, MerchantPolicy, PaymentCase, WebhookEvent
from arc.integrations.razorpay import hash_raw_body
from arc.persistence import (
    RecordEventResult,
    append_case_event,
    create_merchant_policy,
    create_payment_case,
    hash_payload,
    record_event_once,
)


def _new_payment_case(*, attempt_count: int = 0, amount: int = 18_500) -> PaymentCase:
    return PaymentCase(
        case_reference=f"case_{uuid4().hex}",
        merchant_id="merchant_test",
        payment_id=f"pay_{uuid4().hex}",
        amount=amount,
        currency="INR",
        current_state=CaseState.DETECTED,
        attempt_count=attempt_count,
    )


def _record_event(
    session: Session,
    *,
    event_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> RecordEventResult:
    event_payload = payload or {"event": "payment.failed"}
    raw_body = json.dumps(event_payload, separators=(",", ":")).encode("utf-8")
    return record_event_once(
        session,
        razorpay_event_id=event_id or f"evt_{uuid4().hex}",
        event_type="payment.failed",
        account_id="account_test",
        payment_id=f"pay_{uuid4().hex}",
        raw_payload=event_payload,
        raw_body_sha256=hash_raw_body(raw_body),
        signature_verified=True,
    )


def test_migration_creates_expected_schema(migrated_engine: Engine) -> None:
    database_inspector = inspect(migrated_engine)
    expected_tables = {
        "webhook_events",
        "payment_cases",
        "case_events",
        "merchant_policies",
    }

    assert expected_tables.issubset(database_inspector.get_table_names())

    webhook_columns = {
        column["name"]: column
        for column in database_inspector.get_columns("webhook_events")
    }
    assert isinstance(webhook_columns["raw_payload"]["type"], JSONB)
    assert webhook_columns["received_at"]["type"].timezone is True
    assert webhook_columns["raw_body_sha256"]["nullable"] is True
    assert webhook_columns["processing_started_at"]["type"].timezone is True
    assert webhook_columns["processing_started_at"]["nullable"] is True
    assert webhook_columns["processing_attempt_count"]["nullable"] is False
    assert str(webhook_columns["processing_attempt_count"]["default"]) == "0"

    webhook_checks = {
        constraint["name"]
        for constraint in database_inspector.get_check_constraints(
            "webhook_events"
        )
    }
    assert "ck_webhook_events_raw_body_sha256_hex" in webhook_checks
    assert (
        "ck_webhook_events_processing_attempt_count_non_negative"
        in webhook_checks
    )

    payment_case_columns = {
        column["name"]: column
        for column in database_inspector.get_columns("payment_cases")
    }
    assert payment_case_columns["razorpay_payment_status"]["nullable"] is True
    assert payment_case_columns["razorpay_subscription_status"]["nullable"] is True

    webhook_indexes = {
        index["name"] for index in database_inspector.get_indexes("webhook_events")
    }
    assert "ix_webhook_events_event_type" in webhook_indexes
    assert "ix_webhook_events_received_at" in webhook_indexes


def test_webhook_event_can_be_inserted(db_session: Session) -> None:
    result = _record_event(db_session)
    db_session.commit()

    assert result.inserted is True
    assert result.duplicate is False
    assert result.event.processing_status is EventProcessingStatus.RECEIVED
    assert result.event.payload_hash == hash_payload(result.event.raw_payload)
    assert result.event.raw_body_sha256 is not None


def test_duplicate_event_is_stored_exactly_once_without_overwrite(
    db_session: Session,
) -> None:
    event_id = f"evt_{uuid4().hex}"
    original_payload = {"event": "payment.failed", "version": 1}
    first = _record_event(db_session, event_id=event_id, payload=original_payload)
    db_session.commit()

    duplicate = _record_event(
        db_session,
        event_id=event_id,
        payload={"event": "payment.failed", "version": 2},
    )
    db_session.commit()

    stored_count = db_session.scalar(
        select(func.count())
        .select_from(WebhookEvent)
        .where(WebhookEvent.razorpay_event_id == event_id)
    )
    assert first.event.id == duplicate.event.id
    assert duplicate.inserted is False
    assert duplicate.duplicate is True
    assert duplicate.integrity_mismatch is True
    assert stored_count == 1
    assert duplicate.event.raw_payload == original_payload


def test_duplicate_handling_leaves_transaction_usable(db_session: Session) -> None:
    event_id = f"evt_{uuid4().hex}"
    _record_event(db_session, event_id=event_id)
    duplicate = _record_event(db_session, event_id=event_id)

    payment_case = create_payment_case(db_session, _new_payment_case())
    db_session.commit()

    assert duplicate.duplicate is True
    assert db_session.get(PaymentCase, payment_case.id) is not None


def test_json_payload_round_trips(db_session: Session) -> None:
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "amount": 18_500,
                    "notes": ["synthetic", "integration-test"],
                }
            }
        },
    }
    result = _record_event(db_session, payload=payload)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(WebhookEvent, result.event.id)
    assert stored is not None
    assert stored.raw_payload == payload


def test_payment_case_persists_integer_minor_units(db_session: Session) -> None:
    payment_case = create_payment_case(
        db_session,
        _new_payment_case(amount=18_501),
    )
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(PaymentCase, payment_case.id)
    assert stored is not None
    assert stored.amount == 18_501
    assert isinstance(stored.amount, int)


def test_negative_attempt_count_is_rejected(db_session: Session) -> None:
    db_session.add(_new_payment_case(attempt_count=-1))

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(PaymentCase)) == 0


def test_negative_webhook_processing_attempt_count_is_rejected(
    db_session: Session,
) -> None:
    result = _record_event(db_session)
    result.event.processing_attempt_count = -1

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_case_event_requires_existing_case(db_session: Session) -> None:
    db_session.add(
        CaseEvent(
            case_id=uuid4(),
            event_type="CASE_DETECTED",
            source="SYSTEM",
            event_data={},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_merchant_policy_requires_unique_merchant_id(db_session: Session) -> None:
    first = MerchantPolicy(
        merchant_id="merchant_unique",
        automation_enabled=True,
        allowed_actions=["WAIT"],
        max_automated_attempts=2,
        max_contact_attempts=1,
        recovery_window_minutes=1_440,
        high_value_threshold_minor=100_000,
        stopping_rules={"stop_when_paid": True},
    )
    create_merchant_policy(db_session, first)
    db_session.commit()

    db_session.add(MerchantPolicy(merchant_id="merchant_unique"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_timestamps_are_timezone_aware(db_session: Session) -> None:
    result = _record_event(db_session)
    payment_case = create_payment_case(db_session, _new_payment_case())
    db_session.commit()
    db_session.refresh(result.event)
    db_session.refresh(payment_case)

    assert result.event.received_at.utcoffset() is not None
    assert payment_case.detected_at.utcoffset() is not None
    assert payment_case.created_at.utcoffset() is not None


def test_webhook_payload_cannot_be_updated(db_session: Session) -> None:
    result = _record_event(db_session, payload={"event": "payment.failed"})
    db_session.commit()

    result.event.raw_payload = {"event": "payment.captured"}
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()


def test_webhook_raw_body_hash_cannot_be_updated(db_session: Session) -> None:
    result = _record_event(db_session)
    db_session.commit()

    result.event.raw_body_sha256 = "0" * 64
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()


def test_webhook_operational_metadata_can_be_updated(db_session: Session) -> None:
    result = _record_event(db_session)
    db_session.commit()

    result.event.processing_status = EventProcessingStatus.PROCESSED
    result.event.processed_at = datetime.now(UTC)
    db_session.commit()

    db_session.refresh(result.event)
    assert result.event.processing_status is EventProcessingStatus.PROCESSED
    assert result.event.processed_at is not None


def test_case_events_are_append_only(db_session: Session) -> None:
    payment_case = create_payment_case(db_session, _new_payment_case())
    case_event = append_case_event(
        db_session,
        CaseEvent(
            case_id=payment_case.id,
            event_type="CASE_DETECTED",
            source="SYSTEM",
            event_data={"reason": "synthetic-test"},
        ),
    )
    db_session.commit()

    case_event.source = "OPERATOR"
    with pytest.raises(ValueError, match="append-only"):
        db_session.flush()
