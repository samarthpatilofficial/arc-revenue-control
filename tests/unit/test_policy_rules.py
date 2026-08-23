"""Unit tests for strict deterministic merchant authorization rules."""

from datetime import UTC, datetime, timedelta
from inspect import signature

import pytest

from arc.domain.enums import (
    FailureCategory,
    PolicyDecisionResult,
    RecoveryAction,
)
from arc.domain.models import MerchantPolicy
from arc.policy.authorization import (
    AUTOMATED_RECOVERY_ACTIONS,
    CUSTOMER_CONTACT_ACTIONS,
    SAFE_INTERNAL_ACTIONS,
    AuthorizationFacts,
    evaluate_authorization,
)
from arc.policy.fingerprint import build_policy_fingerprint
from arc.policy.schemas import (
    PolicyConfiguration,
    PolicyConfigurationError,
    validate_policy,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _policy(**overrides: object) -> MerchantPolicy:
    values: dict[str, object] = {
        "merchant_id": "merchant_policy_unit",
        "automation_enabled": True,
        "allowed_actions": [
            RecoveryAction.REQUEST_RETRY.value,
            RecoveryAction.CREATE_RECOVERY_LINK.value,
            RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE.value,
        ],
        "max_automated_attempts": 3,
        "max_contact_attempts": 2,
        "recovery_window_minutes": 60,
        "high_value_threshold_minor": 50_000,
        "require_approval_above_minor": 100_000,
        "stopping_rules": {},
    }
    values.update(overrides)
    return MerchantPolicy(**values)


def _configuration(**overrides: object) -> PolicyConfiguration:
    return validate_policy(_policy(**overrides))


def _facts(**overrides: object) -> AuthorizationFacts:
    values: dict[str, object] = {
        "action": RecoveryAction.REQUEST_RETRY,
        "amount_minor": 25_000,
        "attempt_count": 0,
        "contact_attempt_count": 0,
        "detected_at": NOW - timedelta(minutes=10),
        "failure_category": FailureCategory.CUSTOMER_FUNDS,
        "payment_method": "card",
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return AuthorizationFacts(**values)  # type: ignore[arg-type]


def _evaluate(
    *,
    facts: AuthorizationFacts | None = None,
    configuration: PolicyConfiguration | None = None,
    policy_present: bool = True,
):
    return evaluate_authorization(
        facts or _facts(),
        policy_present=policy_present,
        configuration=configuration or _configuration(),
    )


def test_action_classifications_are_explicit_and_disjoint() -> None:
    assert SAFE_INTERNAL_ACTIONS == {
        RecoveryAction.NO_ACTION,
        RecoveryAction.WAIT,
        RecoveryAction.ESCALATE_TO_HUMAN,
    }
    assert AUTOMATED_RECOVERY_ACTIONS == {
        RecoveryAction.REQUEST_RETRY,
        RecoveryAction.CREATE_RECOVERY_LINK,
        RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
    }
    assert CUSTOMER_CONTACT_ACTIONS == {
        RecoveryAction.CREATE_RECOVERY_LINK,
        RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
    }
    assert SAFE_INTERNAL_ACTIONS.isdisjoint(AUTOMATED_RECOVERY_ACTIONS)


def test_known_allowed_actions_parse() -> None:
    configuration = _configuration()

    assert configuration.allowed_actions == AUTOMATED_RECOVERY_ACTIONS


@pytest.mark.parametrize(
    "allowed_actions",
    [
        ["FUTURE_UNKNOWN_ACTION"],
        {"REQUEST_RETRY": True},
        "REQUEST_RETRY",
        [RecoveryAction.REQUEST_RETRY.value, 12],
    ],
)
def test_unknown_or_malformed_allowed_actions_fail_closed(
    allowed_actions: object,
) -> None:
    with pytest.raises(PolicyConfigurationError):
        validate_policy(_policy(allowed_actions=allowed_actions))


def test_valid_stopping_rules_parse_and_normalize() -> None:
    configuration = _configuration(
        stopping_rules={
            "blocked_failure_categories": ["CUSTOMER_FUNDS"],
            "blocked_payment_methods": [" CARD "],
            "require_approval_actions": ["REQUEST_RETRY"],
        }
    )

    assert configuration.blocked_failure_categories == {
        FailureCategory.CUSTOMER_FUNDS
    }
    assert configuration.blocked_payment_methods == {"card"}
    assert configuration.require_approval_actions == {
        RecoveryAction.REQUEST_RETRY
    }


@pytest.mark.parametrize(
    "stopping_rules",
    [
        {"future_rule": []},
        {"blocked_failure_categories": ["FUTURE_CATEGORY"]},
        {"require_approval_actions": ["FUTURE_ACTION"]},
        {"blocked_payment_methods": "card"},
        [],
    ],
)
def test_malformed_stopping_rules_fail_closed(stopping_rules: object) -> None:
    with pytest.raises(PolicyConfigurationError):
        validate_policy(_policy(stopping_rules=stopping_rules))


def test_policy_fingerprint_is_deterministic_and_order_independent() -> None:
    first = _policy(
        allowed_actions=["REQUEST_RETRY", "CREATE_RECOVERY_LINK"],
        stopping_rules={
            "blocked_payment_methods": ["upi", "card"],
            "require_approval_actions": [
                "CREATE_RECOVERY_LINK",
                "REQUEST_RETRY",
            ],
        },
    )
    second = _policy(
        allowed_actions=["CREATE_RECOVERY_LINK", "REQUEST_RETRY"],
        stopping_rules={
            "require_approval_actions": [
                "REQUEST_RETRY",
                "CREATE_RECOVERY_LINK",
            ],
            "blocked_payment_methods": ["card", "upi"],
        },
    )

    assert build_policy_fingerprint(first, validate_policy(first)) == (
        build_policy_fingerprint(second, validate_policy(second))
    )


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (RecoveryAction.NO_ACTION, "SAFE_INTERNAL_NO_ACTION"),
        (RecoveryAction.WAIT, "SAFE_INTERNAL_WAIT"),
        (
            RecoveryAction.ESCALATE_TO_HUMAN,
            "SAFE_INTERNAL_HUMAN_ESCALATION",
        ),
    ],
)
def test_safe_internal_actions_authorize_without_policy(
    action: RecoveryAction,
    reason: str,
) -> None:
    result = evaluate_authorization(
        _facts(action=action),
        policy_present=False,
        configuration=None,
    )

    assert result.result is PolicyDecisionResult.AUTHORIZED
    assert result.reason_code == reason


