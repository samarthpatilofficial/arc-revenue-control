"""Bounded offline and optional live-model strategy providers for evaluation."""

from dataclasses import dataclass
from typing import Protocol

from arc.domain.enums import RecoveryAction
from arc.evaluation.models import SyntheticScenario
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelClient,
    StrategyOutput,
)


class EvaluationStrategyProvider(Protocol):
    """Narrow strategy boundary used by the persistence-free runner."""

    @property
    def mode(self) -> str: ...

    def propose(
        self,
        context: StrategyContext,
        scenario: SyntheticScenario,
    ) -> StrategyOutput: ...


@dataclass(frozen=True, slots=True)
class OfflineStrategyProvider:
    """Deterministic fixtures validated by the production strategy schema."""

    @property
    def mode(self) -> str:
        return "OFFLINE"

    def propose(
        self,
        context: StrategyContext,
        scenario: SyntheticScenario,
    ) -> StrategyOutput:
        del context
        if scenario.offline_action is None:
            raise ValueError("Offline strategy fixture is missing")
        return StrategyOutput(
            action=scenario.offline_action,
            explanation=(
                "Deterministic synthetic strategy fixture validated against "
                "the ARC action contract."
            ),
            confidence=1.0,
            re_evaluate_after_seconds=(
                300 if scenario.offline_action is RecoveryAction.WAIT else None
            ),
        )


@dataclass(frozen=True, slots=True)
class OpenAIStrategyProvider:
    """Optional real-model adapter using the existing strict ARC client."""

    client: StrategyModelClient

    @property
    def mode(self) -> str:
        return "OPENAI"

    def propose(
        self,
        context: StrategyContext,
        scenario: SyntheticScenario,
    ) -> StrategyOutput:
        del scenario
        return self.client.propose(context).output
