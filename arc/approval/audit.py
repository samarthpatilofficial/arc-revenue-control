"""Bounded audit events for decision-scoped human approvals."""

from sqlalchemy.orm import Session

from arc.domain.enums import ApprovalStatus
from arc.domain.models import ApprovalRequest, CaseEvent

APPROVAL_AUDIT_SOURCE = "HUMAN_APPROVAL"


def append_approval_audit(
    session: Session,
    approval: ApprovalRequest,
) -> None:
    """Append an approval lifecycle event without free-form operator data."""

    event_type = {
        ApprovalStatus.PENDING: "APPROVAL_REQUESTED",
        ApprovalStatus.APPROVED: "APPROVAL_APPROVED",
        ApprovalStatus.REJECTED: "APPROVAL_REJECTED",
    }[approval.status]
    session.add(
        CaseEvent(
            case_id=approval.case_id,
            event_type=event_type,
            source=APPROVAL_AUDIT_SOURCE,
            event_data={
                "approval_request_id": str(approval.id),
                "policy_decision_id": str(approval.policy_decision_id),
                "status": approval.status.value,
            },
        )
    )
