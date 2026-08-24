"""Read-only semantic validation for ARC's persisted demo evidence."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arc.db.session import get_session_factory
from arc.demo.markers import (
    ALREADY_CAPTURED_PROTECTION,
    DEMO_EVENT_SOURCE,
    DEMO_EVENT_TYPE,
    HARD_STOP_ATTENTION,
    HIGH_VALUE_APPROVAL,
    RESERVED_DEMO_SCENARIO_KEYS,
)
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    PolicyDecisionResult,
    ProviderMode,
    RecoveryOutcomeStatus,
)
from arc.domain.models import (
    ApprovalRequest,
    CaseEvent,
    PaymentCase,
    PolicyDecision,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
)
from arc.outcomes import calculate_recovery_metrics
from arc.read_models import get_case_detail
from arc.read_models.schemas import DataOrigin

SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class DemoPreflightCheck:
    """One bounded readiness assertion with a sanitized failure explanation."""

    label: str
    ready: bool
    missing: str | None = None


@dataclass(frozen=True, slots=True)
class DemoPreflightResult:
    """Complete read-only readiness result."""

    checks: tuple[DemoPreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.ready for check in self.checks)


def run_demo_preflight(
    *,
    session_factory: SessionFactory | None = None,
) -> DemoPreflightResult:
    """Inspect persisted demo state without writes or external API calls."""

    try:
        factory = session_factory or get_session_factory()
        with factory() as session:
            # PostgreSQL enforces the command's read-only contract even if this
            # module is changed incorrectly in the future.
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(select(1)).scalar_one()
            return _inspect_demo_state(session)
    except (SQLAlchemyError, OSError):
        return _database_unavailable_result()


def render_demo_preflight(result: DemoPreflightResult) -> str:
    """Render stable, identifier-free console output."""

    lines = ["ARC Demo Preflight", "------------------"]
    for check in result.checks:
        label = f"{check.label} "
        dots = "." * max(1, 25 - len(label))
        lines.append(f"{label}{dots} {'READY' if check.ready else 'NOT READY'}")
        if not check.ready and check.missing:
            lines.append(f"  Missing: {check.missing}")
    lines.extend(
        ["", f"DEMO STATUS: {'READY' if result.ready else 'NOT READY'}"]
    )
    return "\n".join(lines)


def _inspect_demo_state(session: Session) -> DemoPreflightResult:
    cases = {item.id: item for item in session.scalars(select(PaymentCase))}
    markers = list(
        session.scalars(
            select(CaseEvent).where(
                CaseEvent.event_type == DEMO_EVENT_TYPE,
                CaseEvent.source == DEMO_EVENT_SOURCE,
            )
        )
    )
    synthetic_case_ids = {marker.case_id for marker in markers}
    scenario_cases = _scenario_case_map(markers, cases)

    decisions = list(session.scalars(select(PolicyDecision)))
    approvals = list(session.scalars(select(ApprovalRequest)))
    attributions = list(session.scalars(select(RecoveryAttribution)))
    observations = list(session.scalars(select(RecoveryOutcomeObservation)))
    observations_by_id = {item.id: item for item in observations}

    real_candidates = [
        item
        for item in attributions
        if item.case_id not in synthetic_case_ids
        and item.provider_mode is ProviderMode.TEST
        and item.recovered_amount_minor > 0
        and cases.get(item.case_id) is not None
        and cases[item.case_id].current_state is CaseState.RECOVERED
    ]
    evidenced_real = [
        item
        for item in real_candidates
        if _has_recovered_outcome(item, observations_by_id)
    ]

    high_value_ready = _high_value_ready(
        scenario_cases.get(HIGH_VALUE_APPROVAL),
        decisions,
        approvals,
    )
    already_captured_ready = _already_captured_ready(
        scenario_cases.get(ALREADY_CAPTURED_PROTECTION),
    )
    hard_stop_ready = _hard_stop_ready(
        scenario_cases.get(HARD_STOP_ATTENTION),
    )
    synthetic_separation_ready = _synthetic_separation_ready(
        session,
        markers,
        scenario_cases,
        observations,
        attributions,
    )
    evidence_metrics_ready = _evidence_metrics_ready(
        session,
        synthetic_case_ids,
        attributions,
    )
    mode_isolation_ready = _mode_isolation_ready(
        observations,
        observations_by_id,
        attributions,
    )

    return DemoPreflightResult(
        checks=(
            DemoPreflightCheck("Database", True),
            DemoPreflightCheck(
                "Real TEST recovery",
                bool(real_candidates),
                "No non-synthetic recovered Test Mode attribution was found.",
            ),
            DemoPreflightCheck(
                "High-value approval",
                high_value_ready,
                "The reserved high-value case is not pending policy-scoped approval.",
            ),
            DemoPreflightCheck(
                "Already-captured case",
                already_captured_ready,
                "The reserved captured case is not recovered without an action.",
            ),
            DemoPreflightCheck(
                "Hard-stop case",
                hard_stop_ready,
                "The reserved hard-stop case is not terminal without an action.",
            ),
            DemoPreflightCheck(
                "Evidence attribution",
                bool(evidenced_real),
                "Test attribution is not paired with a recovered provider outcome.",
            ),
            DemoPreflightCheck(
                "Synthetic separation",
                synthetic_separation_ready,
                "Exactly three correctly labelled offline scenarios are required.",
            ),
            DemoPreflightCheck(
                "Evidence metrics",
                evidence_metrics_ready,
                "Synthetic recovered state is affecting evidence-backed metrics.",
            ),
            DemoPreflightCheck(
                "Mode isolation",
                mode_isolation_ready,
                "Test and live provider evidence is not cleanly isolated.",
            ),
        )
    )


def _scenario_case_map(
    markers: list[CaseEvent],
    cases: dict[object, PaymentCase],
) -> dict[str, PaymentCase]:
    result: dict[str, PaymentCase] = {}
    for marker in markers:
        key = marker.event_data.get("scenario_key")
        if not isinstance(key, str) or key not in RESERVED_DEMO_SCENARIO_KEYS:
            continue
        payment_case = cases.get(marker.case_id)
        if payment_case is not None and key not in result:
            result[key] = payment_case
    return result


def _current_decision(
    payment_case: PaymentCase,
    decisions: list[PolicyDecision],
) -> PolicyDecision | None:
    current = [
        item
        for item in decisions
        if item.case_id == payment_case.id and item.superseded_at is None
    ]
    return max(current, key=lambda item: item.evaluated_at, default=None)


def _high_value_ready(
    payment_case: PaymentCase | None,
    decisions: list[PolicyDecision],
    approvals: list[ApprovalRequest],
) -> bool:
    if payment_case is None or payment_case.amount is None:
        return False
    decision = _current_decision(payment_case, decisions)
    if (
        decision is None
        or decision.result is not PolicyDecisionResult.REQUIRES_APPROVAL
        or decision.approval_threshold_minor is None
        or payment_case.amount < decision.approval_threshold_minor
    ):
        return False
    return any(
        approval.case_id == payment_case.id
        and approval.policy_decision_id == decision.id
        and approval.status is ApprovalStatus.PENDING
        for approval in approvals
    )


def _already_captured_ready(payment_case: PaymentCase | None) -> bool:
    if payment_case is None:
        return False
    reconciled_capture = any(
        event.event_type == "RECONCILIATION_FOUND_ALREADY_CAPTURED"
        for event in payment_case.case_events
    )
    return (
        payment_case.current_state is CaseState.RECOVERED
        and reconciled_capture
        and not payment_case.recovery_actions
        and not payment_case.attributions
    )


def _hard_stop_ready(payment_case: PaymentCase | None) -> bool:
    return bool(
        payment_case is not None
        and payment_case.current_state
        in {CaseState.EXHAUSTED, CaseState.ESCALATED}
        and not payment_case.recovery_actions
    )


def _has_recovered_outcome(
    attribution: RecoveryAttribution,
    observations_by_id: dict[object, RecoveryOutcomeObservation],
) -> bool:
    outcome = observations_by_id.get(attribution.outcome_observation_id)
    return bool(
        outcome is not None
        and outcome.case_id == attribution.case_id
        and outcome.recovery_action_id == attribution.recovery_action_id
        and outcome.provider_mode is ProviderMode.TEST
        and outcome.outcome_status is RecoveryOutcomeStatus.RECOVERED
        and outcome.currency == attribution.currency
        and outcome.amount_paid_minor >= attribution.recovered_amount_minor
    )


def _synthetic_separation_ready(
    session: Session,
    markers: list[CaseEvent],
    scenario_cases: dict[str, PaymentCase],
    observations: list[RecoveryOutcomeObservation],
    attributions: list[RecoveryAttribution],
) -> bool:
    marker_keys = [marker.event_data.get("scenario_key") for marker in markers]
    markers_valid = (
        len(markers) == len(RESERVED_DEMO_SCENARIO_KEYS)
        and set(marker_keys) == RESERVED_DEMO_SCENARIO_KEYS
        and len({marker.case_id for marker in markers}) == len(markers)
        and all(
            marker.event_data
            == {"scenario_key": marker.event_data.get("scenario_key"), "synthetic": True}
            for marker in markers
        )
    )
    projected_synthetic = len(scenario_cases) == len(RESERVED_DEMO_SCENARIO_KEYS)
    if projected_synthetic:
        projected_synthetic = all(
            (detail := get_case_detail(session, payment_case.case_reference))
            is not None
            and detail.data_origin is DataOrigin.SYNTHETIC_DEMO
            for payment_case in scenario_cases.values()
        )
    synthetic_case_ids = {item.id for item in scenario_cases.values()}
    no_live_evidence = not any(
        item.case_id in synthetic_case_ids
        and item.provider_mode is ProviderMode.LIVE
        for item in [*observations, *attributions]
    )
    return markers_valid and projected_synthetic and no_live_evidence


def _evidence_metrics_ready(
    session: Session,
    synthetic_case_ids: set[object],
    attributions: list[RecoveryAttribution],
) -> bool:
    if any(item.case_id in synthetic_case_ids for item in attributions):
        return False
    grouped: dict[tuple[ProviderMode, str], list[RecoveryAttribution]] = defaultdict(list)
    for item in attributions:
        grouped[(item.provider_mode, item.currency)].append(item)
    for (mode, currency), items in grouped.items():
        metrics = calculate_recovery_metrics(
            session,
            provider_mode=mode,
            currency=currency,
        )
        if (
            metrics.recovered_cases != len({item.case_id for item in items})
            or metrics.recovered_revenue_minor
            != sum(item.recovered_amount_minor for item in items)
        ):
            return False
    return True


def _mode_isolation_ready(
    observations: list[RecoveryOutcomeObservation],
    observations_by_id: dict[object, RecoveryOutcomeObservation],
    attributions: list[RecoveryAttribution],
) -> bool:
    modes_by_case: dict[object, set[ProviderMode]] = defaultdict(set)
    for item in observations:
        modes_by_case[item.case_id].add(item.provider_mode)
    if any(len(modes) > 1 for modes in modes_by_case.values()):
        return False
    return all(
        (outcome := observations_by_id.get(item.outcome_observation_id))
        is not None
        and outcome.provider_mode is item.provider_mode
        and outcome.currency == item.currency
        for item in attributions
    )


def _database_unavailable_result() -> DemoPreflightResult:
    return DemoPreflightResult(
        checks=(
            DemoPreflightCheck(
                "Database",
                False,
                "ARC could not read the configured PostgreSQL database.",
            ),
        )
    )


__all__ = [
    "DemoPreflightCheck",
    "DemoPreflightResult",
    "render_demo_preflight",
    "run_demo_preflight",
]
