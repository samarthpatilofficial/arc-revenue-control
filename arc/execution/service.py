"""Crash-safe governed recovery execution with post-request fencing."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from arc.approval.permission import is_execution_permitted
from arc.config import Settings, get_settings
from arc.domain.enums import (
    CaseState,
    PolicyDecisionResult,
    RecoveryAction,
    RecoveryExecutionStatus,
)
from arc.domain.models import (
    ApprovalRequest,
    PaymentCase,
    PolicyDecision,
    RecoveryActionRecord,
    StrategyProposal,
)
from arc.execution.audit import (
    EXECUTION_AUDIT_SOURCE,
    append_execution_audit,
)
from arc.execution.errors import (
    ExecutionCaseNotFoundError,
    ExecutionConfigurationError,
    ExecutionNotPermittedError,
    ExecutionRequiresPolicyReevaluationError,
)
from arc.execution.fingerprint import (
    build_execution_idempotency_key,
    build_internal_request_fingerprint,
    build_payment_link_request_fingerprint,
)
from arc.integrations.razorpay.payment_links import (
    PaymentLinkCreateRequest,
    PaymentLinkError,
    PaymentLinkGateway,
    PaymentLinkSnapshot,
    PaymentLinkUncertainError,
    RazorpayPaymentLinkClient,
)
from arc.policy.authorization import CUSTOMER_CONTACT_ACTIONS
from arc.policy.current import (
    CurrentAuthorizationError,
    CurrentAuthorizationInputs,
    recompute_current_authorization_inputs,
)
from arc.reconciliation.state_machine import transition_case

EXECUTION_LEASE_SECONDS = 120
PAYMENT_LINK_OPERATIONAL_EXPIRY_SECONDS = 30 * 60

_FINAL_EXECUTION_STATUSES = frozenset(
    {
        RecoveryExecutionStatus.SUCCEEDED,
        RecoveryExecutionStatus.FAILED,
        RecoveryExecutionStatus.CANCELLED,
        RecoveryExecutionStatus.COMPENSATION_REQUIRED,
    }
)
_INTERNAL_SUPPORTED_ACTIONS = frozenset(
    {
        RecoveryAction.WAIT,
        RecoveryAction.NO_ACTION,
        RecoveryAction.ESCALATE_TO_HUMAN,
    }
)
_UNSUPPORTED_ACTIONS = frozenset(
    {
        RecoveryAction.REQUEST_RETRY,
        RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
    }
)


@dataclass(frozen=True, slots=True)
class RecoveryExecutionResult:
    """Sanitized projection of a durable recovery-action ledger row."""

    recovery_action_id: UUID
    case_id: UUID
    policy_decision_id: UUID
    action: RecoveryAction
    execution_status: RecoveryExecutionStatus
    case_state: CaseState
    reason_code: str
    execution_attempt_count: int
    external_reference_id: str | None
    external_reference: str | None
    external_status: str | None
    external_url: str | None
    idempotent: bool


@dataclass(frozen=True, slots=True)
class _ExecutionClaim:
    recovery_action_id: UUID
    case_id: UUID
    action: RecoveryAction
    amount_minor: int | None
    currency: str | None
    reference_id: str | None
    expire_by: int | None


@dataclass(frozen=True, slots=True)
class _ExternalFinalization:
    result: RecoveryExecutionResult
    compensation_required: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecoveryExecutionService:
    """Execute one exact current authorization using durable DB fencing."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        payment_link_gateway: PaymentLinkGateway | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._payment_link_gateway = payment_link_gateway
        self._settings = settings or get_settings()
        self._clock = clock

    def execute(self, case_id: UUID) -> RecoveryExecutionResult:
        """Claim and execute the current policy decision idempotently."""

        prepared = self._prepare_and_claim(case_id)
        if isinstance(prepared, RecoveryExecutionResult):
            return prepared
        if prepared.action is RecoveryAction.CREATE_RECOVERY_LINK:
            return self._execute_payment_link(prepared)
        return self._execute_internal(prepared)

    def _prepare_and_claim(
        self,
        case_id: UUID,
    ) -> _ExecutionClaim | RecoveryExecutionResult:
        now = self._clock()
        _require_aware(now)
        with self._session_factory() as session:
            payment_case = _lock_case(session, case_id)
            proposal = _load_current_proposal(session, payment_case.id)
            decision = _load_current_decision(session, payment_case.id)
            existing = session.scalar(
                select(RecoveryActionRecord)
                .where(RecoveryActionRecord.policy_decision_id == decision.id)
                .with_for_update()
            )
            if existing is not None and (
                existing.execution_status in _FINAL_EXECUTION_STATUSES
            ):
                return _to_result(
                    existing,
                    payment_case,
                    reason_code="RECOVERY_ACTION_ALREADY_FINAL",
                    idempotent=True,
                )
            if payment_case.current_state is not CaseState.POLICY_VALIDATED:
                raise ExecutionRequiresPolicyReevaluationError(
                    "Case state requires policy reevaluation before execution"
                )

            inputs = _current_inputs(
                session,
                payment_case,
                proposal,
                decision,
                evaluated_at=now,
            )
            approval = _load_approval(session, decision.id)
            if not is_execution_permitted(decision, approval):
                raise ExecutionNotPermittedError(
                    "Current authorization does not permit execution"
                )

            if existing is None:
                existing = _build_record(
                    payment_case,
                    proposal,
                    decision,
                    approval,
                    inputs,
                    now=now,
                )
                session.add(existing)
                session.flush()
                append_execution_audit(
                    session,
                    existing,
                    "RECOVERY_ACTION_PREPARED",
                )
            else:
                _validate_existing_record(
                    existing,
                    payment_case,
                    proposal,
                    decision,
                )

            if _has_fresh_lease(existing, now):
                result = _to_result(
                    existing,
                    payment_case,
                    reason_code="EXECUTION_ALREADY_PROCESSING",
                    idempotent=True,
                )
                session.commit()
                return result

            existing.execution_status = RecoveryExecutionStatus.IN_PROGRESS
            existing.execution_started_at = now
            existing.execution_attempt_count += 1
            existing.failed_at = None
            existing.error_code = None
            append_execution_audit(
                session,
                existing,
                "RECOVERY_ACTION_STARTED",
            )
            claim = _to_claim(existing, payment_case)
            session.commit()
            return claim

    def _execute_payment_link(
        self,
        claim: _ExecutionClaim,
    ) -> RecoveryExecutionResult:
        request = _payment_link_request(claim)
        gateway, owned = self._gateway_for_request()
        try:
            try:
                matches = gateway.lookup_by_reference(request.reference_id)
            except PaymentLinkError as error:
                return self._finalize_provider_problem(
                    claim,
                    RecoveryExecutionStatus.INDETERMINATE,
                    error.reason_code,
                    event_type="RECOVERY_ACTION_INDETERMINATE",
                )

            adopted = False
            if len(matches) == 1 and _matches_request(matches[0], request):
                snapshot = matches[0]
                adopted = True
            elif len(matches) == 0:
                try:
                    snapshot = gateway.create(request)
                except PaymentLinkUncertainError as error:
                    return self._finalize_provider_problem(
                        claim,
                        RecoveryExecutionStatus.INDETERMINATE,
                        error.reason_code,
                        event_type="RECOVERY_ACTION_INDETERMINATE",
                    )
                except PaymentLinkError as error:
                    return self._finalize_provider_problem(
                        claim,
                        RecoveryExecutionStatus.FAILED,
                        error.reason_code,
                        event_type="RECOVERY_ACTION_FAILED",
                    )
            else:
                return self._finalize_provider_problem(
                    claim,
                    RecoveryExecutionStatus.INDETERMINATE,
                    "RAZORPAY_PAYMENT_LINK_LOOKUP_AMBIGUOUS",
                    event_type="RECOVERY_ACTION_INDETERMINATE",
                )

            finalized = self._finalize_external_success(
                claim,
                snapshot,
                adopted=adopted,
            )
            if not finalized.compensation_required:
                return finalized.result
            return self._compensate(
                claim,
                snapshot,
                gateway,
            )
        finally:
            if owned:
                close = getattr(gateway, "close", None)
                if callable(close):
                    close()

    def _execute_internal(
        self,
        claim: _ExecutionClaim,
    ) -> RecoveryExecutionResult:
        now = self._clock()
        _require_aware(now)
        with self._session_factory() as session:
            payment_case = _lock_case(session, claim.case_id)
            record = _lock_record(session, claim.recovery_action_id)
            if record.execution_status in _FINAL_EXECUTION_STATUSES:
                return _to_result(
                    record,
                    payment_case,
                    reason_code="RECOVERY_ACTION_ALREADY_FINAL",
                    idempotent=True,
                )
            if not _post_request_context_is_current(
                session,
                payment_case,
                record,
                evaluated_at=now,
            ):
                record.execution_status = RecoveryExecutionStatus.CANCELLED
                record.error_code = (
                    "EXECUTION_REQUIRES_POLICY_REEVALUATION"
                )
                append_execution_audit(
                    session,
                    record,
                    "EXECUTION_BLOCKED_STALE_AUTHORIZATION",
                )
                result = _to_result(
                    record,
                    payment_case,
                    reason_code=record.error_code,
                    idempotent=False,
                )
                session.commit()
                return result

            if record.action in _UNSUPPORTED_ACTIONS:
                record.execution_status = RecoveryExecutionStatus.FAILED
                record.failed_at = now
                record.error_code = "EXECUTOR_ACTION_NOT_IMPLEMENTED"
                append_execution_audit(
                    session,
                    record,
                    "EXECUTOR_ACTION_NOT_IMPLEMENTED",
                )
                transition_case(
                    session,
                    payment_case,
                    CaseState.ESCALATED,
                    reason_code="EXECUTOR_ACTION_NOT_IMPLEMENTED",
                    source=EXECUTION_AUDIT_SOURCE,
                    metadata={"recovery_action_id": str(record.id)},
                )
                result = _to_result(
                    record,
                    payment_case,
                    reason_code=record.error_code,
                    idempotent=False,
                )
                session.commit()
                return result

            if record.action not in _INTERNAL_SUPPORTED_ACTIONS:
                raise ExecutionConfigurationError(
                    "Recovery action has no bounded executor"
                )

            previous_state = payment_case.current_state
            record.execution_status = RecoveryExecutionStatus.SUCCEEDED
            record.executed_at = now
            if record.action is RecoveryAction.WAIT:
                proposal = session.get(
                    StrategyProposal,
                    record.strategy_proposal_id,
                )
                if (
                    proposal is not None
                    and proposal.re_evaluate_after_seconds is not None
                ):
                    record.next_evaluation_at = now + timedelta(
                        seconds=proposal.re_evaluate_after_seconds
                    )
                transition_case(
                    session,
                    payment_case,
                    CaseState.ACTIONED,
                    reason_code="RECOVERY_ACTION_EXECUTED",
                    source=EXECUTION_AUDIT_SOURCE,
                    metadata={"recovery_action_id": str(record.id)},
                )
                transition_case(
                    session,
                    payment_case,
                    CaseState.WAITING_FOR_OUTCOME,
                    reason_code="AWAITING_RECOVERY_OUTCOME",
                    source=EXECUTION_AUDIT_SOURCE,
                    metadata={"recovery_action_id": str(record.id)},
                )
            elif record.action is RecoveryAction.ESCALATE_TO_HUMAN:
                transition_case(
                    session,
                    payment_case,
                    CaseState.ESCALATED,
                    reason_code="RECOVERY_ACTION_ESCALATED_TO_HUMAN",
                    source=EXECUTION_AUDIT_SOURCE,
                    metadata={"recovery_action_id": str(record.id)},
                )
            else:
                transition_case(
                    session,
                    payment_case,
                    CaseState.EXHAUSTED,
                    reason_code="RECOVERY_NO_ACTION_SELECTED",
                    source=EXECUTION_AUDIT_SOURCE,
                    metadata={"recovery_action_id": str(record.id)},
                )
            append_execution_audit(
                session,
                record,
                "RECOVERY_ACTION_SUCCEEDED",
                metadata={
                    "previous_state": previous_state.value,
                    "new_state": payment_case.current_state.value,
                },
            )
            result = _to_result(
                record,
                payment_case,
                reason_code="RECOVERY_ACTION_SUCCEEDED",
                idempotent=False,
            )
            session.commit()
            return result

    def _finalize_provider_problem(
        self,
        claim: _ExecutionClaim,
        status: RecoveryExecutionStatus,
        error_code: str,
        *,
        event_type: str,
    ) -> RecoveryExecutionResult:
        now = self._clock()
        _require_aware(now)
        with self._session_factory() as session:
            payment_case = _lock_case(session, claim.case_id)
            record = _lock_record(session, claim.recovery_action_id)
            if record.execution_status in _FINAL_EXECUTION_STATUSES:
                return _to_result(
                    record,
                    payment_case,
                    reason_code="RECOVERY_ACTION_ALREADY_FINAL",
                    idempotent=True,
                )
            record.execution_status = status
            record.error_code = _bounded_error_code(error_code)
            if status is RecoveryExecutionStatus.FAILED:
                record.failed_at = now
            append_execution_audit(session, record, event_type)
            result = _to_result(
                record,
                payment_case,
                reason_code=record.error_code,
                idempotent=False,
            )
            session.commit()
            return result

    def _finalize_external_success(
        self,
        claim: _ExecutionClaim,
        snapshot: PaymentLinkSnapshot,
        *,
        adopted: bool,
    ) -> _ExternalFinalization:
        now = self._clock()
        _require_aware(now)
        with self._session_factory() as session:
            payment_case = _lock_case(session, claim.case_id)
            record = _lock_record(session, claim.recovery_action_id)
            _persist_external_projection(record, snapshot)

            if not _post_request_context_is_current(
                session,
                payment_case,
                record,
                evaluated_at=now,
            ):
                record.execution_status = (
                    RecoveryExecutionStatus.COMPENSATION_REQUIRED
                )
                record.error_code = (
                    "EXECUTION_BLOCKED_STALE_AUTHORIZATION"
                )
                append_execution_audit(
                    session,
                    record,
                    "EXECUTION_BLOCKED_STALE_AUTHORIZATION",
                )
                result = _to_result(
                    record,
                    payment_case,
                    reason_code=record.error_code,
                    idempotent=False,
                )
                session.commit()
                return _ExternalFinalization(result, True)

            previous_state = payment_case.current_state
            record.execution_status = RecoveryExecutionStatus.SUCCEEDED
            record.executed_at = now
            record.failed_at = None
            record.error_code = None
            payment_case.attempt_count += 1
            if record.action in CUSTOMER_CONTACT_ACTIONS:
                payment_case.contact_attempt_count += 1
            transition_case(
                session,
                payment_case,
                CaseState.ACTIONED,
                reason_code="RECOVERY_ACTION_EXECUTED",
                source=EXECUTION_AUDIT_SOURCE,
                metadata={"recovery_action_id": str(record.id)},
            )
            transition_case(
                session,
                payment_case,
                CaseState.WAITING_FOR_OUTCOME,
                reason_code="AWAITING_RECOVERY_OUTCOME",
                source=EXECUTION_AUDIT_SOURCE,
                metadata={"recovery_action_id": str(record.id)},
            )
            if adopted:
                append_execution_audit(
                    session,
                    record,
                    "RECOVERY_ACTION_ADOPTED_EXISTING",
                )
            append_execution_audit(
                session,
                record,
                "RECOVERY_ACTION_SUCCEEDED",
                metadata={
                    "previous_state": previous_state.value,
                    "new_state": payment_case.current_state.value,
                },
            )
            result = _to_result(
                record,
                payment_case,
                reason_code="RECOVERY_ACTION_SUCCEEDED",
                idempotent=False,
            )
            session.commit()
            return _ExternalFinalization(result, False)

    def _compensate(
        self,
        claim: _ExecutionClaim,
        snapshot: PaymentLinkSnapshot,
        gateway: PaymentLinkGateway,
    ) -> RecoveryExecutionResult:
        try:
            cancelled = gateway.cancel(snapshot.id)
            if cancelled.status != "cancelled":
                raise ExecutionConfigurationError(
                    "Razorpay cancellation was not confirmed"
                )
        except (PaymentLinkError, ExecutionConfigurationError) as error:
            reason_code = getattr(
                error,
                "reason_code",
                "RAZORPAY_PAYMENT_LINK_CANCELLATION_UNCONFIRMED",
            )
            return self._finalize_compensation(
                claim,
                snapshot,
                cancelled=None,
                error_code=reason_code,
            )
        return self._finalize_compensation(
            claim,
            snapshot,
            cancelled=cancelled,
            error_code=None,
        )

    def _finalize_compensation(
        self,
        claim: _ExecutionClaim,
        original: PaymentLinkSnapshot,
        *,
        cancelled: PaymentLinkSnapshot | None,
        error_code: str | None,
    ) -> RecoveryExecutionResult:
        with self._session_factory() as session:
            payment_case = _lock_case(session, claim.case_id)
            record = _lock_record(session, claim.recovery_action_id)
            if cancelled is not None:
                _persist_external_projection(record, cancelled)
                record.execution_status = RecoveryExecutionStatus.CANCELLED
                record.error_code = None
                append_execution_audit(
                    session,
                    record,
                    "RECOVERY_ACTION_COMPENSATED",
                )
                reason = "RECOVERY_ACTION_COMPENSATED"
            else:
                _persist_external_projection(record, original)
                record.execution_status = (
                    RecoveryExecutionStatus.COMPENSATION_REQUIRED
                )
                record.error_code = _bounded_error_code(
                    error_code
                    or "RAZORPAY_PAYMENT_LINK_CANCELLATION_UNCONFIRMED"
                )
                append_execution_audit(
                    session,
                    record,
                    "RECOVERY_ACTION_COMPENSATION_REQUIRED",
                )
                reason = record.error_code
            result = _to_result(
                record,
                payment_case,
                reason_code=reason,
                idempotent=False,
            )
            session.commit()
            return result

    def _gateway_for_request(self) -> tuple[PaymentLinkGateway, bool]:
        if self._payment_link_gateway is not None:
            return self._payment_link_gateway, False
        return RazorpayPaymentLinkClient.from_settings(self._settings), True


