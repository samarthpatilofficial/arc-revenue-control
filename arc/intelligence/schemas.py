"""Strict model output and minimum-data strategy context contracts."""

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from arc.domain.enums import (
    FailureCategory,
    RecoveryAction,
    RecoveryDisposition,
)

BoundedContextText = Annotated[str, Field(min_length=1, max_length=100)]
OptionalContextText = BoundedContextText | None


class StrategyOutput(BaseModel):
    """Strict, locally revalidated model proposal without authority fields."""

    model_config = ConfigDict(extra="forbid", strict=True)

    action: RecoveryAction
    explanation: Annotated[str, Field(min_length=1, max_length=500)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    re_evaluate_after_seconds: Annotated[int, Field(ge=0, le=86400)] | None


class StrategyContext(BaseModel):
    """Frozen minimum-data snapshot sent to strategy reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    amount_minor: Annotated[int, Field(ge=0)] | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    payment_method: OptionalContextText = None
    payment_status: OptionalContextText = None
    subscription_status: OptionalContextText = None
    failure_category: FailureCategory
    recovery_disposition: RecoveryDisposition
    diagnosis_reason_code: BoundedContextText
    error_reason: OptionalContextText = None
    error_source: OptionalContextText = None
    error_step: OptionalContextText = None
    attempt_count: Annotated[int, Field(ge=0)]
    recovery_kind: Literal["payment", "subscription"]


@dataclass(frozen=True, slots=True)
class StrategyModelResult:
    """Validated provider proposal plus bounded operational metadata."""

    output: StrategyOutput
    provider_response_id: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int


class StrategyModelClient(Protocol):
    """Small injected boundary for one model inference attempt."""

    @property
    def model(self) -> str:
        """Return the provider model identifier used for fingerprints."""

    def propose(self, context: StrategyContext) -> StrategyModelResult:
        """Return one locally validated bounded strategy proposal."""
