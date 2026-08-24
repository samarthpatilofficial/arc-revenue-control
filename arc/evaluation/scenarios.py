"""Deterministic generation of the versioned 100-case synthetic dataset."""

from collections import Counter
from random import Random
from typing import Literal

from arc.domain.enums import RecoveryAction
from arc.evaluation.models import (
    PolicyProfile,
    ScenarioKind,
    SyntheticOutcome,
    SyntheticScenario,
)

DATASET_VERSION = "arc-synthetic-recovery-v1"
DATASET_SEED = 1403
DATASET_CASE_COUNT = 100

_SCENARIO_COUNTS: dict[ScenarioKind, int] = {
    ScenarioKind.ALREADY_CAPTURED: 10,
    ScenarioKind.PLATFORM_RETRY_ACTIVE: 10,
    ScenarioKind.CUSTOMER_AUTHENTICATION: 12,
    ScenarioKind.INSUFFICIENT_FUNDS: 12,
    ScenarioKind.ISSUER_BANK: 10,
    ScenarioKind.GATEWAY_NETWORK: 10,
    ScenarioKind.RETRY_EXHAUSTED: 8,
    ScenarioKind.HIGH_VALUE_APPROVAL: 8,
    ScenarioKind.ATTEMPT_LIMIT: 5,
    ScenarioKind.CONTACT_LIMIT: 5,
    ScenarioKind.HARD_STOP: 4,
    ScenarioKind.INCOMPLETE_UNKNOWN: 3,
    ScenarioKind.DUPLICATE_ACTION: 2,
    ScenarioKind.STALE_CAPTURE: 1,
}

_PLAUSIBLE_AMOUNTS_MINOR = (
    19_900,
    49_900,
    75_000,
    99_900,
    125_000,
    180_000,
    249_900,
    350_000,
    499_900,
    750_000,
)
_HIGH_VALUE_AMOUNTS_MINOR = (1_250_000, 2_500_000, 5_000_000)


def generate_scenarios() -> tuple[SyntheticScenario, ...]:
    """Return exactly 100 stable PII-free INR scenarios."""

    rng = Random(DATASET_SEED)
    blueprint = [
        (kind, occurrence)
        for kind, count in _SCENARIO_COUNTS.items()
        for occurrence in range(count)
    ]
    rng.shuffle(blueprint)
    scenarios = tuple(
        _build_scenario(
            scenario_id=f"eval_case_{position:04d}",
            kind=kind,
            occurrence=occurrence,
            rng=rng,
        )
        for position, (kind, occurrence) in enumerate(blueprint, start=1)
    )
    if len(scenarios) != DATASET_CASE_COUNT:
        raise RuntimeError("Synthetic evaluation dataset size is invalid")
    if len({scenario.scenario_id for scenario in scenarios}) != len(scenarios):
        raise RuntimeError("Synthetic evaluation case identifiers are not unique")
    if Counter(scenario.kind for scenario in scenarios) != Counter(
        _SCENARIO_COUNTS
    ):
        raise RuntimeError("Synthetic evaluation scenario composition changed")
    return scenarios


def scenario_counts() -> dict[str, int]:
    """Return the versioned dataset composition for documentation/tests."""

    return {kind.value: count for kind, count in _SCENARIO_COUNTS.items()}


def _amount(rng: Random, *, high_value: bool = False) -> int:
    values = (
        _HIGH_VALUE_AMOUNTS_MINOR if high_value else _PLAUSIBLE_AMOUNTS_MINOR
    )
    return rng.choice(values)


def _base(
    *,
    scenario_id: str,
    kind: ScenarioKind,
    amount_minor: int,
    identity_kind: Literal["payment", "subscription"] = "payment",
    payment_status: str | None = "failed",
    subscription_status: str | None = None,
    payment_method: str | None = "card",
    error_reason: str | None = None,
    error_source: str | None = None,
    error_step: str | None = None,
    attempt_count: int = 0,
    contact_attempt_count: int = 0,
    detected_minutes_ago: int = 30,
    offline_action: RecoveryAction | None = None,
    synthetic_outcome: SyntheticOutcome = SyntheticOutcome.NOT_APPLICABLE,
    policy_profile: PolicyProfile = PolicyProfile.STANDARD,
    execution_request_count: int = 1,
    stale_capture_before_execution: bool = False,
) -> SyntheticScenario:
    return SyntheticScenario(
        scenario_id=scenario_id,
        kind=kind,
        amount_minor=amount_minor,
        identity_kind=identity_kind,
        payment_status=payment_status,
        subscription_status=subscription_status,
        payment_method=payment_method,
        error_reason=error_reason,
        error_source=error_source,
        error_step=error_step,
        attempt_count=attempt_count,
        contact_attempt_count=contact_attempt_count,
        detected_minutes_ago=detected_minutes_ago,
        offline_action=offline_action,
        synthetic_outcome=synthetic_outcome,
        policy_profile=policy_profile,
        execution_request_count=execution_request_count,
        stale_capture_before_execution=stale_capture_before_execution,
    )