def execute_recovery_action(
    case_id: UUID,
    *,
    session_factory: Callable[[], Session],
    payment_link_gateway: PaymentLinkGateway | None = None,
) -> RecoveryExecutionResult:
    """Convenience entry point for one governed recovery execution."""

    return RecoveryExecutionService(
        session_factory=session_factory,
        payment_link_gateway=payment_link_gateway,
    ).execute(case_id)


def _lock_case(session: Session, case_id: UUID) -> PaymentCase:
    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.id == case_id)
        .with_for_update()
    )
    if payment_case is None:
        raise ExecutionCaseNotFoundError("Payment case was not found")
    return payment_case


def _lock_record(session: Session, record_id: UUID) -> RecoveryActionRecord:
    record = session.scalar(
        select(RecoveryActionRecord)
        .where(RecoveryActionRecord.id == record_id)
        .with_for_update()
    )
    if record is None:
        raise ExecutionConfigurationError(
            "Recovery action ledger row was not found"
        )
    return record


def _load_current_proposal(
    session: Session,
    case_id: UUID,
) -> StrategyProposal:
    proposal = session.scalar(
        select(StrategyProposal).where(
            StrategyProposal.case_id == case_id,
            StrategyProposal.superseded_at.is_(None),
        )
    )
    if proposal is None:
        raise ExecutionRequiresPolicyReevaluationError(
            "A current strategy proposal is required"
        )
    return proposal


