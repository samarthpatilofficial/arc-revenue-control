"""PostgreSQL-backed contracts for the sanitized Task 10 read API."""

import asyncio
from collections.abc import Callable, Generator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from arc.config import Settings
from arc.db.session import get_db_session
from arc.demo import seed_demo_scenarios
from arc.domain.enums import ProviderMode
from arc.domain.models import PaymentCase
from arc.outcomes import RecoveryOutcomeService
from services.api.main import create_app
from tests.outcome_support import (
    TEST_SETTINGS,
    StubOutcomeGateway,
    outcome_snapshot,
    prepare_waiting_recovery,
)
from tests.reconciliation_support import SessionFactory


@pytest.fixture
def api_get(
    integration_session_factory: SessionFactory,
) -> Generator[Callable[[str], Response], None, None]:
    settings = Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        _env_file=None,
    )
    app = create_app(settings)

    def override_session() -> Generator[Session, None, None]:
        with integration_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session

    def get(path: str) -> Response:
        async def request() -> Response:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.get(path)

        return asyncio.run(request())

    yield get
    app.dependency_overrides.clear()


def _demo_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        demo_mode=True,
        _env_file=None,
    )


def _recover(
    session_factory: SessionFactory,
    *,
    payment_id: str,
    amount: int,
    mode: ProviderMode,
    currency: str = "INR",
) -> tuple[PaymentCase, str]:
    payment_case, action, _ = prepare_waiting_recovery(
        session_factory,
        payment_id=payment_id,
        amount=amount,
    )
    if currency != "INR":
        with session_factory() as session:
            stored = session.get(PaymentCase, payment_case.id)
            assert stored is not None
            stored.currency = currency
            session.commit()
        payment_case.currency = currency
    recovered_payment_id = f"pay_recovered_{payment_id.removeprefix('pay_')}"
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=amount,
        payment_id=recovered_payment_id,
    )
    RecoveryOutcomeService(
        session_factory=session_factory,
        payment_link_gateway=StubOutcomeGateway(snapshot),
        settings=TEST_SETTINGS,
        provider_mode=mode,
    ).observe_recovery_action(action.id)
    with session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        session.expunge(stored)
        return stored, recovered_payment_id


def _assert_sensitive_fields_absent(payload: object) -> None:
    serialized = repr(payload).lower()
    forbidden = (
        "payment_id",
        "subscription_id",
        "customer_id",
        "merchant_id",
        "external_url",
        "provider_payment_id",
        "assessment_fingerprint",
        "authorization_input_fingerprint",
        "request_fingerprint",
        "idempotency_key",
        "error_description",
    )
    for field in forbidden:
        assert field not in serialized


def test_dashboard_summary_never_mixes_modes_or_currencies(
    integration_session_factory: SessionFactory,
    api_get: Callable[[str], Response],
) -> None:
    _recover(
        integration_session_factory,
        payment_id="pay_read_metrics_test_inr",
        amount=1_000,
        mode=ProviderMode.TEST,
    )
    _recover(
        integration_session_factory,
        payment_id="pay_read_metrics_live_inr",
        amount=2_000,
        mode=ProviderMode.LIVE,
    )
    _recover(
        integration_session_factory,
        payment_id="pay_read_metrics_test_usd",
        amount=3_000,
        mode=ProviderMode.TEST,
        currency="USD",
    )

    test_inr = api_get(
        "/api/v1/dashboard/summary?provider_mode=TEST&currency=INR"
    )
    live_inr = api_get(
        "/api/v1/dashboard/summary?provider_mode=LIVE&currency=INR"
    )
    test_usd = api_get(
        "/api/v1/dashboard/summary?provider_mode=TEST&currency=USD"
    )

    assert test_inr.status_code == 200
    assert test_inr.json()["cases_evaluated"] == 1
    assert test_inr.json()["recovered_revenue_minor"] == 1_000
    assert live_inr.json()["cases_evaluated"] == 1
    assert live_inr.json()["recovered_revenue_minor"] == 2_000
    assert test_usd.json()["cases_evaluated"] == 1
    assert test_usd.json()["recovered_revenue_minor"] == 3_000


def test_case_list_filters_and_provider_origin_are_sanitized(
    integration_session_factory: SessionFactory,
    api_get: Callable[[str], Response],
) -> None:
    recovered, _ = _recover(
        integration_session_factory,
        payment_id="pay_private_case_list",
        amount=1_000,
        mode=ProviderMode.TEST,
    )
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, recovered.id)
        assert stored is not None
        stored.customer_id = "customer-private-value"
        stored.error_description = "private raw provider description"
        session.commit()
    seed_demo_scenarios(
        settings=_demo_settings(),
        session_factory=integration_session_factory,
    )

    response = api_get("/api/v1/cases?state=RECOVERED")
    test_only = api_get("/api/v1/cases?provider_mode=TEST")

    assert response.status_code == 200
    assert all(item["current_state"] == "RECOVERED" for item in response.json())
    assert test_only.status_code == 200
    assert [item["case_reference"] for item in test_only.json()] == [
        recovered.case_reference
    ]
    assert test_only.json()[0]["data_origin"] == "TEST_MODE"
    _assert_sensitive_fields_absent(response.json())
    assert "customer-private-value" not in repr(response.json())
    assert "private raw provider description" not in repr(response.json())


