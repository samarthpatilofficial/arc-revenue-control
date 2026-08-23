"""Canonical deterministic fingerprints for merchant authorization."""

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from arc.domain.enums import FailureCategory, RecoveryAction
from arc.domain.models import MerchantPolicy
from arc.policy.schemas import PolicyConfiguration

POLICY_RULESET_VERSION = "arc-merchant-policy-v1"
AUTHORIZATION_RULESET_VERSION = "arc-authorization-v1"


def _hash_facts(facts: dict[str, Any]) -> str:
    serialized = json.dumps(
        facts,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _canonicalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        normalized = [_canonicalize_json(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ),
        )
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"unsupported_type": type(value).__name__}


def build_policy_fingerprint(
    policy: MerchantPolicy | None,
    configuration: PolicyConfiguration | None,
) -> str:
    """Hash normalized usable policy or a safe missing/invalid representation."""

    if policy is None:
        facts: dict[str, Any] = {
            "policy_status": "policy_missing",
            "policy_ruleset_version": POLICY_RULESET_VERSION,
        }
    elif configuration is None:
        facts = {
            "policy_status": "policy_invalid",
            "policy_ruleset_version": POLICY_RULESET_VERSION,
            "automation_enabled": _canonicalize_json(
                policy.automation_enabled
            ),
            "allowed_actions": _canonicalize_json(policy.allowed_actions),
            "max_automated_attempts": _canonicalize_json(
                policy.max_automated_attempts
            ),
            "max_contact_attempts": _canonicalize_json(
                policy.max_contact_attempts
            ),
            "recovery_window_minutes": _canonicalize_json(
                policy.recovery_window_minutes
            ),
            "high_value_threshold_minor": _canonicalize_json(
                policy.high_value_threshold_minor
            ),
            "require_approval_above_minor": _canonicalize_json(
                policy.require_approval_above_minor
            ),
            "stopping_rules": _canonicalize_json(policy.stopping_rules),
        }
    else:
        facts = {
            "policy_status": "valid",
            "policy_ruleset_version": POLICY_RULESET_VERSION,
            "automation_enabled": configuration.automation_enabled,
            "allowed_actions": sorted(
                action.value for action in configuration.allowed_actions
            ),
            "max_automated_attempts": (
                configuration.max_automated_attempts
            ),
            "max_contact_attempts": configuration.max_contact_attempts,
            "recovery_window_minutes": configuration.recovery_window_minutes,
            "high_value_threshold_minor": (
                configuration.high_value_threshold_minor
            ),
            "require_approval_above_minor": (
                configuration.require_approval_above_minor
            ),
            "stopping_rules": {
                "blocked_failure_categories": sorted(
                    category.value
                    for category in configuration.blocked_failure_categories
                ),
                "blocked_payment_methods": sorted(
                    configuration.blocked_payment_methods
                ),
                "require_approval_actions": sorted(
                    action.value
                    for action in configuration.require_approval_actions
                ),
            },
        }
    return _hash_facts(facts)


def build_authorization_input_fingerprint(
    *,
    strategy_proposal_id: UUID,
    strategy_input_fingerprint: str,
    assessment_fingerprint: str,
    policy_fingerprint: str,
    action: RecoveryAction,
    attempt_count: int,
    contact_attempt_count: int,
    amount_minor: int | None,
    failure_category: FailureCategory | None,
    payment_method: str | None,
    recovery_window_ends_at: datetime | None,
    recovery_window_expired: bool | None,
) -> str:
    """Hash only deterministic facts with authorization authority."""

    return _hash_facts(
        {
            "authorization_ruleset_version": AUTHORIZATION_RULESET_VERSION,
            "strategy_proposal_id": str(strategy_proposal_id),
            "strategy_input_fingerprint": strategy_input_fingerprint,
            "assessment_fingerprint": assessment_fingerprint,
            "policy_fingerprint": policy_fingerprint,
            "action": action.value,
            "attempt_count": attempt_count,
            "contact_attempt_count": contact_attempt_count,
            "amount_minor": amount_minor,
            "failure_category": (
                failure_category.value if failure_category is not None else None
            ),
            "payment_method": (
                payment_method.strip().lower()
                if payment_method is not None
                else None
            ),
            "recovery_window_ends_at": (
                recovery_window_ends_at.isoformat()
                if recovery_window_ends_at is not None
                else None
            ),
            "recovery_window_expired": recovery_window_expired,
        }
    )
