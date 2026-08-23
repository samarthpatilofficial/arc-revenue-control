"""Two-transaction bounded strategy generation with stale-context fencing."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arc.config import Settings, get_settings
from arc.domain.enums import (
    CaseState,
    RecoveryAction,
    StrategySource,
)
from arc.domain.models import PaymentCase, StrategyProposal
from arc.integrations.openai import OpenAIResponsesClient
from arc.intelligence.audit import (
    STRATEGY_AUDIT_SOURCE,
    append_generated,
    append_generation_failure,
    append_rejected,
    append_stale_context,
)
from arc.intelligence.compatibility import (
    RuleStrategy,
    ai_reason_code,
    rule_strategy_for,
    validate_action_compatibility,
)
from arc.intelligence.errors import (
    StrategyConfigurationError,
    StrategyError,
    StrategyNotAllowedError,
    StrategyStaleContextError,
    StrategyUnavailableError,
)
from arc.intelligence.context import (
    required_assessment_fingerprint,
    validate_strategy_context,
)
from arc.intelligence.fingerprint import build_strategy_input_fingerprint
from arc.intelligence.prompt import STRATEGY_PROMPT_VERSION
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelClient,
    StrategyModelResult,
)
from arc.reconciliation.state_machine import transition_case


class StrategyCaseNotFoundError(LookupError):
    """Raised when the requested payment case does not exist."""


@dataclass(frozen=True, slots=True)
class StrategyGenerationResult:
    """Sanitized current proposal projection returned by the service."""

    proposal_id: UUID
    case_id: UUID
    case_state: CaseState
    source: StrategySource
    action: RecoveryAction
    reason_code: str
    explanation: str
    confidence: float | None
    re_evaluate_after_seconds: int | None
    assessment_fingerprint: str
    strategy_input_fingerprint: str
    idempotent: bool


@dataclass(frozen=True, slots=True)
class _StrategySnapshot:
    case_id: UUID
    assessment_fingerprint: str
    context: StrategyContext
    strategy_input_fingerprint: str
    configured_model: str | None
    rule_strategy: RuleStrategy | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class StrategyService:
    """Generate one bounded proposal without holding a lock during inference."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        model_client: StrategyModelClient | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._model_client = model_client
        self._settings = settings or get_settings()
        self._clock = clock

    def generate_strategy(self, case_id: UUID) -> StrategyGenerationResult:
        """Return an idempotent current proposal or safely generate one."""

        prepared = self._prepare_snapshot(case_id)
        if isinstance(prepared, StrategyGenerationResult):
            return prepared
        snapshot = prepared

        if snapshot.rule_strategy is not None:
            return self._persist_if_current(snapshot, model_result=None)

        try:
            model_result = self._model_client_for_request().propose(
                snapshot.context
            )
        except StrategyError as error:
            self._record_generation_failure(snapshot, error.reason_code)
            raise
        except Exception as error:
            safe_error = StrategyUnavailableError(
                "Strategy provider failed safely"
            )
            self._record_generation_failure(
                snapshot,
                safe_error.reason_code,
            )
            raise safe_error from error

        return self._persist_if_current(snapshot, model_result=model_result)

    def _prepare_snapshot(
        self,
        case_id: UUID,
    ) -> _StrategySnapshot | StrategyGenerationResult:
        with self._session_factory() as session:
            payment_case = _lock_case(session, case_id)
            context = validate_strategy_context(
                payment_case,
                clock=self._clock,
            )
            rule_strategy = rule_strategy_for(context.recovery_disposition)
            configured_model = (
                None if rule_strategy is not None else self._configured_model()
            )
            assessment_fingerprint = required_assessment_fingerprint(
                payment_case
            )
            input_fingerprint = build_strategy_input_fingerprint(
                assessment_fingerprint=assessment_fingerprint,
                context=context,
                model=configured_model,
            )
            existing = _find_identical_proposal(
                session,
                case_id,
                input_fingerprint,
            )
            if existing is not None:
                result = _to_result(
                    existing,
                    payment_case.current_state,
                    idempotent=True,
                )
                session.commit()
                return result

            _validate_generation_state(session, payment_case)
            snapshot = _StrategySnapshot(
                case_id=case_id,
                assessment_fingerprint=assessment_fingerprint,
                context=context,
                strategy_input_fingerprint=input_fingerprint,
                configured_model=configured_model,
                rule_strategy=rule_strategy,
            )
            session.commit()
            return snapshot

    def _persist_if_current(
        self,
        snapshot: _StrategySnapshot,
        *,
        model_result: StrategyModelResult | None,
    ) -> StrategyGenerationResult:
        try:
            return self._persist_locked(snapshot, model_result=model_result)
        except IntegrityError as error:
            with self._session_factory() as session:
                existing = _find_identical_proposal(
                    session,
                    snapshot.case_id,
                    snapshot.strategy_input_fingerprint,
                )
                if existing is not None:
                    payment_case = session.get(PaymentCase, snapshot.case_id)
                    if payment_case is None:
                        raise StrategyCaseNotFoundError(
                            "Payment case was not found"
                        ) from error
                    return _to_result(
                        existing,
                        payment_case.current_state,
                        idempotent=True,
                    )
            raise StrategyNotAllowedError(
                "Strategy proposal could not be persisted safely"
            ) from error

    def _persist_locked(
        self,
        snapshot: _StrategySnapshot,
        *,
        model_result: StrategyModelResult | None,
    ) -> StrategyGenerationResult:
        with self._session_factory() as session:
            payment_case = _lock_case(session, snapshot.case_id)
            try:
                current_context = validate_strategy_context(
                    payment_case,
                    clock=self._clock,
                )
                current_assessment = required_assessment_fingerprint(
                    payment_case
                )
                current_fingerprint = build_strategy_input_fingerprint(
                    assessment_fingerprint=current_assessment,
                    context=current_context,
                    model=snapshot.configured_model,
                )
            except StrategyError:
                _audit_stale_context(
                    session, payment_case, snapshot, model_result
                )
                session.commit()
                raise StrategyStaleContextError(
                    "Strategy proposal was discarded because case truth changed"
                )

            if (
                current_assessment != snapshot.assessment_fingerprint
                or current_context != snapshot.context
                or current_fingerprint
                != snapshot.strategy_input_fingerprint
            ):
                _audit_stale_context(
                    session, payment_case, snapshot, model_result
                )
                session.commit()
                raise StrategyStaleContextError(
                    "Strategy proposal was discarded because case truth changed"
                )

            existing = _find_identical_proposal(
                session,
                snapshot.case_id,
                snapshot.strategy_input_fingerprint,
            )
            if existing is not None:
                result = _to_result(
                    existing,
                    payment_case.current_state,
                    idempotent=True,
                )
                session.commit()
                return result

            _validate_generation_state(session, payment_case)
            action = (
                snapshot.rule_strategy.action
                if snapshot.rule_strategy is not None
                else _required_model_result(model_result).output.action
            )
            try:
                validate_action_compatibility(
                    current_context.recovery_disposition,
                    action,
                )
            except StrategyNotAllowedError:
                append_rejected(
                    session,
                    payment_case,
                    assessment_fingerprint=snapshot.assessment_fingerprint,
                    strategy_input_fingerprint=(
                        snapshot.strategy_input_fingerprint
                    ),
                    source=_snapshot_source(snapshot),
                    action=action,
                    model=_result_model(snapshot, model_result),
                )
                session.commit()
                raise StrategyNotAllowedError(
                    "Strategy proposal is incompatible with diagnosis"
                )

            previous_state = payment_case.current_state
            current_proposal = _find_current_proposal(
                session,
                payment_case.id,
            )
            persisted_at = self._clock()
            if current_proposal is not None:
                current_proposal.superseded_at = persisted_at

            proposal = _build_proposal(
                snapshot,
                action=action,
                model_result=model_result,
            )
            session.add(proposal)
            session.flush()

            if previous_state is CaseState.DIAGNOSED:
                transition_case(
                    session,
                    payment_case,
                    CaseState.DECISIONED,
                    reason_code="STRATEGY_PROPOSAL_ACCEPTED",
                    source=STRATEGY_AUDIT_SOURCE,
                    metadata={
                        "proposal_id": str(proposal.id),
                        "strategy_input_fingerprint": (
                            proposal.strategy_input_fingerprint
                        ),
                    },
                )
            append_generated(
                session,
                payment_case,
                proposal,
                previous_state=previous_state,
            )
            result = _to_result(
                proposal,
                payment_case.current_state,
                idempotent=False,
            )
            session.commit()
            return result

    def _configured_model(self) -> str:
        model = (
            self._model_client.model
            if self._model_client is not None
            else self._settings.openai_model
        )
        if not model or len(model) > 100:
            raise StrategyConfigurationError(
                "OpenAI strategy model configuration is invalid"
            )
        return model

    def _model_client_for_request(self) -> StrategyModelClient:
        if self._model_client is not None:
            return self._model_client
        api_key = self._settings.openai_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise StrategyConfigurationError(
                "OpenAI strategy credentials are not configured"
            )
        return OpenAIResponsesClient(
            api_key=api_key,
            model=self._settings.openai_model,
            base_url=self._settings.openai_api_base_url,
        )

    def _record_generation_failure(
        self,
        snapshot: _StrategySnapshot,
        failure_reason_code: str,
    ) -> None:
        with self._session_factory() as session:
            payment_case = session.get(PaymentCase, snapshot.case_id)
            if payment_case is None:
                return
            append_generation_failure(
                session,
                payment_case,
                assessment_fingerprint=snapshot.assessment_fingerprint,
                strategy_input_fingerprint=(
                    snapshot.strategy_input_fingerprint
                ),
                model=snapshot.configured_model,
                failure_reason_code=failure_reason_code,
            )
            session.commit()