def _load_current_decision(
    session: Session,
    case_id: UUID,
) -> PolicyDecision:
    decision = session.scalar(
        select(PolicyDecision).where(
            PolicyDecision.case_id == case_id,
            PolicyDecision.superseded_at.is_(None),
        )
    )
    if decision is None:
        raise ExecutionRequiresPolicyReevaluationError(
            "A current policy decision is required"
        )
    return decision


def _load_approval(
    session: Session,
    policy_decision_id: UUID,
) -> ApprovalRequest | None:
    return session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.policy_decision_id == policy_decision_id
        )
    )


def _current_inputs(
    session: Session,
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    decision: PolicyDecision,
    *,
    evaluated_at: datetime,
) -> CurrentAuthorizationInputs:
    if decision.strategy_proposal_id != proposal.id:
        raise ExecutionRequiresPolicyReevaluationError(
            "Current policy decision does not reference current strategy"
        )
    try:
        inputs = recompute_current_authorization_inputs(
            session,
            payment_case,
            proposal,
            evaluated_at=evaluated_at,
            lock_policy=True,
        )
    except CurrentAuthorizationError as error:
        raise ExecutionRequiresPolicyReevaluationError(str(error)) from error
    if (
        decision.strategy_input_fingerprint
        != proposal.strategy_input_fingerprint
        or decision.policy_fingerprint != inputs.policy_fingerprint
        or decision.authorization_input_fingerprint
        != inputs.authorization_input_fingerprint
        or decision.result is not inputs.evaluation.result
        or decision.reason_code != inputs.evaluation.reason_code
        or decision.recovery_window_ends_at
        != inputs.evaluation.recovery_window_ends_at
        or decision.observed_amount_minor != payment_case.amount
        or decision.observed_attempt_count != payment_case.attempt_count
        or decision.observed_contact_attempt_count
        != payment_case.contact_attempt_count
    ):
        raise ExecutionRequiresPolicyReevaluationError(
            "Current deterministic authorization inputs have changed"
        )
    if (
        decision.result is PolicyDecisionResult.BLOCKED
        or inputs.evaluation.recovery_window_expired is True
    ):
        raise ExecutionRequiresPolicyReevaluationError(
            "Current policy decision no longer permits execution"
        )
    return inputs


