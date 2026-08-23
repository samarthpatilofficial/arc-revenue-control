"""Two-transaction authoritative outcome observation and strict attribution."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arc.config import Settings, get_settings
from arc.domain.enums import (
    CaseState,
    OutcomeObservationSource,
    ProviderMode,
    RecoveryAction,
    RecoveryExecutionStatus,
    RecoveryOutcomeStatus,
)
from arc.domain.models import (
    PaymentCase,
    RecoveryActionRecord,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
)
from arc.integrations.razorpay.payment_links import (
    PaymentLinkError,
    PaymentLinkGateway,
    PaymentLinkSnapshot,
    RazorpayPaymentLinkClient,
    derive_razorpay_provider_mode,
)
from arc.outcomes.audit import OUTCOME_AUDIT_SOURCE, append_outcome_audit
from arc.outcomes.classification import (
    ExpectedPaymentLinkEvidence,
    OutcomeClassification,
    classify_payment_link_outcome,
)
from arc.outcomes.errors import (
    RecoveryObservationConfigurationError,
    RecoveryObservationNotFoundError,
    RecoveryObservationProviderError,
)
from arc.outcomes.fingerprint import build_outcome_evidence_fingerprint
from arc.reconciliation.state_machine import transition_case

ATTRIBUTION_REASON_CODE = "ARC_PAYMENT_LINK_CAPTURED"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeResult:
    """Sanitized projection returned by poll and webhook-triggered observation."""

    recovery_action_id: UUID
    case_id: UUID
    observation_id: UUID
    attribution_id: UUID | None
    provider_mode: ProviderMode
    provider_status: str
    outcome_status: RecoveryOutcomeStatus
    case_state: CaseState
    reason_code: str
    recovered_amount_minor: int | None
    currency: str
    idempotent: bool


class RecoveryOutcomeObserver(Protocol):
    """Narrow dependency used by webhook processing."""

    def observe_recovery_action(
        self,
        recovery_action_id: UUID,
        *,
        source: OutcomeObservationSource = OutcomeObservationSource.POLL,
    ) -> RecoveryOutcomeResult: ...


@dataclass(frozen=True, slots=True)
class _ObservationClaim:
    expected: ExpectedPaymentLinkEvidence
    case_id: UUID
    provider_mode: ProviderMode


class RecoveryOutcomeService:
    """Observe provider truth without holding database locks during HTTP."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        payment_link_gateway: PaymentLinkGateway | None = None,
        settings: Settings | None = None,
        provider_mode: ProviderMode | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._payment_link_gateway = payment_link_gateway
        self._settings = settings or get_settings()
        self._provider_mode = provider_mode
        self._clock = clock

    def observe_recovery_action(
        self,
        recovery_action_id: UUID,
        *,
        source: OutcomeObservationSource = OutcomeObservationSource.POLL,
    ) -> RecoveryOutcomeResult:
        """Read and persist one authoritative Payment Link outcome."""

        claim = self._prepare_claim(recovery_action_id)
        gateway, owned = self._gateway_for_request()
        try:
            try:
                snapshot = gateway.fetch_by_id(
                    claim.expected.payment_link_id
                )
            except PaymentLinkError as error:
                raise RecoveryObservationProviderError(str(error)) from None
        finally:
            if owned:
                close = getattr(gateway, "close", None)
                if callable(close):
                    close()
        return self._persist_observation(claim, snapshot, source=source)

    def _prepare_claim(self, recovery_action_id: UUID) -> _ObservationClaim:
        provider_mode = self._resolved_provider_mode()
        with self._session_factory() as session:
            action, payment_case = _lock_action_and_case(
                session, recovery_action_id
            )
            expected = _validate_observable(action, payment_case)
            claim = _ObservationClaim(
                expected=expected,
                case_id=payment_case.id,
                provider_mode=provider_mode,
            )
            session.commit()
            return claim

    def _persist_observation(
        self,
        claim: _ObservationClaim,
        snapshot: PaymentLinkSnapshot,
        *,
        source: OutcomeObservationSource,
    ) -> RecoveryOutcomeResult:
        observed_at = self._clock()
        _require_aware(observed_at)
        fingerprint = build_outcome_evidence_fingerprint(
            claim.expected.recovery_action_id, snapshot
        )
        with self._session_factory() as session:
            action, payment_case = _lock_action_and_case(
                session, claim.expected.recovery_action_id
            )
            current = _validate_observable(action, payment_case)
            if current != claim.expected or payment_case.id != claim.case_id:
                raise RecoveryObservationConfigurationError(
                    "Recovery action context changed during provider read"
                )

            existing = session.scalar(
                select(RecoveryOutcomeObservation).where(
                    RecoveryOutcomeObservation.recovery_action_id == action.id,
                    RecoveryOutcomeObservation.evidence_fingerprint
                    == fingerprint,
                )
            )
            if existing is not None:
                attribution = _attribution_for_action(session, action.id)
                result = _to_result(
                    existing,
                    attribution,
                    payment_case,
                    reason_code="RECOVERY_OUTCOME_ALREADY_OBSERVED",
                    idempotent=True,
                )
                session.commit()
                return result

            classification = classify_payment_link_outcome(current, snapshot)
            existing_attribution = _attribution_for_action(session, action.id)
            classification = _protect_existing_case_and_attribution(
                session,
                payment_case,
                action,
                classification,
                existing_attribution,
            )
            observation = RecoveryOutcomeObservation(
                case_id=payment_case.id,
                recovery_action_id=action.id,
                source=source,
                provider="RAZORPAY",
                provider_mode=claim.provider_mode,
                provider_status=snapshot.status,
                outcome_status=classification.outcome_status,
                amount_expected_minor=current.amount_minor,
                amount_paid_minor=snapshot.amount_paid,
                currency=current.currency,
                provider_payment_id=classification.provider_payment_id,
                provider_payment_status=classification.provider_payment_status,
                evidence_fingerprint=fingerprint,
                observed_at=observed_at,
            )
            session.add(observation)
            session.flush()
            action.external_status = snapshot.status

            attribution = existing_attribution
            if (
                classification.outcome_status
                is RecoveryOutcomeStatus.RECOVERED
                and attribution is None
            ):
                attribution = RecoveryAttribution(
                    case_id=payment_case.id,
                    recovery_action_id=action.id,
                    outcome_observation_id=observation.id,
                    provider="RAZORPAY",
                    provider_mode=claim.provider_mode,
                    provider_payment_link_id=snapshot.id,
                    provider_reference_id=snapshot.reference_id,
                    provider_payment_id=(
                        classification.provider_payment_id or ""
                    ),
                    recovered_amount_minor=current.amount_minor,
                    currency=current.currency,
                    attribution_reason_code=ATTRIBUTION_REASON_CODE,
                    evidence_fingerprint=fingerprint,
                    attributed_at=observed_at,
                )
                try:
                    with session.begin_nested():
                        session.add(attribution)
                        session.flush()
                except IntegrityError:
                    attribution = None
                    classification = replace(
                        classification,
                        outcome_status=RecoveryOutcomeStatus.REVIEW_REQUIRED,
                        reason_code="RECOVERY_ATTRIBUTION_UNIQUENESS_CONFLICT",
                    )
                    observation.outcome_status = classification.outcome_status

            _apply_outcome_transition(
                session,
                payment_case,
                observation,
                classification,
                attribution,
                observed_at=observed_at,
            )
            result = _to_result(
                observation,
                attribution,
                payment_case,
                reason_code=classification.reason_code,
                idempotent=False,
            )
            session.commit()
            return result

    def _resolved_provider_mode(self) -> ProviderMode:
        if self._provider_mode is not None:
            return self._provider_mode
        try:
            return derive_razorpay_provider_mode(self._settings)
        except PaymentLinkError as error:
            raise RecoveryObservationConfigurationError(str(error)) from None

    def _gateway_for_request(self) -> tuple[PaymentLinkGateway, bool]:
        if self._payment_link_gateway is not None:
            return self._payment_link_gateway, False
        try:
            return RazorpayPaymentLinkClient.from_settings(self._settings), True
        except PaymentLinkError as error:
            raise RecoveryObservationConfigurationError(str(error)) from None


