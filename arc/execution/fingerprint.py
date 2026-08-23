"""Canonical idempotency and provider-request fingerprints."""

import hashlib
import json
from typing import Any
from uuid import UUID

from arc.domain.enums import RecoveryAction

EXECUTOR_RULESET_VERSION = "arc-recovery-executor-v1"


def _hash_facts(facts: dict[str, Any]) -> str:
    serialized = json.dumps(
        facts,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def build_execution_idempotency_key(
    *,
    policy_decision_id: UUID,
    authorization_input_fingerprint: str,
    strategy_proposal_id: UUID,
    action: RecoveryAction,
) -> str:
    """Bind execution identity to the exact governed authorization."""

    return _hash_facts(
        {
            "executor_ruleset_version": EXECUTOR_RULESET_VERSION,
            "policy_decision_id": str(policy_decision_id),
            "authorization_input_fingerprint": (
                authorization_input_fingerprint
            ),
            "strategy_proposal_id": str(strategy_proposal_id),
            "action": action.value,
        }
    )


def build_payment_link_request_fingerprint(
    *,
    action: RecoveryAction,
    amount_minor: int,
    currency: str,
    reference_id: str,
    expire_by: int,
) -> str:
    """Hash the complete PII-free provider request contract."""

    return _hash_facts(
        {
            "executor_ruleset_version": EXECUTOR_RULESET_VERSION,
            "action": action.value,
            "amount": amount_minor,
            "currency": currency.strip().upper(),
            "reference_id": reference_id,
            "expire_by": expire_by,
            "accept_partial": False,
            "description": "ARC recovery payment",
            "notify": {"email": False, "sms": False},
            "reminder_enable": False,
        }
    )


def build_internal_request_fingerprint(
    *,
    action: RecoveryAction,
    policy_decision_id: UUID,
    re_evaluate_after_seconds: int | None,
) -> str:
    """Hash one internal bounded action without model confidence."""

    return _hash_facts(
        {
            "executor_ruleset_version": EXECUTOR_RULESET_VERSION,
            "action": action.value,
            "policy_decision_id": str(policy_decision_id),
            "re_evaluate_after_seconds": re_evaluate_after_seconds,
        }
    )