def _build_record(
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    decision: PolicyDecision,
    approval: ApprovalRequest | None,
    inputs: CurrentAuthorizationInputs,
    *,
    now: datetime,
) -> RecoveryActionRecord:
    record_id = uuid4()
    idempotency_key = build_execution_idempotency_key(
        policy_decision_id=decision.id,
        authorization_input_fingerprint=(
            inputs.authorization_input_fingerprint
        ),
        strategy_proposal_id=proposal.id,
        action=proposal.action,
    )
    if proposal.action is RecoveryAction.CREATE_RECOVERY_LINK:
        if payment_case.amount is None or payment_case.amount <= 0:
            raise ExecutionRequiresPolicyReevaluationError(
                "A positive amount is required for Payment Link execution"
            )
        currency = payment_case.currency
        if currency is None or len(currency.strip()) != 3:
            raise ExecutionRequiresPolicyReevaluationError(
                "A three-letter currency is required for Payment Link execution"
            )
        window_end = decision.recovery_window_ends_at
        if window_end is None or window_end <= now:
            raise ExecutionRequiresPolicyReevaluationError(
                "Authorized recovery window has expired"
            )
        expires_at = min(
            window_end,
            now + timedelta(seconds=PAYMENT_LINK_OPERATIONAL_EXPIRY_SECONDS),
        )
        expire_by = int(expires_at.timestamp())
        if expire_by <= int(now.timestamp()):
            raise ExecutionRequiresPolicyReevaluationError(
                "Payment Link expiry is no longer executable"
            )
        reference_id = f"arc_{record_id.hex}"
        request_fingerprint = build_payment_link_request_fingerprint(
            action=proposal.action,
            amount_minor=payment_case.amount,
            currency=currency,
            reference_id=reference_id,
            expire_by=expire_by,
        )
        provider = "RAZORPAY"
    else:
        expires_at = None
        reference_id = None
        request_fingerprint = build_internal_request_fingerprint(
            action=proposal.action,
            policy_decision_id=decision.id,
            re_evaluate_after_seconds=proposal.re_evaluate_after_seconds,
        )
        provider = "INTERNAL"

    return RecoveryActionRecord(
        id=record_id,
        case_id=payment_case.id,
        strategy_proposal_id=proposal.id,
        policy_decision_id=decision.id,
        approval_request_id=(approval.id if approval is not None else None),
        action=proposal.action,
        execution_status=RecoveryExecutionStatus.PREPARED,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        provider=provider,
        external_reference=reference_id,
        external_expires_at=expires_at,
    )


