"""Pure execution-permission rules separating policy and human authority."""

from arc.domain.enums import ApprovalStatus, PolicyDecisionResult
from arc.domain.models import ApprovalRequest, PolicyDecision
from arc.policy.authorization import is_execution_authorized


def is_execution_permitted(
    policy_decision: PolicyDecision,
    approval_request: ApprovalRequest | None = None,
) -> bool:
    """Return whether this exact current decision may reach the executor."""

    if is_execution_authorized(policy_decision):
        return True
    return (
        policy_decision.result is PolicyDecisionResult.REQUIRES_APPROVAL
        and policy_decision.superseded_at is None
        and approval_request is not None
        and approval_request.case_id == policy_decision.case_id
        and approval_request.policy_decision_id == policy_decision.id
        and approval_request.status is ApprovalStatus.APPROVED
    )