def _build_scenario(
    *,
    scenario_id: str,
    kind: ScenarioKind,
    occurrence: int,
    rng: Random,
) -> SyntheticScenario:
    amount = _amount(rng)
    if kind is ScenarioKind.ALREADY_CAPTURED:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            payment_status="captured",
        )
    if kind is ScenarioKind.PLATFORM_RETRY_ACTIVE:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            identity_kind="subscription",
            payment_status=None,
            subscription_status="pending",
            payment_method=None,
        )
    if kind is ScenarioKind.CUSTOMER_AUTHENTICATION:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            error_reason="incorrect_otp",
            error_source="customer",
            error_step="payment_authentication",
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
            synthetic_outcome=(
                SyntheticOutcome.SUCCESSFUL_CAPTURE
                if occurrence < 8
                else SyntheticOutcome.UNRESOLVED
            ),
        )
    if kind is ScenarioKind.INSUFFICIENT_FUNDS:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            payment_method="upi",
            error_reason="insufficient_funds",
            error_source="customer",
            error_step="payment_authorization",
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
            synthetic_outcome=(
                SyntheticOutcome.SUCCESSFUL_CAPTURE
                if occurrence < 6
                else SyntheticOutcome.UNRESOLVED
            ),
        )
    if kind is ScenarioKind.ISSUER_BANK:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            error_reason="bank_technical_error",
            error_source="issuer_bank",
            error_step="payment_authorization",
            offline_action=RecoveryAction.WAIT,
        )
    if kind is ScenarioKind.GATEWAY_NETWORK:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            payment_method="upi",
            error_reason="gateway_technical_error",
            error_source="gateway",
            error_step="payment_authorization",
            offline_action=RecoveryAction.WAIT,
        )
    if kind is ScenarioKind.RETRY_EXHAUSTED:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            identity_kind="subscription",
            payment_status=None,
            subscription_status="halted",
            payment_method=None,
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
            synthetic_outcome=(
                SyntheticOutcome.SUCCESSFUL_CAPTURE
                if occurrence < 5
                else SyntheticOutcome.UNRESOLVED
            ),
        )
    if kind is ScenarioKind.HIGH_VALUE_APPROVAL:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=_amount(rng, high_value=True),
            error_reason="insufficient_funds",
            error_source="customer",
            error_step="payment_authorization",
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
        )
    if kind is ScenarioKind.ATTEMPT_LIMIT:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            error_reason="incorrect_otp",
            error_source="customer",
            error_step="payment_authentication",
            attempt_count=3,
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
        )
    if kind is ScenarioKind.CONTACT_LIMIT:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            error_reason="insufficient_funds",
            error_source="customer",
            error_step="payment_authorization",
            contact_attempt_count=2,
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
        )
    if kind is ScenarioKind.HARD_STOP:
        if occurrence < 2:
            return _base(
                scenario_id=scenario_id,
                kind=kind,
                amount_minor=amount,
                error_reason="gateway_technical_error",
                error_source="gateway",
                error_step="payment_authorization",
                offline_action=RecoveryAction.REQUEST_RETRY,
                policy_profile=PolicyProfile.BLOCK_FAILURE_CATEGORY,
            )
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            error_reason="incorrect_otp",
            error_source="customer",
            error_step="payment_authentication",
            detected_minutes_ago=2_000,
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
            policy_profile=PolicyProfile.EXPIRED_RECOVERY_WINDOW,
        )
    if kind is ScenarioKind.INCOMPLETE_UNKNOWN:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
        )
    if kind is ScenarioKind.DUPLICATE_ACTION:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            error_reason="incorrect_otp",
            error_source="customer",
            error_step="payment_authentication",
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
            synthetic_outcome=SyntheticOutcome.SUCCESSFUL_CAPTURE,
            execution_request_count=2,
        )
    if kind is ScenarioKind.STALE_CAPTURE:
        return _base(
            scenario_id=scenario_id,
            kind=kind,
            amount_minor=amount,
            error_reason="incorrect_otp",
            error_source="customer",
            error_step="payment_authentication",
            offline_action=RecoveryAction.CREATE_RECOVERY_LINK,
            stale_capture_before_execution=True,
        )
    raise RuntimeError(f"Unhandled synthetic scenario kind: {kind.value}")
