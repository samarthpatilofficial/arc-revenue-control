"""Unit tests for bounded strategy schemas and compatibility rules."""

import pytest
from pydantic import ValidationError

from arc.domain.enums import RecoveryAction, RecoveryDisposition
from arc.intelligence.compatibility import (
    compatible_actions,
    is_action_compatible,
    rule_strategy_for,
    validate_action_compatibility,
)
from arc.intelligence.errors import StrategyNotAllowedError
from arc.intelligence.schemas import StrategyOutput


def test_recovery_action_vocabulary_is_locked() -> None:
    assert {action.value for action in RecoveryAction} == {
        "NO_ACTION",
        "WAIT",
        "REQUEST_RETRY",
        "CREATE_RECOVERY_LINK",
        "REQUEST_PAYMENT_METHOD_UPDATE",
        "ESCALATE_TO_HUMAN",
    }


@pytest.mark.parametrize(
    ("disposition", "expected"),
    [
        (
            RecoveryDisposition.CUSTOMER_ACTION_REQUIRED,
            {
                RecoveryAction.REQUEST_RETRY,
                RecoveryAction.CREATE_RECOVERY_LINK,
                RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
                RecoveryAction.WAIT,
                RecoveryAction.ESCALATE_TO_HUMAN,
            },
        ),
        (
            RecoveryDisposition.RETRY_LATER,
            {
                RecoveryAction.WAIT,
                RecoveryAction.REQUEST_RETRY,
                RecoveryAction.ESCALATE_TO_HUMAN,
            },
        ),
        (
            RecoveryDisposition.ALTERNATE_METHOD_PREFERRED,
            {
                RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
                RecoveryAction.CREATE_RECOVERY_LINK,
                RecoveryAction.ESCALATE_TO_HUMAN,
            },
        ),
        (
            RecoveryDisposition.RECOVERY_STRATEGY_REQUIRED,
            {
                RecoveryAction.REQUEST_RETRY,
                RecoveryAction.CREATE_RECOVERY_LINK,
                RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
                RecoveryAction.ESCALATE_TO_HUMAN,
            },
        ),
    ],
)
def test_ai_compatibility_matrix(
    disposition: RecoveryDisposition,
    expected: set[RecoveryAction],
) -> None:
    assert compatible_actions(disposition) == frozenset(expected)


@pytest.mark.parametrize(
    "disposition",
    [
        RecoveryDisposition.MANUAL_REVIEW,
        RecoveryDisposition.MERCHANT_FIX_REQUIRED,
        RecoveryDisposition.UNKNOWN,
    ],
)
def test_safe_dispositions_bypass_ai(
    disposition: RecoveryDisposition,
) -> None:
    rule = rule_strategy_for(disposition)

    assert rule is not None
    assert rule.action is RecoveryAction.ESCALATE_TO_HUMAN
    assert rule.reason_code.startswith("RULE_")


def test_incompatible_action_is_rejected() -> None:
    assert not is_action_compatible(
        RecoveryDisposition.RETRY_LATER,
        RecoveryAction.CREATE_RECOVERY_LINK,
    )

    with pytest.raises(StrategyNotAllowedError):
        validate_action_compatibility(
            RecoveryDisposition.RETRY_LATER,
            RecoveryAction.CREATE_RECOVERY_LINK,
        )


def test_no_action_cannot_override_pre_strategy_stop_rules() -> None:
    assert all(
        RecoveryAction.NO_ACTION not in compatible_actions(disposition)
        for disposition in RecoveryDisposition
    )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_outside_bounds_is_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        StrategyOutput(
            action=RecoveryAction.WAIT,
            explanation="Bounded test explanation.",
            confidence=confidence,
            re_evaluate_after_seconds=60,
        )


@pytest.mark.parametrize("delay", [-1, 86_401])
def test_re_evaluation_delay_outside_bounds_is_rejected(delay: int) -> None:
    with pytest.raises(ValidationError):
        StrategyOutput(
            action=RecoveryAction.WAIT,
            explanation="Bounded test explanation.",
            confidence=0.5,
            re_evaluate_after_seconds=delay,
        )


def test_structured_output_rejects_additional_authority_fields() -> None:
    with pytest.raises(ValidationError):
        StrategyOutput.model_validate(
            {
                "action": "WAIT",
                "explanation": "Bounded test explanation.",
                "confidence": 0.5,
                "re_evaluate_after_seconds": 60,
                "authorized": True,
            }
        )


def test_explanation_length_is_bounded_locally() -> None:
    with pytest.raises(ValidationError):
        StrategyOutput(
            action=RecoveryAction.WAIT,
            explanation="x" * 501,
            confidence=0.5,
            re_evaluate_after_seconds=60,
        )