def _validate_existing_record(
    record: RecoveryActionRecord,
    payment_case: PaymentCase,
    proposal: StrategyProposal,
    decision: PolicyDecision,
) -> None:
    expected_idempotency = build_execution_idempotency_key(
        policy_decision_id=decision.id,
        authorization_input_fingerprint=(
            decision.authorization_input_fingerprint
        ),
        strategy_proposal_id=proposal.id,
        action=proposal.action,
    )
    if (
        record.case_id != payment_case.id
        or record.strategy_proposal_id != proposal.id
        or record.action is not proposal.action
        or record.idempotency_key != expected_idempotency
    ):
        raise ExecutionRequiresPolicyReevaluationError(
            "Existing recovery action does not match current authorization"
        )
    if record.action is RecoveryAction.CREATE_RECOVERY_LINK:
        if (
            payment_case.amount is None
            or payment_case.currency is None
            or record.external_reference is None
            or record.external_expires_at is None
        ):
            raise ExecutionConfigurationError(
                "Payment Link execution intent is incomplete"
            )
        expected_request = build_payment_link_request_fingerprint(
            action=record.action,
            amount_minor=payment_case.amount,
            currency=payment_case.currency,
            reference_id=record.external_reference,
            expire_by=int(record.external_expires_at.timestamp()),
        )
    else:
        expected_request = build_internal_request_fingerprint(
            action=record.action,
            policy_decision_id=decision.id,
            re_evaluate_after_seconds=proposal.re_evaluate_after_seconds,
        )
    if record.request_fingerprint != expected_request:
        raise ExecutionRequiresPolicyReevaluationError(
            "Existing recovery request fingerprint is inconsistent"
        )