def generate_strategy(
    case_id: UUID,
    *,
    session_factory: Callable[[], Session],
    model_client: StrategyModelClient | None = None,
) -> StrategyGenerationResult:
    """Convenience entry point for one bounded strategy request."""

    return StrategyService(
        session_factory=session_factory,
        model_client=model_client,
    ).generate_strategy(case_id)


def _lock_case(session: Session, case_id: UUID) -> PaymentCase:
    payment_case = session.scalar(
        select(PaymentCase)
        .where(PaymentCase.id == case_id)
        .with_for_update()
    )
    if payment_case is None:
        raise StrategyCaseNotFoundError("Payment case was not found")
    return payment_case


def _validate_generation_state(
    session: Session,
    payment_case: PaymentCase,
) -> None:
    if payment_case.current_state is CaseState.DIAGNOSED:
        return
    if payment_case.current_state is CaseState.DECISIONED:
        current = _find_current_proposal(session, payment_case.id)
        if (
            current is not None
            and payment_case.assessment_fingerprint is not None
            and current.assessment_fingerprint
            != payment_case.assessment_fingerprint
        ):
            return
    raise StrategyNotAllowedError(
        "Case state does not allow strategy generation"
    )


def _find_identical_proposal(
    session: Session,
    case_id: UUID,
    input_fingerprint: str,
) -> StrategyProposal | None:
    return session.scalar(
        select(StrategyProposal).where(
            StrategyProposal.case_id == case_id,
            StrategyProposal.strategy_input_fingerprint == input_fingerprint,
        )
    )


