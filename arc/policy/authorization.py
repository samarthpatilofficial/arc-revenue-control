"""Pure deterministic merchant authorization rules and precedence."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from arc.domain.enums import (
    FailureCategory,
    PolicyDecisionResult,
    RecoveryAction,
)
from arc.domain.models import PolicyDecision
from arc.policy.schemas import PolicyConfiguration

SAFE_INTERNAL_ACTIONS = frozenset(
    {
        RecoveryAction.NO_ACTION,
        RecoveryAction.WAIT,
        RecoveryAction.ESCALATE_TO_HUMAN,
    }
)
AUTOMATED_RECOVERY_ACTIONS = frozenset(
    {
        RecoveryAction.REQUEST_RETRY,
        RecoveryAction.CREATE_RECOVERY_LINK,
        RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
    }
)
CUSTOMER_CONTACT_ACTIONS = frozenset(
    {
        RecoveryAction.CREATE_RECOVERY_LINK,
        RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
    }
)


@dataclass(frozen=True, slots=True)
class AuthorizationFacts:
    """Current bounded facts with deterministic policy authority."""

    action: RecoveryAction
    amount_minor: int | None
    attempt_count: int
    contact_attempt_count: int
    detected_at: datetime
    failure_category: FailureCategory | None
    payment_method: str | None
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthorizationEvaluation:
    """Pure result plus bounded metadata for persistence and audit."""

    result: PolicyDecisionResult
    reason_code: str
    explanation: str
    recovery_window_ends_at: datetime | None
    recovery_window_expired: bool | None
    approval_threshold_minor: int | None
    high_value_threshold_minor: int | None
    observed_high_value: bool | None


def _result(
    result: PolicyDecisionResult,
    reason_code: str,
    explanation: str,
    *,
    recovery_window_ends_at: datetime | None = None,
    recovery_window_expired: bool | None = None,
    configuration: PolicyConfiguration | None = None,
    amount_minor: int | None = None,
) -> AuthorizationEvaluation:
    threshold = (
        configuration.require_approval_above_minor
        if configuration is not None
        else None
    )
    high_value_threshold = (
        configuration.high_value_threshold_minor
        if configuration is not None
        else None
    )
    high_value = (
        amount_minor >= high_value_threshold
        if amount_minor is not None and high_value_threshold is not None
        else None
    )
    return AuthorizationEvaluation(
        result=result,
        reason_code=reason_code,
        explanation=explanation,
        recovery_window_ends_at=recovery_window_ends_at,
        recovery_window_expired=recovery_window_expired,
        approval_threshold_minor=threshold,
        high_value_threshold_minor=high_value_threshold,
        observed_high_value=high_value,
    )


def evaluate_authorization(
    facts: AuthorizationFacts,
    *,
    policy_present: bool,
    configuration: PolicyConfiguration | None,
) -> AuthorizationEvaluation:
    """Evaluate one proposal using explicit hard-stop-first precedence."""

    if facts.action in SAFE_INTERNAL_ACTIONS:
        reason = {
            RecoveryAction.NO_ACTION: "SAFE_INTERNAL_NO_ACTION",
            RecoveryAction.WAIT: "SAFE_INTERNAL_WAIT",
            RecoveryAction.ESCALATE_TO_HUMAN: (
                "SAFE_INTERNAL_HUMAN_ESCALATION"
            ),
        }[facts.action]
        return _result(
            PolicyDecisionResult.AUTHORIZED,
            reason,
            "The proposal is an internal safety-preserving action.",
            amount_minor=facts.amount_minor,
        )

    if facts.action not in AUTOMATED_RECOVERY_ACTIONS:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "POLICY_CONFIGURATION_INVALID",
            "The proposal is not a recognized policy-controlled action.",
            amount_minor=facts.amount_minor,
        )
    if not policy_present:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "POLICY_NOT_CONFIGURED",
            "No merchant policy is configured for external recovery.",
            amount_minor=facts.amount_minor,
        )
    if configuration is None:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "POLICY_CONFIGURATION_INVALID",
            "Merchant policy configuration failed strict validation.",
            amount_minor=facts.amount_minor,
        )
    if facts.action not in configuration.allowed_actions:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "ACTION_NOT_ALLOWED_BY_POLICY",
            "The proposed action is not in the merchant allowlist.",
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    if facts.failure_category in configuration.blocked_failure_categories:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "STOPPING_RULE_FAILURE_CATEGORY",
            "A hard stopping rule blocks this failure category.",
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    normalized_method = (
        facts.payment_method.strip().lower()
        if facts.payment_method is not None
        else None
    )
    if normalized_method in configuration.blocked_payment_methods:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "STOPPING_RULE_PAYMENT_METHOD",
            "A hard stopping rule blocks this payment method.",
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )

    if configuration.recovery_window_minutes <= 0:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "RECOVERY_WINDOW_NOT_CONFIGURED",
            "A positive recovery window is required for external recovery.",
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    recovery_window_ends_at = facts.detected_at + timedelta(
        minutes=configuration.recovery_window_minutes
    )
    recovery_window_expired = facts.evaluated_at > recovery_window_ends_at
    if recovery_window_expired:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "RECOVERY_WINDOW_EXPIRED",
            "The merchant recovery window has expired.",
            recovery_window_ends_at=recovery_window_ends_at,
            recovery_window_expired=True,
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    if facts.attempt_count >= configuration.max_automated_attempts:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "MAX_AUTOMATED_ATTEMPTS_REACHED",
            "The automated recovery-attempt limit has been reached.",
            recovery_window_ends_at=recovery_window_ends_at,
            recovery_window_expired=False,
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    if (
        facts.action in CUSTOMER_CONTACT_ACTIONS
        and facts.contact_attempt_count >= configuration.max_contact_attempts
    ):
        return _result(
            PolicyDecisionResult.BLOCKED,
            "MAX_CUSTOMER_CONTACTS_REACHED",
            "The customer-contact limit has been reached.",
            recovery_window_ends_at=recovery_window_ends_at,
            recovery_window_expired=False,
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    if facts.amount_minor is None:
        return _result(
            PolicyDecisionResult.BLOCKED,
            "POLICY_AMOUNT_CONTEXT_MISSING",
            "Amount context is required for external recovery policy.",
            recovery_window_ends_at=recovery_window_ends_at,
            recovery_window_expired=False,
            configuration=configuration,
        )
    if facts.action in configuration.require_approval_actions:
        return _result(
            PolicyDecisionResult.REQUIRES_APPROVAL,
            "STOPPING_RULE_REQUIRES_APPROVAL",
            "Merchant policy requires approval for this action.",
            recovery_window_ends_at=recovery_window_ends_at,
            recovery_window_expired=False,
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    threshold = configuration.require_approval_above_minor
    if threshold is not None and facts.amount_minor >= threshold:
        return _result(
            PolicyDecisionResult.REQUIRES_APPROVAL,
            "AMOUNT_REQUIRES_HUMAN_APPROVAL",
            "The case amount meets the merchant approval threshold.",
            recovery_window_ends_at=recovery_window_ends_at,
            recovery_window_expired=False,
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    if not configuration.automation_enabled:
        return _result(
            PolicyDecisionResult.REQUIRES_APPROVAL,
            "AUTOMATION_DISABLED_REQUIRES_APPROVAL",
            "Merchant automation is disabled, so human approval is required.",
            recovery_window_ends_at=recovery_window_ends_at,
            recovery_window_expired=False,
            configuration=configuration,
            amount_minor=facts.amount_minor,
        )
    return _result(
        PolicyDecisionResult.AUTHORIZED,
        "POLICY_AUTHORIZED",
        "The proposal satisfies all deterministic merchant policy controls.",
        recovery_window_ends_at=recovery_window_ends_at,
        recovery_window_expired=False,
        configuration=configuration,
        amount_minor=facts.amount_minor,
    )


def is_execution_authorized(policy_decision: PolicyDecision) -> bool:
    """Return true only for the current explicitly authorized decision.

    POLICY_VALIDATED state alone is insufficient. A future executor must load
    the current unsuperseded decision and call this helper.
    """

    return (
        policy_decision.result is PolicyDecisionResult.AUTHORIZED
        and policy_decision.superseded_at is None
    )