def _has_fresh_lease(record: RecoveryActionRecord, now: datetime) -> bool:
    if record.execution_status is not RecoveryExecutionStatus.IN_PROGRESS:
        return False
    started_at = record.execution_started_at
    return (
        started_at is not None
        and started_at > now - timedelta(seconds=EXECUTION_LEASE_SECONDS)
    )


def _to_claim(
    record: RecoveryActionRecord,
    payment_case: PaymentCase,
) -> _ExecutionClaim:
    return _ExecutionClaim(
        recovery_action_id=record.id,
        case_id=record.case_id,
        action=record.action,
        amount_minor=payment_case.amount,
        currency=payment_case.currency,
        reference_id=record.external_reference,
        expire_by=(
            int(record.external_expires_at.timestamp())
            if record.external_expires_at is not None
            else None
        ),
    )


def _payment_link_request(
    claim: _ExecutionClaim,
) -> PaymentLinkCreateRequest:
    if (
        claim.amount_minor is None
        or claim.currency is None
        or claim.reference_id is None
        or claim.expire_by is None
    ):
        raise ExecutionConfigurationError(
            "Payment Link execution claim is incomplete"
        )
    return PaymentLinkCreateRequest(
        amount=claim.amount_minor,
        currency=claim.currency.strip().upper(),
        reference_id=claim.reference_id,
        expire_by=claim.expire_by,
    )


