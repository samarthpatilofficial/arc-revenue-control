"""PostgreSQL-backed contracts for the sanitized evaluator replica."""

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from arc.config import Settings
from arc.demo import seed_demo_scenarios
from arc.demo.openai_evidence import create_openai_evidence_case
from arc.deployment import (
    PublicDemoAlreadyImportedError,
    PublicDemoBundleError,
    PublicDemoImportError,
    export_public_demo_bundle,
    import_public_demo_bundle,
    verify_public_demo_database,
)
from arc.domain.enums import RecoveryAction
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelResult,
    StrategyOutput,
)
from arc.outcomes import RecoveryOutcomeService
from tests.conftest import CORE_TABLES
from tests.outcome_support import (
    TEST_SETTINGS,
    StubOutcomeGateway,
    outcome_snapshot,
    prepare_waiting_recovery,
)
from tests.reconciliation_support import SessionFactory

_SENSITIVE_VALUES = (
    "merchant_provider_sensitive",
    "pay_provider_sensitive_123456789",
    "plink_provider_sensitive_123456789",
    "pay_recovered_sensitive_123456789",
    "response_provider_sensitive_123456789",
    "customer-sensitive@example.test",
    "https://rzp.io/i/must-not-be-persisted",
)


class _AcceptedOpenAIClient:
    model = "gpt-5.6-luna"

    def propose(self, context: StrategyContext) -> StrategyModelResult:
        assert context.amount_minor == 2_500_000
        return StrategyModelResult(
            output=StrategyOutput(
                action=RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
                explanation="Request a bounded payment method update.",
                confidence=0.98,
                re_evaluate_after_seconds=None,
            ),
            provider_response_id=_SENSITIVE_VALUES[4],
            model=self.model,
            input_tokens=40,
            output_tokens=12,
            total_tokens=52,
            latency_ms=10,
        )


def _normal_settings(*, demo_mode: bool = False) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        demo_mode=demo_mode,
        openai_api_key="test-only-placeholder",
        _env_file=None,
    )


def _seed_accepted_evidence(session_factory: SessionFactory) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        session_factory,
        payment_id=_SENSITIVE_VALUES[1],
        payment_link_id=_SENSITIVE_VALUES[2],
        amount=1_000,
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=1_000,
        payment_id=_SENSITIVE_VALUES[3],
    )
    RecoveryOutcomeService(
        session_factory=session_factory,
        payment_link_gateway=StubOutcomeGateway(snapshot),
        settings=TEST_SETTINGS,
    ).observe_recovery_action(action.id)
    with session_factory() as session:
        stored = session.get(type(payment_case), payment_case.id)
        assert stored is not None
        stored.customer_id = _SENSITIVE_VALUES[5]
        session.commit()

    seed_demo_scenarios(
        settings=_normal_settings(demo_mode=True),
        session_factory=session_factory,
    )
    create_openai_evidence_case(
        settings=_normal_settings(),
        session_factory=session_factory,
        model_client=_AcceptedOpenAIClient(),
    )


def _truncate_operational_tables(session_factory: SessionFactory) -> None:
    with session_factory() as session:
        session.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(CORE_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )
        session.commit()


def test_export_refuses_incomplete_evidence(
    integration_session_factory: SessionFactory,
    tmp_path: Path,
) -> None:
    seed_demo_scenarios(
        settings=_normal_settings(demo_mode=True),
        session_factory=integration_session_factory,
    )

    with pytest.raises(PublicDemoBundleError):
        export_public_demo_bundle(
            tmp_path / "invalid.json",
            session_factory=integration_session_factory,
        )


def test_export_is_sanitized_and_contains_no_provider_payload_or_secret(
    integration_session_factory: SessionFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Public demo export must remain offline")

    monkeypatch.setattr(httpx.Client, "request", forbid_network)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbid_network)
    _seed_accepted_evidence(integration_session_factory)
    path = tmp_path / "public-demo.json"

    result = export_public_demo_bundle(
        path,
        session_factory=integration_session_factory,
    )
    rendered = path.read_text(encoding="utf-8")
    bundle = json.loads(rendered)

    assert result.case_count == 5
    assert bundle["bundle_version"] == "arc-public-demo-v1"
    assert "webhook_events" not in bundle["entities"]
    assert "raw_payload" not in rendered
    assert "raw_prompt" not in rendered
    assert "Authorization" not in rendered
    assert "https://rzp.io/" not in rendered
    assert not any(value in rendered for value in _SENSITIVE_VALUES)
    assert all(
        item["external_url"] is None
        for item in bundle["entities"]["recovery_actions"]
    )
    assert all(
        item["provider_response_id"].startswith("public_demo_model_response_")
        for item in bundle["entities"]["strategy_proposals"]
        if item["provider_response_id"] is not None
    )


def test_import_refuses_malformed_bundle_and_nonempty_database(
    integration_session_factory: SessionFactory,
    tmp_path: Path,
) -> None:
    _seed_accepted_evidence(integration_session_factory)
    path = tmp_path / "public-demo.json"
    export_public_demo_bundle(path, session_factory=integration_session_factory)

    with pytest.raises(PublicDemoImportError, match="unexpected operational"):
        import_public_demo_bundle(
            path,
            session_factory=integration_session_factory,
        )

    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["case_count"] = 4
    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps(bundle), encoding="utf-8")
    _truncate_operational_tables(integration_session_factory)

    with pytest.raises(PublicDemoImportError):
        import_public_demo_bundle(
            malformed,
            session_factory=integration_session_factory,
        )


def test_export_import_round_trip_preserves_judge_facing_facts(
    integration_session_factory: SessionFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Public demo round trip must remain offline")

    monkeypatch.setattr(httpx.Client, "request", forbid_network)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbid_network)
    _seed_accepted_evidence(integration_session_factory)
    path = tmp_path / "public-demo.json"
    exported = export_public_demo_bundle(
        path,
        session_factory=integration_session_factory,
    )
    _truncate_operational_tables(integration_session_factory)

    imported = import_public_demo_bundle(
        path,
        session_factory=integration_session_factory,
    )
    verified = verify_public_demo_database(
        session_factory=integration_session_factory
    )

    assert imported.checksum_sha256 == exported.checksum_sha256
    assert verified.ready is True
    assert verified.case_count == 5
    assert verified.provider_recoveries == 1
    assert verified.provider_attributed_minor == 1_000
    assert verified.openai_evidence_cases == 1
    assert verified.openai_executions == 0
    assert verified.openai_attributions == 0
    assert verified.already_captured_protected == 1
    assert verified.hard_stops == 1
    assert verified.approval_cases == 2
    assert verified.provider_identifiers_exposed == 0
    assert verified.payment_link_urls_exposed == 0
    with pytest.raises(PublicDemoAlreadyImportedError, match="already imported"):
        import_public_demo_bundle(
            path,
            session_factory=integration_session_factory,
        )
