"""Deterministic read models for recovery outcomes, attribution, and metrics."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arc.domain.enums import (
    CaseState,
    ProviderMode,
    RecoveryExecutionStatus,
    RecoveryOutcomeStatus,
)
from arc.domain.models import (
    PaymentCase,
    RecoveryActionRecord,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
)


@dataclass(frozen=True, slots=True)
class RecoveredAmountSummary:
    provider_mode: ProviderMode
    currency: str
    recovered_cases: int
    recovered_amount_minor: int


@dataclass(frozen=True, slots=True)
class RecoveryMetrics:
    """Currency- and mode-scoped metrics derived only from persisted rows."""

    provider_mode: ProviderMode
    currency: str
    cases_evaluated: int
    revenue_at_risk_minor: int
    recovery_actions_succeeded: int
    recovered_cases: int
    recovered_revenue_minor: int
    recovery_rate_by_cases: float
    recovery_rate_by_amount: float
    awaiting_outcome: int
    requires_attention: int


def get_current_outcome_for_case(
    session: Session,
    case_id: UUID,
) -> RecoveryOutcomeObservation | None:
    return session.scalar(
        select(RecoveryOutcomeObservation)
        .where(RecoveryOutcomeObservation.case_id == case_id)
        .order_by(
            RecoveryOutcomeObservation.observed_at.desc(),
            RecoveryOutcomeObservation.created_at.desc(),
        )
        .limit(1)
    )


def get_attribution_for_case(
    session: Session,
    case_id: UUID,
) -> RecoveryAttribution | None:
    return session.scalar(
        select(RecoveryAttribution).where(
            RecoveryAttribution.case_id == case_id
        )
    )


def list_recovered_cases(
    session: Session,
    *,
    provider_mode: ProviderMode,
    currency: str | None = None,
) -> list[PaymentCase]:
    statement = (
        select(PaymentCase)
        .join(
            RecoveryAttribution,
            RecoveryAttribution.case_id == PaymentCase.id,
        )
        .where(RecoveryAttribution.provider_mode == provider_mode)
        .order_by(RecoveryAttribution.attributed_at.desc())
    )
    if currency is not None:
        statement = statement.where(
            RecoveryAttribution.currency == _currency(currency)
        )
    return list(session.scalars(statement).unique())


def list_waiting_for_outcome_cases(session: Session) -> list[PaymentCase]:
    return list(
        session.scalars(
            select(PaymentCase)
            .where(PaymentCase.current_state == CaseState.WAITING_FOR_OUTCOME)
            .order_by(PaymentCase.updated_at)
        )
    )


def summarize_recovered_amount(
    session: Session,
    *,
    provider_mode: ProviderMode | None = None,
) -> list[RecoveredAmountSummary]:
    statement = select(
        RecoveryAttribution.provider_mode,
        RecoveryAttribution.currency,
        func.count(RecoveryAttribution.case_id),
        func.coalesce(func.sum(RecoveryAttribution.recovered_amount_minor), 0),
    ).group_by(
        RecoveryAttribution.provider_mode,
        RecoveryAttribution.currency,
    )
    if provider_mode is not None:
        statement = statement.where(
            RecoveryAttribution.provider_mode == provider_mode
        )
    return [
        RecoveredAmountSummary(
            provider_mode=mode,
            currency=currency,
            recovered_cases=count,
            recovered_amount_minor=amount,
        )
        for mode, currency, count, amount in session.execute(statement)
    ]


def calculate_recovery_metrics(
    session: Session,
    *,
    provider_mode: ProviderMode,
    currency: str,
) -> RecoveryMetrics:
    """Calculate only evidence-backed metrics without mixing modes/currencies."""

    normalized_currency = _currency(currency)
    observations = list(
        session.scalars(
            select(RecoveryOutcomeObservation).where(
                RecoveryOutcomeObservation.provider_mode == provider_mode,
                RecoveryOutcomeObservation.currency == normalized_currency,
            )
        )
    )
    latest_by_action: dict[UUID, RecoveryOutcomeObservation] = {}
    for observation in observations:
        previous = latest_by_action.get(observation.recovery_action_id)
        if previous is None or (
            observation.observed_at,
            observation.created_at,
        ) > (previous.observed_at, previous.created_at):
            latest_by_action[observation.recovery_action_id] = observation

    case_ids = {observation.case_id for observation in observations}
    cases = {
        payment_case.id: payment_case
        for payment_case in session.scalars(
            select(PaymentCase).where(PaymentCase.id.in_(case_ids))
        )
    } if case_ids else {}
    action_ids = set(latest_by_action)
    actions = list(
        session.scalars(
            select(RecoveryActionRecord).where(
                RecoveryActionRecord.id.in_(action_ids)
            )
        )
    ) if action_ids else []
    attributions = list(
        session.scalars(
            select(RecoveryAttribution).where(
                RecoveryAttribution.provider_mode == provider_mode,
                RecoveryAttribution.currency == normalized_currency,
            )
        )
    )

    cases_evaluated = len(cases)
    revenue_at_risk = sum(
        payment_case.amount or 0
        for payment_case in cases.values()
        if payment_case.currency == normalized_currency
    )
    recovered_case_ids = {item.case_id for item in attributions}
    recovered_revenue = sum(
        item.recovered_amount_minor for item in attributions
    )
    awaiting = sum(
        payment_case.current_state is CaseState.WAITING_FOR_OUTCOME
        for payment_case in cases.values()
    )
    requires_attention = len(
        {
            observation.case_id
            for observation in latest_by_action.values()
            if observation.outcome_status
            is RecoveryOutcomeStatus.REVIEW_REQUIRED
            or cases.get(observation.case_id) is not None
            and cases[observation.case_id].current_state is CaseState.ESCALATED
        }
    )
    succeeded = sum(
        action.execution_status is RecoveryExecutionStatus.SUCCEEDED
        for action in actions
    )
    return RecoveryMetrics(
        provider_mode=provider_mode,
        currency=normalized_currency,
        cases_evaluated=cases_evaluated,
        revenue_at_risk_minor=revenue_at_risk,
        recovery_actions_succeeded=succeeded,
        recovered_cases=len(recovered_case_ids),
        recovered_revenue_minor=recovered_revenue,
        recovery_rate_by_cases=(
            len(recovered_case_ids) / cases_evaluated
            if cases_evaluated
            else 0.0
        ),
        recovery_rate_by_amount=(
            recovered_revenue / revenue_at_risk if revenue_at_risk else 0.0
        ),
        awaiting_outcome=awaiting,
        requires_attention=requires_attention,
    )


def _currency(value: str) -> str:
    normalized = value.strip().upper() if isinstance(value, str) else ""
    if len(normalized) != 3:
        raise ValueError("Currency must be a three-letter code")
    return normalized