def test_external_action_without_policy_is_blocked() -> None:
    result = evaluate_authorization(
        _facts(), policy_present=False, configuration=None
    )

    assert result.result is PolicyDecisionResult.BLOCKED
    assert result.reason_code == "POLICY_NOT_CONFIGURED"


def test_action_not_allowlisted_is_blocked() -> None:
    result = _evaluate(configuration=_configuration(allowed_actions=[]))

    assert result.reason_code == "ACTION_NOT_ALLOWED_BY_POLICY"


def test_automation_disabled_requires_approval() -> None:
    result = _evaluate(
        configuration=_configuration(automation_enabled=False)
    )

    assert result.result is PolicyDecisionResult.REQUIRES_APPROVAL
    assert result.reason_code == "AUTOMATION_DISABLED_REQUIRES_APPROVAL"


@pytest.mark.parametrize(
    ("attempt_count", "expected_result", "expected_reason"),
    [
        (2, PolicyDecisionResult.AUTHORIZED, "POLICY_AUTHORIZED"),
        (
            3,
            PolicyDecisionResult.BLOCKED,
            "MAX_AUTOMATED_ATTEMPTS_REACHED",
        ),
    ],
)
def test_automated_attempt_limit_boundary(
    attempt_count: int,
    expected_result: PolicyDecisionResult,
    expected_reason: str,
) -> None:
    result = _evaluate(facts=_facts(attempt_count=attempt_count))

    assert result.result is expected_result
    assert result.reason_code == expected_reason


def test_zero_automated_attempt_limit_blocks_first_external_action() -> None:
    result = _evaluate(
        configuration=_configuration(max_automated_attempts=0)
    )

    assert result.reason_code == "MAX_AUTOMATED_ATTEMPTS_REACHED"