def observe_recovery_action(
    recovery_action_id: UUID,
    *,
    session_factory: Callable[[], Session],
    source: OutcomeObservationSource = OutcomeObservationSource.POLL,
    payment_link_gateway: PaymentLinkGateway | None = None,
) -> RecoveryOutcomeResult:
    """Convenience entry point for authoritative outcome observation."""

    return RecoveryOutcomeService(
        session_factory=session_factory,
        payment_link_gateway=payment_link_gateway,
    ).observe_recovery_action(recovery_action_id, source=source)


def _lock_action_and_case(
    session: Session,
    recovery_action_id: UUID,
) -> tuple[RecoveryActionRecord, PaymentCase]:
    case_id = session.scalar(
        select(RecoveryActionRecord.case_id).where(
            RecoveryActionRecord.id == recovery_action_id
        )
    )
    if case_id is None:
        raise RecoveryObservationNotFoundError("Recovery action was not found")
    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.id == case_id)
        .with_for_update()
    )
    action = session.scalar(
        select(RecoveryActionRecord)
        .where(RecoveryActionRecord.id == recovery_action_id)
        .with_for_update()
    )
    if payment_case is None or action is None or action.case_id != payment_case.id:
        raise RecoveryObservationNotFoundError(
            "Recovery action context was not found"
        )
    return action, payment_case


