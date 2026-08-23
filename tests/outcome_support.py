"""PostgreSQL setup and offline provider fakes for Task 9 tests."""

import json
from collections.abc import Callable
from uuid import UUID, uuid4

from sqlalchemy import select

from arc.config import Settings
from arc.domain.enums import ProviderMode, RecoveryAction
from arc.domain.models import PaymentCase, RecoveryActionRecord
from arc.execution.service import RecoveryExecutionService
from arc.integrations.razorpay.payment_links import (
    PaymentLinkCreateRequest,
    PaymentLinkSnapshot,
)
from arc.integrations.razorpay.webhook_security import hash_raw_body
from arc.persistence import record_event_once
from tests.execution_support import (
    StubPaymentLinkGateway,
    payment_link_snapshot,
    prepare_policy_decision,
)
from tests.reconciliation_support import SessionFactory

TEST_SETTINGS = Settings(
    database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
    razorpay_key_id="rzp_test_ci_only",
    razorpay_key_secret="ci_only_secret",
    _env_file=None,
)


class StubOutcomeGateway:
    """Read fake that exposes no provider payload beyond the strict snapshot."""

    def __init__(
        self,
        snapshot: PaymentLinkSnapshot | Exception,
        *,
        on_fetch: Callable[[], None] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.on_fetch = on_fetch
        self.calls: list[str] = []

    def fetch_by_id(self, payment_link_id: str) -> PaymentLinkSnapshot:
        self.calls.append(payment_link_id)
        if self.on_fetch is not None:
            self.on_fetch()
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot

    def lookup_by_reference(
        self, reference_id: str
    ) -> list[PaymentLinkSnapshot]:
        raise AssertionError("Outcome observer must not perform collection lookup")

    def create(self, request: PaymentLinkCreateRequest) -> PaymentLinkSnapshot:
        raise AssertionError("Outcome observer must not create Payment Links")

    def cancel(self, payment_link_id: str) -> PaymentLinkSnapshot:
        raise AssertionError("Outcome observer must not cancel Payment Links")


def prepare_waiting_recovery(
    session_factory: SessionFactory,
    *,
    amount: int = 1000,
    payment_id: str | None = None,
    payment_link_id: str | None = None,
) -> tuple[PaymentCase, RecoveryActionRecord, PaymentLinkSnapshot]:
    """Build a real governed action in WAITING_FOR_OUTCOME using offline fakes."""

    original_payment_id = payment_id or f"pay_original_{uuid4().hex}"
    link_id = payment_link_id or f"plink_{uuid4().hex}"
    payment_case, _, _ = prepare_policy_decision(
        session_factory,
        payment_id=original_payment_id,
        action=RecoveryAction.CREATE_RECOVERY_LINK,
        amount=amount,
    )
    execution_gateway = StubPaymentLinkGateway(payment_link_id=link_id)
    result = RecoveryExecutionService(
        session_factory=session_factory,
        payment_link_gateway=execution_gateway,
        settings=TEST_SETTINGS,
    ).execute(payment_case.id)
    request = execution_gateway.requests[0]
    provider_snapshot = payment_link_snapshot(
        request=request,
        payment_link_id=link_id,
    )
    with session_factory() as session:
        stored_case = session.get(PaymentCase, result.case_id)
        action = session.get(RecoveryActionRecord, result.recovery_action_id)
        assert stored_case is not None
        assert action is not None
        session.expunge(stored_case)
        session.expunge(action)
    return stored_case, action, provider_snapshot


def outcome_snapshot(
    action: RecoveryActionRecord,
    payment_case: PaymentCase,
    *,
    status: str,
    amount_paid: int = 0,
    payment_id: str | None = None,
    payment_status: str = "captured",
    payment_amount: int | None = None,
    updated_at: int = 1_725_000_100,
    **overrides: object,
) -> PaymentLinkSnapshot:
    assert action.external_reference_id is not None
    assert action.external_reference is not None
    assert payment_case.amount is not None
    assert payment_case.currency is not None
    payments: list[dict[str, object]] = []
    if payment_id is not None:
        payments.append(
            {
                "payment_id": payment_id,
                "amount": payment_amount or payment_case.amount,
                "status": payment_status,
                "method": "card",
                "created_at": updated_at,
                "payment_link_id": action.external_reference_id,
            }
        )
    values: dict[str, object] = {
        "id": action.external_reference_id,
        "reference_id": action.external_reference,
        "amount": payment_case.amount,
        "amount_paid": amount_paid,
        "currency": payment_case.currency,
        "status": status,
        "short_url": "https://rzp.io/i/must-not-be-persisted",
        "expire_by": 1_800_000_000,
        "updated_at": updated_at,
        "payments": payments,
    }
    values.update(overrides)
    return PaymentLinkSnapshot.model_validate(values)


def store_payment_link_event(
    session_factory: SessionFactory,
    action: RecoveryActionRecord | None,
    *,
    event_type: str = "payment_link.paid",
    event_id: str | None = None,
    include_pii: bool = False,
) -> UUID:
    entity: dict[str, object] = {
        "id": (
            action.external_reference_id if action is not None else "plink_unmatched"
        ),
        "reference_id": (
            action.external_reference if action is not None else "unmatched_ref"
        ),
        "status": event_type.removeprefix("payment_link."),
    }
    if include_pii:
        entity["customer"] = {
            "name": "Webhook PII must remain only in immutable ledger",
            "email": "private@example.test",
            "contact": "+910000000000",
        }
    payload = {
        "event": event_type,
        "payload": {"payment_link": {"entity": entity}},
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    with session_factory() as session:
        stored = record_event_once(
            session,
            razorpay_event_id=event_id or f"evt_{uuid4().hex}",
            event_type=event_type,
            raw_payload=payload,
            raw_body_sha256=hash_raw_body(raw_body),
            signature_verified=True,
        )
        session.commit()
        return stored.event.id


def load_action(
    session_factory: SessionFactory, action_id: UUID
) -> RecoveryActionRecord:
    with session_factory() as session:
        action = session.scalar(
            select(RecoveryActionRecord).where(
                RecoveryActionRecord.id == action_id
            )
        )
        assert action is not None
        session.expunge(action)
        return action
