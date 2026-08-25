"""Sanitized export, import, and verification for public evaluator evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Uuid, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arc.db.session import get_session_factory
from arc.demo.markers import (
    ALREADY_CAPTURED_PROTECTION,
    DEMO_EVENT_SOURCE,
    DEMO_EVENT_TYPE,
    HARD_STOP_ATTENTION,
    HIGH_VALUE_APPROVAL,
    OPENAI_EVIDENCE_CASE_REFERENCE,
    OPENAI_EVIDENCE_EVENT_SOURCE,
    OPENAI_EVIDENCE_EVENT_TYPE,
    OPENAI_EVIDENCE_SCENARIO,
    RESERVED_DEMO_SCENARIO_KEYS,
)
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    PolicyDecisionResult,
    ProviderMode,
    RecoveryAction,
    RecoveryOutcomeStatus,
    StrategySource,
)
from arc.domain.models import (
    ApprovalRequest,
    CaseEvent,
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
    RecoveryActionRecord,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
    StrategyProposal,
    WebhookEvent,
)
from arc.outcomes import calculate_recovery_metrics
from arc.policy.schemas import validate_policy
from arc.read_models import (
    get_case_detail,
    get_case_timeline,
    list_approval_queue,
    list_case_summaries,
    list_recovery_actions,
)
from arc.read_models.schemas import DataOrigin, ResolutionKind, StrategyProvenance

BUNDLE_VERSION = "arc-public-demo-v1"
DEFAULT_BUNDLE_PATH = Path("var/deployment/public-demo-bundle.json")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_SHAPED_RE = re.compile(
    r"(?:rzp_(?:test|live)_|https://rzp\.io/|\bplink_[A-Za-z0-9]+|"
    r"\bpay_[A-Za-z0-9]{8,})"
)

SessionFactory = Callable[[], Session]


class PublicDemoBundleError(RuntimeError):
    """Raised when accepted evidence cannot be exported safely."""


class PublicDemoImportError(RuntimeError):
    """Raised when a bundle cannot be imported safely."""


class PublicDemoAlreadyImportedError(PublicDemoImportError):
    """Raised when the exact bundle already occupies the target database."""


@dataclass(frozen=True, slots=True)
class PublicDemoBundleResult:
    """Safe aggregate result for an explicit export or import."""

    path: Path
    bundle_version: str
    case_count: int
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class PublicDemoVerificationResult:
    """Sanitized semantic verification of an imported evaluator database."""

    ready: bool
    case_count: int
    provider_recoveries: int
    provider_attributed_minor: int
    openai_evidence_cases: int
    openai_executions: int
    openai_attributions: int
    already_captured_protected: int
    hard_stops: int
    approval_cases: int
    provider_identifiers_exposed: int
    payment_link_urls_exposed: int
    failure_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EntitySpec:
    model: type[Any]
    fields: tuple[str, ...]


_ENTITY_SPECS: dict[str, _EntitySpec] = {
    "merchant_policies": _EntitySpec(
        MerchantPolicy,
        (
            "id",
            "merchant_id",
            "automation_enabled",
            "allowed_actions",
            "max_automated_attempts",
            "max_contact_attempts",
            "recovery_window_minutes",
            "high_value_threshold_minor",
            "require_approval_above_minor",
            "stopping_rules",
            "created_at",
            "updated_at",
        ),
    ),
    "payment_cases": _EntitySpec(
        PaymentCase,
        (
            "id",
            "case_reference",
            "merchant_id",
            "payment_id",
            "subscription_id",
            "razorpay_payment_status",
            "razorpay_subscription_status",
            "razorpay_payment_method",
            "customer_id",
            "amount",
            "currency",
            "current_state",
            "error_code",
            "error_description",
            "error_source",
            "error_step",
            "error_reason",
            "eligibility_status",
            "eligibility_reason_code",
            "eligibility_evaluated_at",
            "failure_category",
            "recovery_disposition",
            "diagnosis_reason_code",
            "diagnosed_at",
            "assessment_fingerprint",
            "attempt_count",
            "contact_attempt_count",
            "detected_at",
            "last_reconciled_at",
            "resolved_at",
            "created_at",
            "updated_at",
        ),
    ),
    "case_events": _EntitySpec(
        CaseEvent,
        ("id", "case_id", "event_type", "source", "event_data", "created_at"),
    ),
    "strategy_proposals": _EntitySpec(
        StrategyProposal,
        (
            "id",
            "case_id",
            "assessment_fingerprint",
            "strategy_input_fingerprint",
            "source",
            "action",
            "reason_code",
            "explanation",
            "confidence",
            "re_evaluate_after_seconds",
            "prompt_version",
            "model",
            "provider_response_id",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "latency_ms",
            "created_at",
            "superseded_at",
        ),
    ),
    "policy_decisions": _EntitySpec(
        PolicyDecision,
        (
            "id",
            "case_id",
            "strategy_proposal_id",
            "merchant_policy_id",
            "strategy_input_fingerprint",
            "policy_fingerprint",
            "authorization_input_fingerprint",
            "result",
            "reason_code",
            "explanation",
            "recovery_window_ends_at",
            "approval_threshold_minor",
            "high_value_threshold_minor",
            "observed_high_value",
            "observed_amount_minor",
            "observed_attempt_count",
            "observed_contact_attempt_count",
            "evaluated_at",
            "superseded_at",
        ),
    ),
    "approval_requests": _EntitySpec(
        ApprovalRequest,
        (
            "id",
            "case_id",
            "policy_decision_id",
            "status",
            "requested_at",
            "decided_at",
            "decided_by",
            "decision_note",
            "created_at",
        ),
    ),
    "recovery_actions": _EntitySpec(
        RecoveryActionRecord,
        (
            "id",
            "case_id",
            "strategy_proposal_id",
            "policy_decision_id",
            "approval_request_id",
            "action",
            "execution_status",
            "idempotency_key",
            "request_fingerprint",
            "provider",
            "external_reference_id",
            "external_reference",
            "external_status",
            "external_url",
            "external_expires_at",
            "execution_started_at",
            "execution_attempt_count",
            "executed_at",
            "failed_at",
            "error_code",
            "next_evaluation_at",
            "created_at",
            "updated_at",
        ),
    ),
    "recovery_outcome_observations": _EntitySpec(
        RecoveryOutcomeObservation,
        (
            "id",
            "case_id",
            "recovery_action_id",
            "source",
            "provider",
            "provider_mode",
            "provider_status",
            "outcome_status",
            "amount_expected_minor",
            "amount_paid_minor",
            "currency",
            "provider_payment_id",
            "provider_payment_status",
            "evidence_fingerprint",
            "observed_at",
            "created_at",
        ),
    ),
    "recovery_attributions": _EntitySpec(
        RecoveryAttribution,
        (
            "id",
            "case_id",
            "recovery_action_id",
            "outcome_observation_id",
            "provider",
            "provider_mode",
            "provider_payment_link_id",
            "provider_reference_id",
            "provider_payment_id",
            "recovered_amount_minor",
            "currency",
            "attribution_reason_code",
            "evidence_fingerprint",
            "attributed_at",
            "created_at",
        ),
    ),
}


def export_public_demo_bundle(
    output_path: Path = DEFAULT_BUNDLE_PATH,
    *,
    session_factory: SessionFactory | None = None,
) -> PublicDemoBundleResult:
    """Validate and export exactly the accepted judge-facing evidence."""

    _assert_model_field_coverage()
    factory = session_factory or get_session_factory()
    with factory() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        selection = _select_accepted_evidence(session)
        entities = _serialize_entities(session, selection)
        _validate_sanitized_entities(entities, selection.sensitive_values)
        session.rollback()

    payload = {
        "bundle_version": BUNDLE_VERSION,
        "case_count": 5,
        "entities": entities,
    }
    checksum = _checksum(payload)
    bundle = {**payload, "checksum_sha256": checksum}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return PublicDemoBundleResult(
        path=output_path,
        bundle_version=BUNDLE_VERSION,
        case_count=5,
        checksum_sha256=checksum,
    )


def import_public_demo_bundle(
    bundle_path: Path,
    *,
    session_factory: SessionFactory | None = None,
) -> PublicDemoBundleResult:
    """Import one validated bundle into an empty migrated database."""

    bundle = _load_bundle(bundle_path)
    entities = bundle["entities"]
    factory = session_factory or get_session_factory()
    try:
        with factory() as session, session.begin():
            _guard_import_target(session, entities)
            for entity_name, spec in _ENTITY_SPECS.items():
                for record in entities[entity_name]:
                    session.add(spec.model(**_decode_record(spec, record)))
                session.flush()
    except PublicDemoImportError:
        raise
    except (SQLAlchemyError, TypeError, ValueError) as error:
        raise PublicDemoImportError(
            "Public demo bundle import failed safely"
        ) from error
    return PublicDemoBundleResult(
        path=bundle_path,
        bundle_version=bundle["bundle_version"],
        case_count=bundle["case_count"],
        checksum_sha256=bundle["checksum_sha256"],
    )


def verify_public_demo_database(
    *,
    session_factory: SessionFactory | None = None,
) -> PublicDemoVerificationResult:
    """Verify imported facts through the same display-safe read models."""

    factory = session_factory or get_session_factory()
    failures: list[str] = []
    try:
        with factory() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            cases = list_case_summaries(
                session,
                state=None,
                failure_category=None,
                provider_mode=None,
                limit=100,
                offset=0,
            )
            details = {
                item.case_reference: get_case_detail(session, item.case_reference)
                for item in cases
            }
            timelines = {
                item.case_reference: get_case_timeline(
                    session, item.case_reference
                )
                for item in cases
            }
            approvals = list_approval_queue(
                session,
                status=ApprovalStatus.PENDING,
                limit=100,
                offset=0,
            )
            actions = list_recovery_actions(session, limit=100, offset=0)
            metrics = calculate_recovery_metrics(
                session,
                provider_mode=ProviderMode.TEST,
                currency="INR",
            )

            provider_cases = [
                item
                for item in cases
                if item.data_origin is DataOrigin.TEST_MODE
                and item.resolution_kind is ResolutionKind.ARC_RECOVERED
            ]
            openai_cases = [
                item
                for item in cases
                if item.data_origin is DataOrigin.SYNTHETIC_INPUT
                and item.strategy_provenance is StrategyProvenance.OPENAI
            ]
            captured_cases = [
                item
                for item in cases
                if item.resolution_kind is ResolutionKind.ALREADY_CAPTURED
                and item.data_origin is DataOrigin.SYNTHETIC_DEMO
            ]
            hard_stops = [
                item
                for item in cases
                if item.case_reference == "demo_hard_stop_attention_v1"
                and item.current_state is CaseState.EXHAUSTED
                and item.data_origin is DataOrigin.SYNTHETIC_DEMO
            ]
            openai_ids = {
                row.id
                for row in session.scalars(
                    select(PaymentCase).where(
                        PaymentCase.case_reference.in_(
                            [item.case_reference for item in openai_cases]
                        )
                    )
                )
            }
            openai_executions = _count_for_case_ids(
                session, RecoveryActionRecord, openai_ids
            )
            openai_attributions = _count_for_case_ids(
                session, RecoveryAttribution, openai_ids
            )

            safe_projection = {
                "cases": cases,
                "details": details,
                "timelines": timelines,
                "approvals": approvals,
                "actions": actions,
            }
            serialized_projection = json.dumps(
                _json_value(safe_projection), sort_keys=True
            )
            provider_identifiers = len(
                _PROVIDER_SHAPED_RE.findall(serialized_projection)
            )
            payment_link_urls = serialized_projection.count("https://rzp.io/")

            if len(cases) != 5:
                failures.append("Expected exactly five evaluator cases")
            if len(provider_cases) != 1:
                failures.append("Provider-backed recovered case is invalid")
            if (
                metrics.recovered_cases != 1
                or metrics.recovered_revenue_minor != 1_000
            ):
                failures.append("Provider attribution metrics are invalid")
            if len(openai_cases) != 1:
                failures.append("OpenAI evidence case is invalid")
            else:
                detail = details[openai_cases[0].case_reference]
                if (
                    detail is None
                    or detail.strategy is None
                    or detail.strategy.model != "gpt-5.6-luna"
                    or detail.strategy.action
                    is not RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE
                    or detail.strategy.confidence != 0.98
                    or detail.policy is None
                    or detail.policy.result
                    is not PolicyDecisionResult.REQUIRES_APPROVAL
                    or detail.approval is None
                    or detail.approval.approval_status
                    is not ApprovalStatus.PENDING
                ):
                    failures.append("OpenAI evidence meaning changed")
            if openai_executions or openai_attributions:
                failures.append("OpenAI evidence was incorrectly executed")
            if len(captured_cases) != 1:
                failures.append("Already-captured protection is invalid")
            if len(hard_stops) != 1:
                failures.append("Hard-stop evidence is invalid")
            if len(approvals) != 2:
                failures.append("Approval evidence count is invalid")
            if provider_identifiers:
                failures.append("Provider identifier leaked through read models")
            if payment_link_urls:
                failures.append("Payment Link URL leaked through read models")
            session.rollback()
    except (SQLAlchemyError, OSError, ValueError, TypeError):
        return PublicDemoVerificationResult(
            ready=False,
            case_count=0,
            provider_recoveries=0,
            provider_attributed_minor=0,
            openai_evidence_cases=0,
            openai_executions=0,
            openai_attributions=0,
            already_captured_protected=0,
            hard_stops=0,
            approval_cases=0,
            provider_identifiers_exposed=0,
            payment_link_urls_exposed=0,
            failure_reasons=("Public demo database is unavailable or invalid",),
        )

    return PublicDemoVerificationResult(
        ready=not failures,
        case_count=len(cases),
        provider_recoveries=len(provider_cases),
        provider_attributed_minor=metrics.recovered_revenue_minor,
        openai_evidence_cases=len(openai_cases),
        openai_executions=openai_executions,
        openai_attributions=openai_attributions,
        already_captured_protected=len(captured_cases),
        hard_stops=len(hard_stops),
        approval_cases=len(approvals),
        provider_identifiers_exposed=provider_identifiers,
        payment_link_urls_exposed=payment_link_urls,
        failure_reasons=tuple(failures),
    )


def render_public_demo_verification(
    result: PublicDemoVerificationResult,
) -> str:
    """Render stable, sanitized operator output."""

    lines = [
        "Public Demo Evidence Verification",
        "---------------------------------",
        f"Cases .......................... {result.case_count}",
        f"Provider-backed recoveries .... {result.provider_recoveries}",
        "Provider attributed INR ....... "
        f"INR {result.provider_attributed_minor / 100:,.2f}",
        f"OpenAI evidence cases ......... {result.openai_evidence_cases}",
        f"OpenAI executions ............. {result.openai_executions}",
        f"OpenAI attributions ........... {result.openai_attributions}",
        "Already captured protected .... "
        f"{result.already_captured_protected}",
        f"Hard stops .................... {result.hard_stops}",
        f"Approval cases ................ {result.approval_cases}",
        "Provider identifiers exposed ... "
        f"{result.provider_identifiers_exposed}",
        "Payment Link URLs exposed ...... "
        f"{result.payment_link_urls_exposed}",
    ]
    for reason in result.failure_reasons:
        lines.append(f"Failure: {reason}")
    lines.extend(
        [
            "",
            "PUBLIC DEMO DATABASE: READY"
            if result.ready
            else "PUBLIC DEMO DATABASE: NOT READY",
        ]
    )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _EvidenceSelection:
    case_ids: frozenset[UUID]
    policy_ids: frozenset[UUID]
    sensitive_values: frozenset[str]
    merchant_replacements: Mapping[str, str]
    case_reference_replacements: Mapping[str, str]
    payment_replacements: Mapping[str, str]
    subscription_replacements: Mapping[str, str]


def _select_accepted_evidence(session: Session) -> _EvidenceSelection:
    cases = list(session.scalars(select(PaymentCase)))
    by_id = {item.id: item for item in cases}
    demo_markers = list(
        session.scalars(
            select(CaseEvent).where(
                CaseEvent.event_type == DEMO_EVENT_TYPE,
                CaseEvent.source == DEMO_EVENT_SOURCE,
            )
        )
    )
    scenario_map = {
        marker.event_data.get("scenario_key"): by_id.get(marker.case_id)
        for marker in demo_markers
    }
    if (
        len(demo_markers) != 3
        or set(scenario_map) != RESERVED_DEMO_SCENARIO_KEYS
        or any(value is None for value in scenario_map.values())
    ):
        raise PublicDemoBundleError("Offline demo evidence is incomplete")

    openai_markers = list(
        session.scalars(
            select(CaseEvent).where(
                CaseEvent.event_type == OPENAI_EVIDENCE_EVENT_TYPE,
                CaseEvent.source == OPENAI_EVIDENCE_EVENT_SOURCE,
            )
        )
    )
    if len(openai_markers) != 1:
        raise PublicDemoBundleError("OpenAI evidence marker is invalid")
    openai_case = by_id.get(openai_markers[0].case_id)
    if (
        openai_case is None
        or openai_case.case_reference != OPENAI_EVIDENCE_CASE_REFERENCE
        or openai_markers[0].event_data
        != {"scenario_key": OPENAI_EVIDENCE_SCENARIO, "synthetic": True}
    ):
        raise PublicDemoBundleError("OpenAI evidence identity is invalid")

    synthetic_ids = {
        marker.case_id for marker in [*demo_markers, *openai_markers]
    }
    provider_attributions = list(
        session.scalars(
            select(RecoveryAttribution).where(
                RecoveryAttribution.provider_mode == ProviderMode.TEST,
                RecoveryAttribution.currency == "INR",
                RecoveryAttribution.recovered_amount_minor == 1_000,
                RecoveryAttribution.case_id.not_in(synthetic_ids),
            )
        )
    )
    if len(provider_attributions) != 1:
        raise PublicDemoBundleError("Accepted provider attribution is invalid")
    provider_case = by_id.get(provider_attributions[0].case_id)
    if provider_case is None:
        raise PublicDemoBundleError("Accepted provider case is missing")

    selected_cases = [
        provider_case,
        openai_case,
        *(scenario_map[key] for key in sorted(RESERVED_DEMO_SCENARIO_KEYS)),
    ]
    selected_ids = {item.id for item in selected_cases if item is not None}
    if len(selected_ids) != 5:
        raise PublicDemoBundleError("Judge-facing case count must equal five")

    _validate_provider_evidence(session, provider_case)
    _validate_openai_evidence(session, openai_case)
    _validate_offline_evidence(session, scenario_map)

    policy_ids = frozenset(
        item
        for item in session.scalars(
            select(PolicyDecision.merchant_policy_id).where(
                PolicyDecision.case_id.in_(selected_ids),
                PolicyDecision.merchant_policy_id.is_not(None),
            )
        )
        if item is not None
    )
    policies = list(
        session.scalars(select(MerchantPolicy).where(MerchantPolicy.id.in_(policy_ids)))
    )
    for policy in policies:
        validate_policy(policy)

    merchant_values = sorted(
        {item.merchant_id for item in selected_cases if item is not None}
        | {item.merchant_id for item in policies}
    )
    payment_values = sorted(
        {
            item.payment_id
            for item in selected_cases
            if item is not None and item.payment_id is not None
        }
    )
    subscription_values = sorted(
        {
            item.subscription_id
            for item in selected_cases
            if item is not None and item.subscription_id is not None
        }
    )
    sensitive_values = _collect_sensitive_values(
        session, selected_ids, merchant_values, payment_values, subscription_values
    )
    sensitive_values.add(provider_case.case_reference)
    return _EvidenceSelection(
        case_ids=frozenset(selected_ids),
        policy_ids=policy_ids,
        sensitive_values=frozenset(sensitive_values),
        merchant_replacements={
            value: f"public_demo_merchant_{index:03d}"
            for index, value in enumerate(merchant_values, start=1)
        },
        case_reference_replacements={
            provider_case.case_reference: "public_demo_provider_recovery_v1"
        },
        payment_replacements={
            value: f"public_demo_payment_{index:03d}"
            for index, value in enumerate(payment_values, start=1)
        },
        subscription_replacements={
            value: f"public_demo_subscription_{index:03d}"
            for index, value in enumerate(subscription_values, start=1)
        },
    )


def _validate_provider_evidence(session: Session, payment_case: PaymentCase) -> None:
    actions = list(
        session.scalars(
            select(RecoveryActionRecord).where(
                RecoveryActionRecord.case_id == payment_case.id
            )
        )
    )
    observations = list(
        session.scalars(
            select(RecoveryOutcomeObservation).where(
                RecoveryOutcomeObservation.case_id == payment_case.id
            )
        )
    )
    attributions = list(
        session.scalars(
            select(RecoveryAttribution).where(
                RecoveryAttribution.case_id == payment_case.id
            )
        )
    )
    if (
        payment_case.current_state is not CaseState.RECOVERED
        or len(actions) != 1
        or len(observations) != 1
        or len(attributions) != 1
        or observations[0].provider_mode is not ProviderMode.TEST
        or observations[0].outcome_status is not RecoveryOutcomeStatus.RECOVERED
        or observations[0].provider_payment_status != "captured"
        or observations[0].amount_expected_minor != 1_000
        or observations[0].amount_paid_minor != 1_000
        or observations[0].currency != "INR"
        or attributions[0].recovered_amount_minor != 1_000
        or attributions[0].currency != "INR"
        or attributions[0].outcome_observation_id != observations[0].id
        or attributions[0].recovery_action_id != actions[0].id
    ):
        raise PublicDemoBundleError("Provider-backed evidence is incomplete")


def _validate_openai_evidence(session: Session, payment_case: PaymentCase) -> None:
    proposals = list(
        session.scalars(
            select(StrategyProposal).where(
                StrategyProposal.case_id == payment_case.id,
                StrategyProposal.superseded_at.is_(None),
            )
        )
    )
    decisions = list(
        session.scalars(
            select(PolicyDecision).where(
                PolicyDecision.case_id == payment_case.id,
                PolicyDecision.superseded_at.is_(None),
            )
        )
    )
    approvals = list(
        session.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.case_id == payment_case.id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
    )
    if (
        len(proposals) != 1
        or proposals[0].source is not StrategySource.AI
        or proposals[0].model != "gpt-5.6-luna"
        or proposals[0].action is not RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE
        or proposals[0].confidence != 0.98
        or len(decisions) != 1
        or decisions[0].result is not PolicyDecisionResult.REQUIRES_APPROVAL
        or len(approvals) != 1
        or payment_case.current_state is not CaseState.POLICY_VALIDATED
        or _count_for_case_ids(session, RecoveryActionRecord, {payment_case.id})
        or _count_for_case_ids(session, RecoveryOutcomeObservation, {payment_case.id})
        or _count_for_case_ids(session, RecoveryAttribution, {payment_case.id})
    ):
        raise PublicDemoBundleError("OpenAI evidence invariants are invalid")


def _validate_offline_evidence(
    session: Session,
    scenarios: Mapping[str, PaymentCase | None],
) -> None:
    high_value = scenarios[HIGH_VALUE_APPROVAL]
    hard_stop = scenarios[HARD_STOP_ATTENTION]
    captured = scenarios[ALREADY_CAPTURED_PROTECTION]
    assert high_value is not None and hard_stop is not None and captured is not None
    high_decision = session.scalar(
        select(PolicyDecision).where(
            PolicyDecision.case_id == high_value.id,
            PolicyDecision.superseded_at.is_(None),
        )
    )
    high_approval = session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.case_id == high_value.id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
    )
    captured_signal = session.scalar(
        select(func.count()).select_from(CaseEvent).where(
            CaseEvent.case_id == captured.id,
            CaseEvent.event_type == "RECONCILIATION_FOUND_ALREADY_CAPTURED",
        )
    )
    synthetic_ids = {item.id for item in (high_value, hard_stop, captured)}
    if (
        high_decision is None
        or high_decision.result is not PolicyDecisionResult.REQUIRES_APPROVAL
        or high_approval is None
        or hard_stop.current_state is not CaseState.EXHAUSTED
        or captured.current_state is not CaseState.RECOVERED
        or not captured_signal
        or _count_for_case_ids(session, RecoveryActionRecord, {hard_stop.id})
        or _count_for_case_ids(session, RecoveryActionRecord, {captured.id})
        or _count_for_case_ids(session, RecoveryOutcomeObservation, synthetic_ids)
        or _count_for_case_ids(session, RecoveryAttribution, synthetic_ids)
    ):
        raise PublicDemoBundleError("Offline safety evidence is invalid")


def _count_for_case_ids(
    session: Session,
    model: type[Any],
    case_ids: Iterable[UUID],
) -> int:
    ids = tuple(case_ids)
    if not ids:
        return 0
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(model.case_id.in_(ids))
        )
        or 0
    )


def _collect_sensitive_values(
    session: Session,
    case_ids: set[UUID],
    merchants: list[str],
    payments: list[str],
    subscriptions: list[str],
) -> set[str]:
    values = {value for value in [*merchants, *payments, *subscriptions] if value}
    for payment_case in session.scalars(
        select(PaymentCase).where(PaymentCase.id.in_(case_ids))
    ):
        if payment_case.customer_id:
            values.add(payment_case.customer_id)
    for proposal in session.scalars(
        select(StrategyProposal).where(StrategyProposal.case_id.in_(case_ids))
    ):
        if proposal.provider_response_id:
            values.add(proposal.provider_response_id)
    for action in session.scalars(
        select(RecoveryActionRecord).where(RecoveryActionRecord.case_id.in_(case_ids))
    ):
        values.update(
            value
            for value in (
                action.external_reference_id,
                action.external_reference,
                action.external_url,
            )
            if value
        )
    for observation in session.scalars(
        select(RecoveryOutcomeObservation).where(
            RecoveryOutcomeObservation.case_id.in_(case_ids)
        )
    ):
        if observation.provider_payment_id:
            values.add(observation.provider_payment_id)
    for attribution in session.scalars(
        select(RecoveryAttribution).where(
            RecoveryAttribution.case_id.in_(case_ids)
        )
    ):
        values.update(
            (
                attribution.provider_payment_link_id,
                attribution.provider_reference_id,
                attribution.provider_payment_id,
            )
        )
    return values


def _serialize_entities(
    session: Session,
    selection: _EvidenceSelection,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for entity_name, spec in _ENTITY_SPECS.items():
        statement = select(spec.model)
        if entity_name == "merchant_policies":
            statement = statement.where(spec.model.id.in_(selection.policy_ids))
        else:
            statement = statement.where(
                spec.model.case_id.in_(selection.case_ids)
                if hasattr(spec.model, "case_id")
                else spec.model.id.in_(selection.case_ids)
            )
        rows = list(session.scalars(statement))
        serialized = [
            _serialize_record(entity_name, row, spec, selection)
            for row in rows
        ]
        serialized.sort(key=lambda item: str(item["id"]))
        result[entity_name] = serialized
    return result


def _serialize_record(
    entity_name: str,
    row: Any,
    spec: _EntitySpec,
    selection: _EvidenceSelection,
) -> dict[str, Any]:
    values = {field: getattr(row, field) for field in spec.fields}
    if entity_name == "merchant_policies":
        values["merchant_id"] = selection.merchant_replacements[values["merchant_id"]]
    elif entity_name == "payment_cases":
        values["case_reference"] = selection.case_reference_replacements.get(
            values["case_reference"], values["case_reference"]
        )
        values["merchant_id"] = selection.merchant_replacements[values["merchant_id"]]
        values["payment_id"] = selection.payment_replacements.get(values["payment_id"])
        values["subscription_id"] = selection.subscription_replacements.get(
            values["subscription_id"]
        )
        values["customer_id"] = None
        values["error_description"] = None
        if values["assessment_fingerprint"] is not None:
            values["assessment_fingerprint"] = _synthetic_hash(
                "assessment", row.id
            )
    elif entity_name == "case_events":
        values["event_data"] = _safe_case_event_data(
            row.event_type, row.event_data
        )
    elif entity_name == "strategy_proposals":
        values["assessment_fingerprint"] = _synthetic_hash(
            "strategy-assessment", row.id
        )
        values["strategy_input_fingerprint"] = _synthetic_hash(
            "strategy-input", row.id
        )
        if values["provider_response_id"] is not None:
            values["provider_response_id"] = f"public_demo_model_response_{row.id.hex[:12]}"
    elif entity_name == "policy_decisions":
        values["strategy_input_fingerprint"] = _synthetic_hash(
            "policy-strategy-input", row.id
        )
        values["policy_fingerprint"] = _synthetic_hash("policy", row.id)
        values["authorization_input_fingerprint"] = _synthetic_hash(
            "authorization-input", row.id
        )
    elif entity_name == "approval_requests":
        values["decided_by"] = (
            "public_demo_operator" if values["decided_at"] is not None else None
        )
        values["decision_note"] = None
    elif entity_name == "recovery_actions":
        values["idempotency_key"] = _synthetic_hash("idempotency", row.id)
        values["request_fingerprint"] = _synthetic_hash("request", row.id)
        values["external_reference_id"] = (
            f"public_demo_payment_link_{row.id.hex[:12]}"
            if values["external_reference_id"] is not None
            else None
        )
        values["external_reference"] = (
            f"public_demo_ref_{row.id.hex[:12]}"
            if values["external_reference"] is not None
            else None
        )
        values["external_url"] = None
    elif entity_name == "recovery_outcome_observations":
        values["provider_payment_id"] = (
            f"public_demo_provider_payment_{row.recovery_action_id.hex[:12]}"
            if values["provider_payment_id"] is not None
            else None
        )
        values["evidence_fingerprint"] = _synthetic_hash(
            "outcome-evidence", row.id
        )
    elif entity_name == "recovery_attributions":
        suffix = row.recovery_action_id.hex[:12]
        values["provider_payment_link_id"] = f"public_demo_payment_link_{suffix}"
        values["provider_reference_id"] = f"public_demo_ref_{suffix}"
        values["provider_payment_id"] = f"public_demo_provider_payment_{suffix}"
        values["evidence_fingerprint"] = _synthetic_hash(
            "attribution-evidence", row.id
        )
    return {field: _json_value(values[field]) for field in spec.fields}


def _safe_case_event_data(
    event_type: str,
    event_data: Mapping[str, Any],
) -> dict[str, Any]:
    allowed: tuple[str, ...]
    if event_type in {DEMO_EVENT_TYPE, OPENAI_EVIDENCE_EVENT_TYPE}:
        allowed = ("scenario_key", "synthetic")
    elif event_type == "ELIGIBILITY_EVALUATED":
        allowed = ("eligibility_decision", "eligibility_reason")
    elif event_type in {"FAILURE_DIAGNOSED", "FAILURE_REDIAGNOSED"}:
        allowed = (
            "failure_category",
            "recovery_disposition",
            "diagnosis_reason",
        )
    else:
        allowed = ()
    return {
        key: _json_value(event_data[key])
        for key in allowed
        if key in event_data
        and isinstance(event_data[key], (str, bool, int, float, type(None)))
    }


def _validate_sanitized_entities(
    entities: Mapping[str, list[dict[str, Any]]],
    sensitive_values: Iterable[str],
) -> None:
    rendered = json.dumps(entities, sort_keys=True)
    leaked = [value for value in sensitive_values if value and value in rendered]
    if leaked:
        raise PublicDemoBundleError("Sensitive source identifiers remain in export")
    if "https://rzp.io/" in rendered or "Authorization" in rendered:
        raise PublicDemoBundleError("Provider URL or credential material remains")
    if re.search(r"\bsk-[A-Za-z0-9_-]{8,}", rendered):
        raise PublicDemoBundleError("Credential-shaped value remains in export")
    if '"raw_payload"' in rendered or '"raw_prompt"' in rendered:
        raise PublicDemoBundleError("Raw provider/model material remains in export")
    for record in entities["recovery_actions"]:
        if record["external_url"] is not None:
            raise PublicDemoBundleError("Payment Link URL remains in export")
    for entity_name, records in entities.items():
        for record in records:
            for key, value in record.items():
                if key.endswith("fingerprint") or key in {"idempotency_key"}:
                    if value is not None and not _HASH_RE.fullmatch(str(value)):
                        raise PublicDemoBundleError(
                            f"Invalid sanitized hash in {entity_name}"
                        )


def _load_bundle(path: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublicDemoImportError("Public demo bundle is unreadable") from error
    if not isinstance(bundle, dict) or set(bundle) != {
        "bundle_version",
        "case_count",
        "entities",
        "checksum_sha256",
    }:
        raise PublicDemoImportError("Public demo bundle envelope is invalid")
    if bundle["bundle_version"] != BUNDLE_VERSION or bundle["case_count"] != 5:
        raise PublicDemoImportError("Public demo bundle version or count is invalid")
    checksum = bundle["checksum_sha256"]
    if not isinstance(checksum, str) or not _HASH_RE.fullmatch(checksum):
        raise PublicDemoImportError("Public demo bundle checksum is invalid")
    payload = {key: value for key, value in bundle.items() if key != "checksum_sha256"}
    if _checksum(payload) != checksum:
        raise PublicDemoImportError("Public demo bundle checksum does not match")
    entities = bundle["entities"]
    if not isinstance(entities, dict) or set(entities) != set(_ENTITY_SPECS):
        raise PublicDemoImportError("Public demo bundle entities are invalid")
    for entity_name, spec in _ENTITY_SPECS.items():
        records = entities[entity_name]
        if not isinstance(records, list):
            raise PublicDemoImportError("Public demo entity collection is invalid")
        for record in records:
            if not isinstance(record, dict) or set(record) != set(spec.fields):
                raise PublicDemoImportError("Public demo entity record is invalid")
    _validate_sanitized_entities(entities, ())
    return bundle


def _guard_import_target(
    session: Session,
    entities: Mapping[str, list[dict[str, Any]]],
) -> None:
    counts = {
        name: int(
            session.scalar(select(func.count()).select_from(spec.model)) or 0
        )
        for name, spec in _ENTITY_SPECS.items()
    }
    webhook_count = int(
        session.scalar(select(func.count()).select_from(WebhookEvent)) or 0
    )
    if not any(counts.values()) and webhook_count == 0:
        return
    exact = webhook_count == 0
    for entity_name, spec in _ENTITY_SPECS.items():
        expected_ids = {UUID(record["id"]) for record in entities[entity_name]}
        actual_ids = set(session.scalars(select(spec.model.id)))
        exact = exact and actual_ids == expected_ids
    if exact:
        raise PublicDemoAlreadyImportedError(
            "Exact public demo bundle is already imported"
        )
    raise PublicDemoImportError(
        "Target database contains unexpected operational data"
    )


def _decode_record(
    spec: _EntitySpec,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    columns = {column.key: column for column in spec.model.__table__.columns}
    for field in spec.fields:
        value = record[field]
        if value is None:
            decoded[field] = None
        elif isinstance(columns[field].type, DateTime):
            decoded[field] = datetime.fromisoformat(value)
        elif isinstance(columns[field].type, Uuid):
            decoded[field] = UUID(value)
        else:
            decoded[field] = value
    return decoded


def _assert_model_field_coverage() -> None:
    for entity_name, spec in _ENTITY_SPECS.items():
        actual = {column.key for column in spec.model.__table__.columns}
        expected = set(spec.fields)
        if actual != expected:
            raise PublicDemoBundleError(
                f"Export field review is stale for {entity_name}"
            )


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _synthetic_hash(namespace: str, value: UUID) -> str:
    return hashlib.sha256(
        f"{BUNDLE_VERSION}:{namespace}:{value}".encode("utf-8")
    ).hexdigest()


def _checksum(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "BUNDLE_VERSION",
    "DEFAULT_BUNDLE_PATH",
    "PublicDemoAlreadyImportedError",
    "PublicDemoBundleError",
    "PublicDemoBundleResult",
    "PublicDemoImportError",
    "PublicDemoVerificationResult",
    "export_public_demo_bundle",
    "import_public_demo_bundle",
    "render_public_demo_verification",
    "verify_public_demo_database",
]
