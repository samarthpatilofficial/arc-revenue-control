"""Strict application-side merchant policy validation contracts."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from arc.domain.enums import FailureCategory, RecoveryAction
from arc.domain.models import MerchantPolicy


class PolicyConfigurationError(ValueError):
    """Raised when persisted merchant policy JSON is unsafe to interpret."""


class StoppingRules(BaseModel):
    """Small typed stopping-rule vocabulary with no expression language."""

    model_config = ConfigDict(extra="forbid")

    blocked_failure_categories: list[FailureCategory] = Field(
        default_factory=list
    )
    blocked_payment_methods: list[str] = Field(default_factory=list)
    require_approval_actions: list[RecoveryAction] = Field(default_factory=list)

    @field_validator(
        "blocked_failure_categories",
        "blocked_payment_methods",
        "require_approval_actions",
        mode="before",
    )
    @classmethod
    def require_json_list(cls, value: Any) -> Any:
        if type(value) is not list:
            raise ValueError("Stopping-rule values must be JSON arrays")
        return value

    @field_validator("blocked_payment_methods")
    @classmethod
    def normalize_payment_methods(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Payment methods must be non-empty strings")
            normalized.append(value.strip().lower())
        return normalized


@dataclass(frozen=True, slots=True)
class PolicyConfiguration:
    """Canonical validated policy values used by deterministic authorization."""

    automation_enabled: bool
    allowed_actions: frozenset[RecoveryAction]
    max_automated_attempts: int
    max_contact_attempts: int
    recovery_window_minutes: int
    high_value_threshold_minor: int
    require_approval_above_minor: int | None
    blocked_failure_categories: frozenset[FailureCategory]
    blocked_payment_methods: frozenset[str]
    require_approval_actions: frozenset[RecoveryAction]


def validate_policy(policy: MerchantPolicy) -> PolicyConfiguration:
    """Validate and normalize one persisted policy or fail closed."""

    if type(policy.allowed_actions) is not list:
        raise PolicyConfigurationError("allowed_actions must be a JSON array")
    if type(policy.stopping_rules) is not dict:
        raise PolicyConfigurationError("stopping_rules must be a JSON object")
    if not isinstance(policy.automation_enabled, bool):
        raise PolicyConfigurationError("automation_enabled must be boolean")

    numeric_values = (
        policy.max_automated_attempts,
        policy.max_contact_attempts,
        policy.recovery_window_minutes,
        policy.high_value_threshold_minor,
    )
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for value in numeric_values
    ):
        raise PolicyConfigurationError("Policy numeric limits are invalid")
    threshold = policy.require_approval_above_minor
    if threshold is not None and (
        not isinstance(threshold, int)
        or isinstance(threshold, bool)
        or threshold < 0
    ):
        raise PolicyConfigurationError("Approval threshold is invalid")

    try:
        allowed_actions = frozenset(
            RecoveryAction(value)
            for value in policy.allowed_actions
            if isinstance(value, str)
        )
        if len(allowed_actions) != len(set(policy.allowed_actions)):
            raise ValueError("allowed_actions contains malformed values")
        stopping_rules = StoppingRules.model_validate(policy.stopping_rules)
    except (TypeError, ValueError, ValidationError) as error:
        raise PolicyConfigurationError(
            "Merchant policy configuration is invalid"
        ) from error

    return PolicyConfiguration(
        automation_enabled=policy.automation_enabled,
        allowed_actions=allowed_actions,
        max_automated_attempts=policy.max_automated_attempts,
        max_contact_attempts=policy.max_contact_attempts,
        recovery_window_minutes=policy.recovery_window_minutes,
        high_value_threshold_minor=policy.high_value_threshold_minor,
        require_approval_above_minor=threshold,
        blocked_failure_categories=frozenset(
            stopping_rules.blocked_failure_categories
        ),
        blocked_payment_methods=frozenset(
            stopping_rules.blocked_payment_methods
        ),
        require_approval_actions=frozenset(
            stopping_rules.require_approval_actions
        ),
    )
