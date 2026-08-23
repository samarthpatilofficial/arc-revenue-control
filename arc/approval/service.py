"""Transactional, decision-scoped human approval application service."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from arc.approval.audit import APPROVAL_AUDIT_SOURCE, append_approval_audit
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    PolicyDecisionResult,
)
from arc.domain.models import ApprovalRequest, PaymentCase, PolicyDecision
from arc.reconciliation.state_machine import transition_case


class ApprovalError(ValueError):
    """Base operator-safe approval failure."""

    reason_code = "APPROVAL_NOT_ALLOWED"


class ApprovalNotFoundError(LookupError):
    """Raised when an approval or policy decision cannot be found."""

    reason_code = "APPROVAL_NOT_FOUND"


class ApprovalNotAllowedError(ApprovalError):
    """Raised when current policy or case truth cannot accept approval."""


class ApprovalDecisionConflictError(ApprovalError):
    """Raised when a terminal approval is asked to change direction."""

    reason_code = "APPROVAL_DECISION_CONFLICT"


@dataclass(frozen=True, slots=True)
class ApprovalRequestResult:
    """Sanitized projection returned by approval application operations."""

    approval_request_id: UUID
    case_id: UUID
    policy_decision_id: UUID
    status: ApprovalStatus
    case_state: CaseState
    idempotent: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class HumanApprovalService:
    """Create and decide approvals under the payment-case row lock."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def ensure_approval_request(
        self,
        policy_decision_id: UUID,
    ) -> ApprovalRequestResult:
        """Create one pending request for one current approval decision."""

        with self._session_factory() as session:
            decision_hint = session.get(PolicyDecision, policy_decision_id)
            if decision_hint is None:
                raise ApprovalNotFoundError("Policy decision was not found")
            payment_case = _lock_case(session, decision_hint.case_id)
            decision = _lock_decision(session, policy_decision_id)
            _validate_current_approval_context(payment_case, decision)

            existing = session.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.policy_decision_id == decision.id
                )
            )
            if existing is not None:
                return _to_result(existing, payment_case, idempotent=True)

            requested_at = self._clock()
            _require_aware(requested_at)
            approval = ApprovalRequest(
                case_id=payment_case.id,
                policy_decision_id=decision.id,
                status=ApprovalStatus.PENDING,
                requested_at=requested_at,
            )
            session.add(approval)
            session.flush()
            append_approval_audit(session, approval)
            result = _to_result(approval, payment_case, idempotent=False)
            session.commit()
            return result

    def decide_approval(
        self,
        approval_request_id: UUID,
        decision: ApprovalStatus,
        *,
        decided_by: str,
        note: str | None = None,
    ) -> ApprovalRequestResult:
        """Record one irreversible approved or rejected operator decision."""

        if decision not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ApprovalNotAllowedError(
                "Approval decision must be APPROVED or REJECTED"
            )
        operator = _bounded_required(decided_by, maximum=100, name="operator")
        bounded_note = _bounded_optional(note, maximum=500, name="note")

        with self._session_factory() as session:
            approval_hint = session.get(ApprovalRequest, approval_request_id)
            if approval_hint is None:
                raise ApprovalNotFoundError("Approval request was not found")
            payment_case = _lock_case(session, approval_hint.case_id)
            approval = session.scalar(
                select(ApprovalRequest)
                .where(ApprovalRequest.id == approval_request_id)
                .with_for_update()
            )
            if approval is None:
                raise ApprovalNotFoundError("Approval request was not found")

            if approval.status is not ApprovalStatus.PENDING:
                if approval.status is decision:
                    return _to_result(
                        approval,
                        payment_case,
                        idempotent=True,
                    )
                raise ApprovalDecisionConflictError(
                    "A terminal approval decision cannot be changed"
                )

            policy_decision = _lock_decision(
                session,
                approval.policy_decision_id,
            )
            _validate_current_approval_context(payment_case, policy_decision)
            if approval.case_id != payment_case.id:
                raise ApprovalNotAllowedError(
                    "Approval request does not belong to the current case"
                )

            decided_at = self._clock()
            _require_aware(decided_at)
            approval.status = decision
            approval.decided_at = decided_at
            approval.decided_by = operator
            approval.decision_note = bounded_note
            append_approval_audit(session, approval)

            if decision is ApprovalStatus.REJECTED:
                transition_case(
                    session,
                    payment_case,
                    CaseState.ESCALATED,
                    reason_code="HUMAN_APPROVAL_REJECTED",
                    source=APPROVAL_AUDIT_SOURCE,
                    metadata={
                        "approval_request_id": str(approval.id),
                        "policy_decision_id": str(policy_decision.id),
                    },
                )

            result = _to_result(approval, payment_case, idempotent=False)
            session.commit()
            return result


def _lock_case(session: Session, case_id: UUID) -> PaymentCase:
    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.id == case_id)
        .with_for_update()
    )
    if payment_case is None:
        raise ApprovalNotFoundError("Payment case was not found")
    return payment_case


def _lock_decision(session: Session, decision_id: UUID) -> PolicyDecision:
    decision = session.scalar(
        select(PolicyDecision)
        .where(PolicyDecision.id == decision_id)
        .with_for_update()
    )
    if decision is None:
        raise ApprovalNotFoundError("Policy decision was not found")
    return decision


def _validate_current_approval_context(
    payment_case: PaymentCase,
    decision: PolicyDecision,
) -> None:
    if payment_case.current_state is not CaseState.POLICY_VALIDATED:
        raise ApprovalNotAllowedError(
            "Case state does not allow a human approval decision"
        )
    if (
        decision.case_id != payment_case.id
        or decision.superseded_at is not None
        or decision.result is not PolicyDecisionResult.REQUIRES_APPROVAL
    ):
        raise ApprovalNotAllowedError(
            "Only the current approval-required policy decision may be approved"
        )


def _bounded_required(value: str, *, maximum: int, name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized or len(normalized) > maximum:
        raise ApprovalNotAllowedError(f"Approval {name} is invalid")
    return normalized


def _bounded_optional(
    value: str | None,
    *,
    maximum: int,
    name: str,
) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ApprovalNotAllowedError(f"Approval {name} is invalid")
    return normalized


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApprovalNotAllowedError("Approval clock must be timezone-aware")


def _to_result(
    approval: ApprovalRequest,
    payment_case: PaymentCase,
    *,
    idempotent: bool,
) -> ApprovalRequestResult:
    return ApprovalRequestResult(
        approval_request_id=approval.id,
        case_id=approval.case_id,
        policy_decision_id=approval.policy_decision_id,
        status=approval.status,
        case_state=payment_case.current_state,
        idempotent=idempotent,
    )