def _validate_observable(
    action: RecoveryActionRecord,
    payment_case: PaymentCase,
) -> ExpectedPaymentLinkEvidence:
    if (
        action.action is not RecoveryAction.CREATE_RECOVERY_LINK
        or action.execution_status is not RecoveryExecutionStatus.SUCCEEDED
        or action.provider != "RAZORPAY"
    ):
        raise RecoveryObservationConfigurationError(
            "Recovery action does not support outcome observation"
        )
    if action.external_reference_id is None or action.external_reference is None:
        raise RecoveryObservationConfigurationError(
            "Recovery action is missing provider identifiers"
        )
    if payment_case.amount is None or payment_case.amount <= 0:
        raise RecoveryObservationConfigurationError(
            "Recovery case has no positive expected amount"
        )
    currency = (payment_case.currency or "").strip().upper()
    if len(currency) != 3:
        raise RecoveryObservationConfigurationError(
            "Recovery case has no valid currency"
        )
    if payment_case.current_state not in {
        CaseState.WAITING_FOR_OUTCOME,
        CaseState.RECOVERED,
        CaseState.EXHAUSTED,
        CaseState.ESCALATED,
    }:
        raise RecoveryObservationConfigurationError(
            "Recovery case is not observable in its current state"
        )
    return ExpectedPaymentLinkEvidence(
        recovery_action_id=action.id,
        payment_link_id=action.external_reference_id,
        reference_id=action.external_reference,
        amount_minor=payment_case.amount,
        currency=currency,
    )


def _protect_existing_case_and_attribution(
    session: Session,
    payment_case: PaymentCase,
    action: RecoveryActionRecord,
    classification: OutcomeClassification,
    existing_attribution: RecoveryAttribution | None,
) -> OutcomeClassification:
    if classification.outcome_status is not RecoveryOutcomeStatus.RECOVERED:
        return classification
    payment_id = classification.provider_payment_id
    if payment_id is None:
        return replace(
            classification,
            outcome_status=RecoveryOutcomeStatus.REVIEW_REQUIRED,
            reason_code="RECOVERY_OUTCOME_CAPTURE_MISSING",
        )
    attributed_payment = session.scalar(
        select(RecoveryAttribution).where(
            RecoveryAttribution.provider_payment_id == payment_id
        )
    )
    if attributed_payment is not None and attributed_payment.recovery_action_id != action.id:
        return replace(
            classification,
            outcome_status=RecoveryOutcomeStatus.REVIEW_REQUIRED,
            reason_code="RECOVERY_ATTRIBUTION_PAYMENT_ALREADY_COUNTED",
        )
    if existing_attribution is not None:
        if existing_attribution.provider_payment_id == payment_id:
            return classification
        return replace(
            classification,
            outcome_status=RecoveryOutcomeStatus.REVIEW_REQUIRED,
            reason_code="RECOVERY_ATTRIBUTION_ACTION_ALREADY_COUNTED",
        )
    if payment_case.current_state is CaseState.RECOVERED:
        return replace(
            classification,
            outcome_status=RecoveryOutcomeStatus.REVIEW_REQUIRED,
            reason_code="RECOVERY_ATTRIBUTION_CASE_ALREADY_RECOVERED",
        )
    return classification


