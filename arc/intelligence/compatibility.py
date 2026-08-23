"""Deterministic strategy bypass and disposition/action compatibility rules."""

from dataclasses import dataclass

from arc.domain.enums import RecoveryAction, RecoveryDisposition
from arc.intelligence.errors import StrategyNotAllowedError

STRATEGY_RULESET_VERSION = "arc-strategy-rules-v1"

_COMPATIBLE_ACTIONS: dict[RecoveryDisposition, frozenset[RecoveryAction]] = {
    RecoveryDisposition.CUSTOMER_ACTION_REQUIRED: frozenset(
        {
            RecoveryAction.REQUEST_RETRY,
            RecoveryAction.CREATE_RECOVERY_LINK,
            RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
            RecoveryAction.WAIT,
            RecoveryAction.ESCALATE_TO_HUMAN,
        }
    ),
    RecoveryDisposition.RETRY_LATER: frozenset(
        {
            RecoveryAction.WAIT,
            RecoveryAction.REQUEST_RETRY,
            RecoveryAction.ESCALATE_TO_HUMAN,
        }
    ),
    RecoveryDisposition.ALTERNATE_METHOD_PREFERRED: frozenset(
        {
            RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
            RecoveryAction.CREATE_RECOVERY_LINK,
            RecoveryAction.ESCALATE_TO_HUMAN,
        }
    ),
    RecoveryDisposition.RECOVERY_STRATEGY_REQUIRED: frozenset(
        {
            RecoveryAction.REQUEST_RETRY,
            RecoveryAction.CREATE_RECOVERY_LINK,
            RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
            RecoveryAction.ESCALATE_TO_HUMAN,
        }
    ),
    RecoveryDisposition.MANUAL_REVIEW: frozenset(
        {RecoveryAction.ESCALATE_TO_HUMAN}
    ),
    RecoveryDisposition.MERCHANT_FIX_REQUIRED: frozenset(
        {RecoveryAction.ESCALATE_TO_HUMAN}
    ),
    RecoveryDisposition.UNKNOWN: frozenset(
        {RecoveryAction.ESCALATE_TO_HUMAN}
    ),
}

_AI_REASON_CODES = {
    RecoveryAction.NO_ACTION: "AI_PROPOSED_NO_ACTION",
    RecoveryAction.WAIT: "AI_PROPOSED_WAIT",
    RecoveryAction.REQUEST_RETRY: "AI_PROPOSED_REQUEST_RETRY",
    RecoveryAction.CREATE_RECOVERY_LINK: (
        "AI_PROPOSED_CREATE_RECOVERY_LINK"
    ),
    RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE: (
        "AI_PROPOSED_PAYMENT_METHOD_UPDATE"
    ),
    RecoveryAction.ESCALATE_TO_HUMAN: (
        "AI_PROPOSED_HUMAN_ESCALATION"
    ),
}


@dataclass(frozen=True, slots=True)
class RuleStrategy:
    """Deterministic proposal that bypasses probabilistic reasoning."""

    action: RecoveryAction
    reason_code: str
    explanation: str


_RULE_STRATEGIES = {
    RecoveryDisposition.MANUAL_REVIEW: RuleStrategy(
        action=RecoveryAction.ESCALATE_TO_HUMAN,
        reason_code="RULE_MANUAL_REVIEW_REQUIRED",
        explanation="Deterministic assessment requires operator review.",
    ),
    RecoveryDisposition.MERCHANT_FIX_REQUIRED: RuleStrategy(
        action=RecoveryAction.ESCALATE_TO_HUMAN,
        reason_code="RULE_MERCHANT_FIX_REQUIRED",
        explanation="Merchant-side configuration requires operator action.",
    ),
    RecoveryDisposition.UNKNOWN: RuleStrategy(
        action=RecoveryAction.ESCALATE_TO_HUMAN,
        reason_code="RULE_UNKNOWN_DISPOSITION_ESCALATION",
        explanation="The recovery disposition is unknown and must be reviewed.",
    ),
}


def compatible_actions(
    disposition: RecoveryDisposition,
) -> frozenset[RecoveryAction]:
    """Return the complete bounded action set for one disposition."""

    return _COMPATIBLE_ACTIONS[disposition]


def is_action_compatible(
    disposition: RecoveryDisposition,
    action: RecoveryAction,
) -> bool:
    """Return whether deterministic rules accept the model proposal."""

    return action in compatible_actions(disposition)


def validate_action_compatibility(
    disposition: RecoveryDisposition,
    action: RecoveryAction,
) -> None:
    """Reject a structurally valid but financially incompatible action."""

    if not is_action_compatible(disposition, action):
        raise StrategyNotAllowedError(
            "Strategy proposal is incompatible with deterministic diagnosis"
        )


def rule_strategy_for(
    disposition: RecoveryDisposition,
) -> RuleStrategy | None:
    """Return a safe deterministic AI-bypass proposal when required."""

    return _RULE_STRATEGIES.get(disposition)


def ai_reason_code(action: RecoveryAction) -> str:
    """Derive a stable machine reason code from an accepted model action."""

    return _AI_REASON_CODES[action]
