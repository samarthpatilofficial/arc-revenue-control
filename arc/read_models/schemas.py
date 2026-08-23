"""Explicit display-safe contracts for ARC's read-only API."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    EligibilityDecision,
    FailureCategory,
    PolicyDecisionResult,
    ProviderMode,
    RecoveryAction,
    RecoveryDisposition,
    RecoveryExecutionStatus,
    RecoveryOutcomeStatus,
    StrategySource,
)


class ReadModel(BaseModel):
    """Closed response contract so accidental fields cannot be introduced."""

    model_config = ConfigDict(extra="forbid")


class DataOrigin(StrEnum):
    """Display label that prevents synthetic or test evidence being called live."""

    TEST_MODE = "TEST_MODE"
    LIVE_MODE = "LIVE_MODE"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"


class DashboardSummary(ReadModel):
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


class CaseListItem(ReadModel):
    case_reference: str
    amount_minor: int | None
    currency: str | None
    current_state: CaseState
    payment_method: str | None
    failure_category: FailureCategory | None
    recovery_disposition: RecoveryDisposition | None
    eligibility_status: EligibilityDecision | None
    detected_at: datetime
    resolved_at: datetime | None
    strategy_action: RecoveryAction | None
    policy_result: PolicyDecisionResult | None
    approval_status: ApprovalStatus | None
    recovery_execution_status: RecoveryExecutionStatus | None
    outcome_status: RecoveryOutcomeStatus | None
    recovered_amount_minor: int | None
    provider_mode: ProviderMode | None
    data_origin: DataOrigin | None


class CaseProjection(ReadModel):
    case_reference: str
    amount_minor: int | None
    currency: str | None
    current_state: CaseState
    payment_method: str | None
    attempt_count: int
    contact_attempt_count: int
    detected_at: datetime
    resolved_at: datetime | None


class DiagnosisProjection(ReadModel):
    eligibility_status: EligibilityDecision | None
    eligibility_reason_code: str | None
    failure_category: FailureCategory | None
    recovery_disposition: RecoveryDisposition | None
    diagnosis_reason_code: str | None
    diagnosed_at: datetime | None


class StrategyProjection(ReadModel):
    action: RecoveryAction
    source: StrategySource
    reason_code: str
    explanation: str
    confidence: float | None
    confidence_authority: Literal["MODEL_OBSERVABILITY_ONLY"]
    created_at: datetime


class PolicyProjection(ReadModel):
    result: PolicyDecisionResult
    reason_code: str
    explanation: str
    approval_threshold_minor: int | None
    evaluated_at: datetime


class ApprovalProjection(ReadModel):
    approval_request_id: UUID
    approval_status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None


class ExecutionProjection(ReadModel):
    action: RecoveryAction
    execution_status: RecoveryExecutionStatus
    provider: str
    external_status: str | None
    execution_attempt_count: int
    executed_at: datetime | None
    next_evaluation_at: datetime | None


class OutcomeProjection(ReadModel):
    outcome_status: RecoveryOutcomeStatus
    provider_mode: ProviderMode
    provider_status: str
    amount_expected_minor: int
    amount_paid_minor: int
    currency: str
    observed_at: datetime


class AttributionProjection(ReadModel):
    provider_mode: ProviderMode
    recovered_amount_minor: int
    currency: str
    reason_code: str
    attributed_at: datetime


class CaseDetail(ReadModel):
    data_origin: DataOrigin | None
    case: CaseProjection
    diagnosis: DiagnosisProjection
    strategy: StrategyProjection | None
    policy: PolicyProjection | None
    approval: ApprovalProjection | None
    execution: ExecutionProjection | None
    outcome: OutcomeProjection | None
    attribution: AttributionProjection | None


class TimelineItem(ReadModel):
    stage: str
    title: str
    status: Literal["complete", "pending", "blocked"]
    timestamp: datetime
    detail: str | None = None
    action: RecoveryAction | None = None
    authority: str | None = None
    result: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    provider_mode: ProviderMode | None = None
    data_origin: DataOrigin | None = None


class ApprovalQueueItem(ReadModel):
    approval_request_id: UUID
    case_reference: str
    amount_minor: int | None
    currency: str | None
    strategy_action: RecoveryAction
    policy_reason_code: str
    approval_status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None
    data_origin: DataOrigin | None


class RecoveryActionItem(ReadModel):
    case_reference: str
    action: RecoveryAction
    execution_status: RecoveryExecutionStatus
    provider: str
    external_status: str | None
    execution_attempt_count: int
    executed_at: datetime | None
    next_evaluation_at: datetime | None
    outcome_status: RecoveryOutcomeStatus | None
    provider_mode: ProviderMode | None
    data_origin: DataOrigin | None