def _find_current_proposal(
    session: Session,
    case_id: UUID,
) -> StrategyProposal | None:
    return session.scalar(
        select(StrategyProposal).where(
            StrategyProposal.case_id == case_id,
            StrategyProposal.superseded_at.is_(None),
        )
    )


def _required_model_result(
    model_result: StrategyModelResult | None,
) -> StrategyModelResult:
    if model_result is None:
        raise RuntimeError("AI strategy did not provide a model result")
    return model_result


def _build_proposal(
    snapshot: _StrategySnapshot,
    *,
    action: RecoveryAction,
    model_result: StrategyModelResult | None,
) -> StrategyProposal:
    rule = snapshot.rule_strategy
    if rule is not None:
        return StrategyProposal(
            case_id=snapshot.case_id,
            assessment_fingerprint=snapshot.assessment_fingerprint,
            strategy_input_fingerprint=snapshot.strategy_input_fingerprint,
            source=StrategySource.RULE,
            action=action,
            reason_code=rule.reason_code,
            explanation=rule.explanation,
            confidence=None,
            re_evaluate_after_seconds=None,
            prompt_version=STRATEGY_PROMPT_VERSION,
            model=None,
            provider_response_id=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            latency_ms=None,
        )

    result = _required_model_result(model_result)
    return StrategyProposal(
        case_id=snapshot.case_id,
        assessment_fingerprint=snapshot.assessment_fingerprint,
        strategy_input_fingerprint=snapshot.strategy_input_fingerprint,
        source=StrategySource.AI,
        action=action,
        reason_code=ai_reason_code(action),
        explanation=result.output.explanation,
        confidence=result.output.confidence,
        re_evaluate_after_seconds=(
            result.output.re_evaluate_after_seconds
        ),
        prompt_version=STRATEGY_PROMPT_VERSION,
        model=result.model,
        provider_response_id=result.provider_response_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms,
    )


def _snapshot_source(snapshot: _StrategySnapshot) -> StrategySource:
    return (
        StrategySource.RULE
        if snapshot.rule_strategy is not None
        else StrategySource.AI
    )


def _result_model(
    snapshot: _StrategySnapshot,
    model_result: StrategyModelResult | None,
) -> str | None:
    return (
        model_result.model
        if model_result is not None
        else snapshot.configured_model
    )


def _audit_stale_context(
    session: Session,
    payment_case: PaymentCase,
    snapshot: _StrategySnapshot,
    model_result: StrategyModelResult | None,
) -> None:
    action = (
        model_result.output.action
        if model_result is not None
        else snapshot.rule_strategy.action
        if snapshot.rule_strategy is not None
        else None
    )
    append_stale_context(
        session,
        payment_case,
        assessment_fingerprint=snapshot.assessment_fingerprint,
        strategy_input_fingerprint=snapshot.strategy_input_fingerprint,
        source=_snapshot_source(snapshot),
        action=action,
        model=_result_model(snapshot, model_result),
    )


def _to_result(
    proposal: StrategyProposal,
    case_state: CaseState,
    *,
    idempotent: bool,
) -> StrategyGenerationResult:
    return StrategyGenerationResult(
        proposal_id=proposal.id,
        case_id=proposal.case_id,
        case_state=case_state,
        source=proposal.source,
        action=proposal.action,
        reason_code=proposal.reason_code,
        explanation=proposal.explanation,
        confidence=proposal.confidence,
        re_evaluate_after_seconds=proposal.re_evaluate_after_seconds,
        assessment_fingerprint=proposal.assessment_fingerprint,
        strategy_input_fingerprint=proposal.strategy_input_fingerprint,
        idempotent=idempotent,
    )