def _matches_request(
    snapshot: PaymentLinkSnapshot,
    request: PaymentLinkCreateRequest,
) -> bool:
    return (
        snapshot.reference_id == request.reference_id
        and snapshot.amount == request.amount
        and snapshot.currency == request.currency
    )


def _post_request_context_is_current(
    session: Session,
    payment_case: PaymentCase,
    record: RecoveryActionRecord,
    *,
    evaluated_at: datetime,
) -> bool:
    if payment_case.current_state is not CaseState.POLICY_VALIDATED:
        return False
    proposal = session.get(StrategyProposal, record.strategy_proposal_id)
    decision = session.get(PolicyDecision, record.policy_decision_id)
    if (
        proposal is None
        or decision is None
        or proposal.superseded_at is not None
        or decision.superseded_at is not None
    ):
        return False
    try:
        _current_inputs(
            session,
            payment_case,
            proposal,
            decision,
            evaluated_at=evaluated_at,
        )
    except ExecutionRequiresPolicyReevaluationError:
        return False
    approval = _load_approval(session, decision.id)
    return is_execution_permitted(decision, approval)


def _persist_external_projection(
    record: RecoveryActionRecord,
    snapshot: PaymentLinkSnapshot,
) -> None:
    record.external_reference_id = snapshot.id
    record.external_reference = snapshot.reference_id
    record.external_status = snapshot.status
    record.external_url = str(snapshot.short_url)


def _bounded_error_code(value: str) -> str:
    normalized = value.strip().upper() if isinstance(value, str) else ""
    if not normalized or len(normalized) > 100:
        return "RECOVERY_EXECUTION_FAILED"
    return normalized


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionConfigurationError(
            "Recovery execution clock must be timezone-aware"
        )


def _to_result(
    record: RecoveryActionRecord,
    payment_case: PaymentCase,
    *,
    reason_code: str,
    idempotent: bool,
) -> RecoveryExecutionResult:
    return RecoveryExecutionResult(
        recovery_action_id=record.id,
        case_id=record.case_id,
        policy_decision_id=record.policy_decision_id,
        action=record.action,
        execution_status=record.execution_status,
        case_state=payment_case.current_state,
        reason_code=reason_code,
        execution_attempt_count=record.execution_attempt_count,
        external_reference_id=record.external_reference_id,
        external_reference=record.external_reference,
        external_status=record.external_status,
        external_url=record.external_url,
        idempotent=idempotent,
    )
