"""Idempotent offline scenario seeding behind an explicit demo-mode gate."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from arc.approval import HumanApprovalService
from arc.assessment import CaseAssessmentService
from arc.config import Settings, get_settings
from arc.db.session import get_session_factory
from arc.demo.markers import DEMO_EVENT_SOURCE, DEMO_EVENT_TYPE
from arc.domain.enums import (
    CaseState,
    PolicyDecisionResult,
    RecoveryAction,
)
from arc.domain.models import (
    CaseEvent,
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
)
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelResult,
    StrategyOutput,
)
from arc.intelligence.service import StrategyService
from arc.persistence import append_case_event, create_payment_case
from arc.policy.service import MerchantAuthorizationService
from arc.reconciliation.state_machine import transition_case

HIGH_VALUE_APPROVAL = "HIGH_VALUE_APPROVAL"
ALREADY_CAPTURED_PROTECTION = "ALREADY_CAPTURED_PROTECTION"
HARD_STOP_ATTENTION = "HARD_STOP_ATTENTION"

_HIGH_VALUE_CASE_REFERENCE = "demo_high_value_approval_v1"
_CAPTURED_CASE_REFERENCE = "demo_already_captured_protection_v1"
_HARD_STOP_CASE_REFERENCE = "demo_hard_stop_attention_v1"

_DEMO_MODEL = "arc-demo-offline-strategy-v1"
_DEMO_CURRENCY = "INR"


class DemoModeDisabledError(RuntimeError):
    """Raised before database access when explicit demo mode is disabled."""


class DemoSeedConflictError(RuntimeError):
    """Raised when reserved synthetic identities contain unexpected data."""


@dataclass(frozen=True, slots=True)
class DemoScenarioResult:
    scenario_key: str
    case_reference: str
    created: bool


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    scenarios: tuple[DemoScenarioResult, ...]

    @property
    def created_count(self) -> int:
        return sum(item.created for item in self.scenarios)


@dataclass(frozen=True, slots=True)
class _OfflineStrategyClient:
    """In-process bounded proposal source; it has no HTTP capability."""

    scenario_key: str
    action: RecoveryAction
    explanation: str
    confidence: float

    @property
    def model(self) -> str:
        return _DEMO_MODEL

    def propose(self, context: StrategyContext) -> StrategyModelResult:
        del context
        return StrategyModelResult(
            output=StrategyOutput(
                action=self.action,
                explanation=self.explanation,
                confidence=self.confidence,
                re_evaluate_after_seconds=None,
            ),
            provider_response_id=f"offline-demo-{self.scenario_key.lower()}",
            model=self.model,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            latency_ms=0,
        )


def seed_demo_scenarios(
    *,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> DemoSeedResult:
    """Create three controlled scenarios without provider or model calls."""

    resolved_settings = settings or get_settings()
    if not resolved_settings.demo_mode:
        raise DemoModeDisabledError(
            "Demo scenario seeding requires ARC_DEMO_MODE=true"
        )
    factory = session_factory or get_session_factory()
    return DemoSeedResult(
        scenarios=(
            _seed_high_value_approval(factory, resolved_settings),
            _seed_already_captured(factory),
            _seed_hard_stop(factory, resolved_settings),
        )
    )


def _seed_high_value_approval(
    session_factory: Callable[[], Session],
    settings: Settings,
) -> DemoScenarioResult:
    case_id, created = _ensure_failed_case(
        session_factory,
        scenario_key=HIGH_VALUE_APPROVAL,
        case_reference=_HIGH_VALUE_CASE_REFERENCE,
        merchant_id="demo_merchant_high_value_v1",
        amount_minor=2_500_000,
        attempt_count=0,
        policy_values={
            "automation_enabled": True,
            "allowed_actions": [RecoveryAction.CREATE_RECOVERY_LINK.value],
            "max_automated_attempts": 3,
            "max_contact_attempts": 3,
            "recovery_window_minutes": 1_440,
            "high_value_threshold_minor": 1_000_000,
            "require_approval_above_minor": 2_500_000,
            "stopping_rules": {},
        },
    )
    state = _case_state(session_factory, case_id)
    if state is CaseState.RECONCILING:
        CaseAssessmentService(
            session_factory=session_factory,
            clock=lambda: _case_clock(session_factory, case_id, 1),
        ).assess_case(case_id)
        state = _case_state(session_factory, case_id)
    if state is CaseState.DIAGNOSED:
        StrategyService(
            session_factory=session_factory,
            model_client=_OfflineStrategyClient(
                scenario_key=HIGH_VALUE_APPROVAL,
                action=RecoveryAction.CREATE_RECOVERY_LINK,
                explanation=(
                    "A bounded recovery link is appropriate, subject to "
                    "deterministic high-value approval."
                ),
                confidence=0.93,
            ),
            settings=settings,
            clock=lambda: _case_clock(session_factory, case_id, 2),
        ).generate_strategy(case_id)
        state = _case_state(session_factory, case_id)
    if state is CaseState.DECISIONED:
        MerchantAuthorizationService(
            session_factory=session_factory,
            clock=lambda: _case_clock(session_factory, case_id, 3),
        ).evaluate_policy(case_id)
        state = _case_state(session_factory, case_id)
    if state is CaseState.POLICY_VALIDATED:
        decision = _current_decision(session_factory, case_id)
        if decision.result is not PolicyDecisionResult.REQUIRES_APPROVAL:
            raise DemoSeedConflictError(
                "High-value demo policy did not require approval"
            )
        HumanApprovalService(
            session_factory=session_factory,
            clock=lambda: _case_clock(session_factory, case_id, 4),
        ).ensure_approval_request(decision.id)
    elif state not in {CaseState.ESCALATED, CaseState.EXHAUSTED}:
        raise DemoSeedConflictError(
            "High-value demo scenario has an unexpected lifecycle state"
        )
    return DemoScenarioResult(
        scenario_key=HIGH_VALUE_APPROVAL,
        case_reference=_HIGH_VALUE_CASE_REFERENCE,
        created=created,
    )


def _seed_already_captured(
    session_factory: Callable[[], Session],
) -> DemoScenarioResult:
    with session_factory() as session:
        existing = _existing_scenario(
            session,
            ALREADY_CAPTURED_PROTECTION,
            _CAPTURED_CASE_REFERENCE,
        )
        if existing is not None:
            return DemoScenarioResult(
                scenario_key=ALREADY_CAPTURED_PROTECTION,
                case_reference=_CAPTURED_CASE_REFERENCE,
                created=False,
            )

        seeded_at = datetime.now(UTC) - timedelta(seconds=4)
        payment_case = create_payment_case(
            session,
            PaymentCase(
                case_reference=_CAPTURED_CASE_REFERENCE,
                merchant_id="demo_merchant_already_captured_v1",
                payment_id="demo_payment_already_captured_v1",
                amount=75_000,
                currency=_DEMO_CURRENCY,
                razorpay_payment_status="failed",
                razorpay_payment_method="card",
                error_source="issuer_bank",
                error_step="payment_authorization",
                error_reason="bank_technical_error",
                detected_at=seeded_at + timedelta(seconds=1),
                last_reconciled_at=seeded_at + timedelta(seconds=2),
            ),
        )
        _append_seed_marker(
            session,
            payment_case,
            ALREADY_CAPTURED_PROTECTION,
            seeded_at,
        )
        _append_detection(
            session,
            payment_case,
            seeded_at + timedelta(seconds=1),
        )
        transition_case(
            session,
            payment_case,
            CaseState.RECONCILING,
            reason_code="AUTHORITATIVE_RECONCILIATION_STARTED",
            source=DEMO_EVENT_SOURCE,
        )
        append_case_event(
            session,
            CaseEvent(
                case_id=payment_case.id,
                event_type="RECONCILIATION_CONFIRMED_FAILURE",
                source=DEMO_EVENT_SOURCE,
                event_data={"reason_code": "RECONCILIATION_CONFIRMED_FAILURE"},
                created_at=seeded_at + timedelta(seconds=2),
            ),
        )
        captured_at = seeded_at + timedelta(seconds=3)
        payment_case.razorpay_payment_status = "captured"
        payment_case.error_code = None
        payment_case.error_description = None
        payment_case.error_source = None
        payment_case.error_step = None
        payment_case.error_reason = None
        payment_case.last_reconciled_at = captured_at
        transition_case(
            session,
            payment_case,
            CaseState.RECOVERED,
            reason_code="RECONCILIATION_FOUND_ALREADY_CAPTURED",
            source=DEMO_EVENT_SOURCE,
        )
        payment_case.resolved_at = captured_at
        append_case_event(
            session,
            CaseEvent(
                case_id=payment_case.id,
                event_type="RECONCILIATION_FOUND_ALREADY_CAPTURED",
                source=DEMO_EVENT_SOURCE,
                event_data={
                    "reason_code": "RECONCILIATION_FOUND_ALREADY_CAPTURED"
                },
                created_at=captured_at,
            ),
        )
        session.commit()
    return DemoScenarioResult(
        scenario_key=ALREADY_CAPTURED_PROTECTION,
        case_reference=_CAPTURED_CASE_REFERENCE,
        created=True,
    )


def _seed_hard_stop(
    session_factory: Callable[[], Session],
    settings: Settings,
) -> DemoScenarioResult:
    case_id, created = _ensure_failed_case(
        session_factory,
        scenario_key=HARD_STOP_ATTENTION,
        case_reference=_HARD_STOP_CASE_REFERENCE,
        merchant_id="demo_merchant_hard_stop_v1",
        amount_minor=180_000,
        attempt_count=2,
        policy_values={
            "automation_enabled": True,
            "allowed_actions": [RecoveryAction.CREATE_RECOVERY_LINK.value],
            "max_automated_attempts": 2,
            "max_contact_attempts": 3,
            "recovery_window_minutes": 1_440,
            "high_value_threshold_minor": 1_000_000,
            "require_approval_above_minor": None,
            "stopping_rules": {},
        },
    )
    state = _case_state(session_factory, case_id)
    if state is CaseState.RECONCILING:
        CaseAssessmentService(
            session_factory=session_factory,
            clock=lambda: _case_clock(session_factory, case_id, 1),
        ).assess_case(case_id)
        state = _case_state(session_factory, case_id)
    if state is CaseState.DIAGNOSED:
        StrategyService(
            session_factory=session_factory,
            model_client=_OfflineStrategyClient(
                scenario_key=HARD_STOP_ATTENTION,
                action=RecoveryAction.CREATE_RECOVERY_LINK,
                explanation=(
                    "A recovery link could help, but deterministic attempt "
                    "limits retain final authority."
                ),
                confidence=0.91,
            ),
            settings=settings,
            clock=lambda: _case_clock(session_factory, case_id, 2),
        ).generate_strategy(case_id)
        state = _case_state(session_factory, case_id)
    if state is CaseState.DECISIONED:
        decision = MerchantAuthorizationService(
            session_factory=session_factory,
            clock=lambda: _case_clock(session_factory, case_id, 3),
        ).evaluate_policy(case_id)
        if (
            decision.result is not PolicyDecisionResult.BLOCKED
            or decision.reason_code != "MAX_AUTOMATED_ATTEMPTS_REACHED"
        ):
            raise DemoSeedConflictError(
                "Hard-stop demo policy did not enforce the attempt limit"
            )
        state = _case_state(session_factory, case_id)
    if state is not CaseState.EXHAUSTED:
        raise DemoSeedConflictError(
            "Hard-stop demo scenario has an unexpected lifecycle state"
        )
    return DemoScenarioResult(
        scenario_key=HARD_STOP_ATTENTION,
        case_reference=_HARD_STOP_CASE_REFERENCE,
        created=created,
    )


def _ensure_failed_case(
    session_factory: Callable[[], Session],
    *,
    scenario_key: str,
    case_reference: str,
    merchant_id: str,
    amount_minor: int,
    attempt_count: int,
    policy_values: dict[str, object],
) -> tuple[UUID, bool]:
    with session_factory() as session:
        existing = _existing_scenario(session, scenario_key, case_reference)
        if existing is not None:
            return existing.id, False
        _ensure_demo_policy(
            session,
            merchant_id=merchant_id,
            values=policy_values,
        )
        seeded_at = datetime.now(UTC) - timedelta(seconds=3)
        payment_case = create_payment_case(
            session,
            PaymentCase(
                case_reference=case_reference,
                merchant_id=merchant_id,
                payment_id=f"demo_payment_{scenario_key.lower()}_v1",
                amount=amount_minor,
                currency=_DEMO_CURRENCY,
                razorpay_payment_status="failed",
                razorpay_payment_method="card",
                error_source="customer",
                error_step="payment_authorization",
                error_reason="insufficient_funds",
                attempt_count=attempt_count,
                contact_attempt_count=0,
                detected_at=seeded_at + timedelta(seconds=1),
                last_reconciled_at=seeded_at + timedelta(seconds=2),
            ),
        )
        _append_seed_marker(session, payment_case, scenario_key, seeded_at)
        _append_detection(
            session,
            payment_case,
            seeded_at + timedelta(seconds=1),
        )
        transition_case(
            session,
            payment_case,
            CaseState.RECONCILING,
            reason_code="AUTHORITATIVE_RECONCILIATION_STARTED",
            source=DEMO_EVENT_SOURCE,
        )
        append_case_event(
            session,
            CaseEvent(
                case_id=payment_case.id,
                event_type="RECONCILIATION_CONFIRMED_FAILURE",
                source=DEMO_EVENT_SOURCE,
                event_data={"reason_code": "RECONCILIATION_CONFIRMED_FAILURE"},
                created_at=seeded_at + timedelta(seconds=2),
            ),
        )
        session.commit()
        return payment_case.id, True


def _existing_scenario(
    session: Session,
    scenario_key: str,
    case_reference: str,
) -> PaymentCase | None:
    payment_case = session.scalar(
        select(PaymentCase).where(
            PaymentCase.case_reference == case_reference
        )
    )
    if payment_case is None:
        return None
    marker = session.scalar(
        select(CaseEvent).where(
            CaseEvent.case_id == payment_case.id,
            CaseEvent.event_type == DEMO_EVENT_TYPE,
            CaseEvent.source == DEMO_EVENT_SOURCE,
        )
    )
    if marker is None or marker.event_data != {
        "scenario_key": scenario_key,
        "synthetic": True,
    }:
        raise DemoSeedConflictError(
            "A reserved demo case reference contains non-demo data"
        )
    return payment_case


def _ensure_demo_policy(
    session: Session,
    *,
    merchant_id: str,
    values: dict[str, object],
) -> None:
    existing = session.scalar(
        select(MerchantPolicy).where(
            MerchantPolicy.merchant_id == merchant_id
        )
    )
    expected = {"merchant_id": merchant_id, **values}
    if existing is None:
        session.add(MerchantPolicy(**expected))
        session.flush()
        return
    if any(getattr(existing, key) != value for key, value in expected.items()):
        raise DemoSeedConflictError(
            "A reserved demo merchant policy contains unexpected data"
        )


def _append_seed_marker(
    session: Session,
    payment_case: PaymentCase,
    scenario_key: str,
    seeded_at: datetime,
) -> None:
    append_case_event(
        session,
        CaseEvent(
            case_id=payment_case.id,
            event_type=DEMO_EVENT_TYPE,
            source=DEMO_EVENT_SOURCE,
            event_data={"scenario_key": scenario_key, "synthetic": True},
            created_at=seeded_at,
        ),
    )


def _append_detection(
    session: Session,
    payment_case: PaymentCase,
    detected_at: datetime,
) -> None:
    append_case_event(
        session,
        CaseEvent(
            case_id=payment_case.id,
            event_type="CASE_DETECTED",
            source=DEMO_EVENT_SOURCE,
            event_data={"reason_code": "CASE_DETECTED"},
            created_at=detected_at,
        ),
    )


def _case_state(
    session_factory: Callable[[], Session],
    case_id: UUID,
) -> CaseState:
    with session_factory() as session:
        payment_case = session.get(PaymentCase, case_id)
        if payment_case is None:
            raise DemoSeedConflictError("Synthetic demo case was not found")
        return payment_case.current_state


def _case_clock(
    session_factory: Callable[[], Session],
    case_id: UUID,
    seconds_after_reconciliation: int,
) -> datetime:
    with session_factory() as session:
        payment_case = session.get(PaymentCase, case_id)
        if payment_case is None or payment_case.last_reconciled_at is None:
            raise DemoSeedConflictError(
                "Synthetic demo reconciliation timestamp is missing"
            )
        minimum = payment_case.last_reconciled_at + timedelta(
            seconds=seconds_after_reconciliation
        )
        return max(datetime.now(UTC), minimum)


def _current_decision(
    session_factory: Callable[[], Session],
    case_id: UUID,
) -> PolicyDecision:
    with session_factory() as session:
        decision = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.case_id == case_id,
                PolicyDecision.superseded_at.is_(None),
            )
        )
        if decision is None:
            raise DemoSeedConflictError(
                "Synthetic demo policy decision is missing"
            )
        session.expunge(decision)
        return decision