def test_case_detail_projects_attribution_without_sensitive_identifiers(
    integration_session_factory: SessionFactory,
    api_get: Callable[[str], Response],
) -> None:
    recovered, provider_payment_id = _recover(
        integration_session_factory,
        payment_id="pay_private_case_detail",
        amount=1_250,
        mode=ProviderMode.TEST,
    )

    response = api_get(f"/api/v1/cases/{recovered.case_reference}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_origin"] == "TEST_MODE"
    assert payload["case"]["current_state"] == "RECOVERED"
    assert payload["outcome"]["outcome_status"] == "RECOVERED"
    assert payload["attribution"] == {
        "provider_mode": "TEST",
        "recovered_amount_minor": 1_250,
        "currency": "INR",
        "reason_code": "ARC_PAYMENT_LINK_CAPTURED",
        "attributed_at": payload["attribution"]["attributed_at"],
    }
    _assert_sensitive_fields_absent(payload)
    assert provider_payment_id not in repr(payload)
    assert "https://" not in repr(payload)


def test_timeline_is_chronological_and_labels_authority_and_synthetic_origin(
    integration_session_factory: SessionFactory,
    api_get: Callable[[str], Response],
) -> None:
    seed_demo_scenarios(
        settings=_demo_settings(),
        session_factory=integration_session_factory,
    )

    response = api_get(
        "/api/v1/cases/demo_high_value_approval_v1/timeline"
    )
    detail = api_get("/api/v1/cases/demo_high_value_approval_v1")

    assert response.status_code == 200
    timeline = response.json()
    timestamps = [datetime.fromisoformat(item["timestamp"]) for item in timeline]
    assert timestamps == sorted(timestamps)
    stages = [item["stage"] for item in timeline]
    assert stages.index("DETECTED") < stages.index("RECONCILED")
    assert stages.index("RECONCILED") < stages.index("DIAGNOSED")
    assert stages.index("DIAGNOSED") < stages.index("STRATEGY")
    assert stages.index("STRATEGY") < stages.index("POLICY")
    assert stages.index("POLICY") < stages.index("APPROVAL")
    assert {item["authority"] for item in timeline} >= {
        "AI_PROPOSAL",
        "DETERMINISTIC_POLICY",
        "HUMAN_APPROVAL",
    }
    assert all(item["data_origin"] == "SYNTHETIC_DEMO" for item in timeline)
    assert next(item for item in timeline if item["stage"] == "STRATEGY")[
        "action"
    ] == "CREATE_RECOVERY_LINK"
    assert detail.status_code == 200
    assert detail.json()["strategy"]["confidence_authority"] == (
        "MODEL_OBSERVABILITY_ONLY"
    )
    _assert_sensitive_fields_absent(timeline)


def test_approval_queue_and_recovery_action_list_are_sanitized(
    integration_session_factory: SessionFactory,
    api_get: Callable[[str], Response],
) -> None:
    seed_demo_scenarios(
        settings=_demo_settings(),
        session_factory=integration_session_factory,
    )
    recovered, _ = _recover(
        integration_session_factory,
        payment_id="pay_read_action_list",
        amount=1_500,
        mode=ProviderMode.TEST,
    )

    approvals = api_get("/api/v1/approvals")
    actions = api_get("/api/v1/recovery-actions")

    assert approvals.status_code == 200
    assert len(approvals.json()) == 1
    assert approvals.json()[0]["case_reference"] == (
        "demo_high_value_approval_v1"
    )
    assert approvals.json()[0]["approval_status"] == "PENDING"
    assert approvals.json()[0]["data_origin"] == "SYNTHETIC_DEMO"
    assert actions.status_code == 200
    assert len(actions.json()) == 1
    assert actions.json()[0]["case_reference"] == recovered.case_reference
    assert actions.json()[0]["outcome_status"] == "RECOVERED"
    assert actions.json()[0]["data_origin"] == "TEST_MODE"
    _assert_sensitive_fields_absent(approvals.json())
    _assert_sensitive_fields_absent(actions.json())


def test_missing_case_and_invalid_filters_use_clean_error_contract(
    api_get: Callable[[str], Response],
) -> None:
    missing = api_get("/api/v1/cases/does-not-exist")
    invalid = api_get("/api/v1/cases?state=NOT_A_STATE")

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "CASE_NOT_FOUND"
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "INVALID_FILTER"