@pytest.mark.parametrize(
    ("contact_count", "expected_result", "expected_reason"),
    [
        (1, PolicyDecisionResult.AUTHORIZED, "POLICY_AUTHORIZED"),
        (
            2,
            PolicyDecisionResult.BLOCKED,
            "MAX_CUSTOMER_CONTACTS_REACHED",
        ),
    ],
)
def test_customer_contact_limit_boundary(
    contact_count: int,
    expected_result: PolicyDecisionResult,
    expected_reason: str,
) -> None:
    result = _evaluate(
        facts=_facts(
            action=RecoveryAction.CREATE_RECOVERY_LINK,
            contact_attempt_count=contact_count,
        )
    )

    assert result.result is expected_result
    assert result.reason_code == expected_reason


def test_zero_contact_limit_blocks_first_customer_contact_action() -> None:
    result = _evaluate(
        facts=_facts(action=RecoveryAction.CREATE_RECOVERY_LINK),
        configuration=_configuration(max_contact_attempts=0),
    )

    assert result.reason_code == "MAX_CUSTOMER_CONTACTS_REACHED"


@pytest.mark.parametrize(
    ("window_minutes", "detected_at", "reason"),
    [
        (60, NOW - timedelta(minutes=59), "POLICY_AUTHORIZED"),
        (60, NOW - timedelta(minutes=61), "RECOVERY_WINDOW_EXPIRED"),
        (0, NOW, "RECOVERY_WINDOW_NOT_CONFIGURED"),
    ],
)
def test_recovery_window_rules(
    window_minutes: int,
    detected_at: datetime,
    reason: str,
) -> None:
    result = _evaluate(
        facts=_facts(detected_at=detected_at),
        configuration=_configuration(
            recovery_window_minutes=window_minutes
        ),
    )

    assert result.reason_code == reason


@pytest.mark.parametrize(
    ("amount", "expected_result"),
    [
        (99_999, PolicyDecisionResult.AUTHORIZED),
        (100_000, PolicyDecisionResult.REQUIRES_APPROVAL),
        (100_001, PolicyDecisionResult.REQUIRES_APPROVAL),
    ],
)
def test_approval_threshold_boundary(
    amount: int,
    expected_result: PolicyDecisionResult,
) -> None:
    result = _evaluate(facts=_facts(amount_minor=amount))

    assert result.result is expected_result


def test_missing_amount_fails_closed_for_external_action() -> None:
    result = _evaluate(facts=_facts(amount_minor=None))

    assert result.reason_code == "POLICY_AMOUNT_CONTEXT_MISSING"


@pytest.mark.parametrize(
    ("rules", "facts", "expected_result", "reason"),
    [
        (
            {"blocked_failure_categories": ["CUSTOMER_FUNDS"]},
            _facts(),
            PolicyDecisionResult.BLOCKED,
            "STOPPING_RULE_FAILURE_CATEGORY",
        ),
        (
            {"blocked_payment_methods": ["card"]},
            _facts(),
            PolicyDecisionResult.BLOCKED,
            "STOPPING_RULE_PAYMENT_METHOD",
        ),
        (
            {"require_approval_actions": ["REQUEST_RETRY"]},
            _facts(),
            PolicyDecisionResult.REQUIRES_APPROVAL,
            "STOPPING_RULE_REQUIRES_APPROVAL",
        ),
    ],
)
def test_stopping_rule_results(
    rules: dict[str, object],
    facts: AuthorizationFacts,
    expected_result: PolicyDecisionResult,
    reason: str,
) -> None:
    result = _evaluate(
        facts=facts,
        configuration=_configuration(stopping_rules=rules),
    )

    assert result.result is expected_result
    assert result.reason_code == reason


def test_hard_stop_outranks_approval_threshold() -> None:
    result = _evaluate(
        facts=_facts(amount_minor=500_000, attempt_count=3)
    )

    assert result.result is PolicyDecisionResult.BLOCKED
    assert result.reason_code == "MAX_AUTOMATED_ATTEMPTS_REACHED"


def test_model_confidence_has_no_authorization_input() -> None:
    parameters = signature(evaluate_authorization).parameters

    assert "confidence" not in parameters
    assert "strategy_source" not in parameters
