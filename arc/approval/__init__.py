"""Decision-scoped human approval services."""

from arc.approval.permission import is_execution_permitted
from arc.approval.service import (
    ApprovalDecisionConflictError,
    ApprovalError,
    ApprovalNotAllowedError,
    ApprovalNotFoundError,
    ApprovalRequestResult,
    HumanApprovalService,
)

__all__ = [
    "ApprovalDecisionConflictError",
    "ApprovalError",
    "ApprovalNotAllowedError",
    "ApprovalNotFoundError",
    "ApprovalRequestResult",
    "HumanApprovalService",
    "is_execution_permitted",
]