def _apply_outcome_transition(
    session: Session,
    payment_case: PaymentCase,
    observation: RecoveryOutcomeObservation,
    classification: OutcomeClassification,
    attribution: RecoveryAttribution | None,
    *,
    observed_at: datetime,
) -> None:
    append_outcome_audit(
        session,
        observation,
        "RECOVERY_OUTCOME_OBSERVED",
        reason_code=classification.reason_code,
        attribution=attribution,
    )
    event_type = f"RECOVERY_OUTCOME_{classification.outcome_status.value}"
    append_outcome_audit(
        session,
        observation,
        event_type,
        reason_code=classification.reason_code,
        attribution=attribution,
    )
    if classification.outcome_status is RecoveryOutcomeStatus.PENDING:
        return

    if classification.outcome_status is RecoveryOutcomeStatus.RECOVERED:
        if attribution is None:
            raise RecoveryObservationConfigurationError(
                "Recovered outcome has no durable attribution"
            )
        append_outcome_audit(
            session,
            observation,
            "RECOVERY_ATTRIBUTED",
            reason_code=ATTRIBUTION_REASON_CODE,
            attribution=attribution,
        )
        if payment_case.current_state is CaseState.WAITING_FOR_OUTCOME:
            transition_case(
                session,
                payment_case,
                CaseState.RECOVERED,
                reason_code="RECOVERY_PAYMENT_CAPTURED",
                source=OUTCOME_AUDIT_SOURCE,
                metadata={
                    "recovery_action_id": str(observation.recovery_action_id),
                    "outcome_observation_id": str(observation.id),
                    "attribution_id": str(attribution.id),
                },
            )
            payment_case.resolved_at = observed_at
        return

    if classification.outcome_status in {
        RecoveryOutcomeStatus.EXPIRED,
        RecoveryOutcomeStatus.CANCELLED,
    }:
        if payment_case.current_state is CaseState.WAITING_FOR_OUTCOME:
            transition_case(
                session,
                payment_case,
                CaseState.EXHAUSTED,
                reason_code=classification.reason_code,
                source=OUTCOME_AUDIT_SOURCE,
                metadata={
                    "recovery_action_id": str(observation.recovery_action_id),
                    "outcome_observation_id": str(observation.id),
                },
            )
            payment_case.resolved_at = observed_at
        return

    append_outcome_audit(
        session,
        observation,
        "RECOVERY_ATTRIBUTION_CONFLICT",
        reason_code=classification.reason_code,
    )
    if payment_case.current_state is CaseState.WAITING_FOR_OUTCOME:
        transition_case(
            session,
            payment_case,
            CaseState.ESCALATED,
            reason_code=classification.reason_code,
            source=OUTCOME_AUDIT_SOURCE,
            metadata={
                "recovery_action_id": str(observation.recovery_action_id),
                "outcome_observation_id": str(observation.id),
            },
        )
        payment_case.resolved_at = observed_at


def _attribution_for_action(
    session: Session,
    recovery_action_id: UUID,
) -> RecoveryAttribution | None:
    return session.scalar(
        select(RecoveryAttribution).where(
            RecoveryAttribution.recovery_action_id == recovery_action_id
        )
    )


def _to_result(
    observation: RecoveryOutcomeObservation,
    attribution: RecoveryAttribution | None,
    payment_case: PaymentCase,
    *,
    reason_code: str,
    idempotent: bool,
) -> RecoveryOutcomeResult:
    return RecoveryOutcomeResult(
        recovery_action_id=observation.recovery_action_id,
        case_id=observation.case_id,
        observation_id=observation.id,
        attribution_id=attribution.id if attribution is not None else None,
        provider_mode=observation.provider_mode,
        provider_status=observation.provider_status,
        outcome_status=observation.outcome_status,
        case_state=payment_case.current_state,
        reason_code=reason_code,
        recovered_amount_minor=(
            attribution.recovered_amount_minor
            if attribution is not None
            else None
        ),
        currency=observation.currency,
        idempotent=idempotent,
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecoveryObservationConfigurationError(
            "Recovery observation clock must be timezone-aware"
        )
