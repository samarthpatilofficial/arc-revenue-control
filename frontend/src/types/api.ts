export type ProviderMode = "TEST" | "LIVE";
export type DataOrigin =
  | "TEST_MODE"
  | "LIVE_MODE"
  | "SYNTHETIC_DEMO"
  | "SYNTHETIC_INPUT";
export type ResolutionKind =
  | "ARC_RECOVERED"
  | "ALREADY_CAPTURED"
  | "REQUIRES_APPROVAL"
  | "AWAITING_OUTCOME"
  | "EXHAUSTED"
  | "ESCALATED"
  | "PENDING";
export type StrategyProvenance =
  | "DETERMINISTIC_RULE"
  | "OFFLINE_SIMULATION"
  | "OPENAI"
  | "BYPASSED";
export type CaseState =
  | "DETECTED"
  | "RECONCILING"
  | "DIAGNOSED"
  | "DECISIONED"
  | "POLICY_VALIDATED"
  | "ACTIONED"
  | "WAITING_FOR_OUTCOME"
  | "RECOVERED"
  | "EXHAUSTED"
  | "ESCALATED";
export type FailureCategory =
  | "CUSTOMER_AUTHENTICATION"
  | "CUSTOMER_FUNDS"
  | "CUSTOMER_INTERRUPTION"
  | "CUSTOMER_OR_INSTRUMENT_RESTRICTION"
  | "BANK_OR_ISSUER"
  | "GATEWAY_OR_NETWORK"
  | "MERCHANT_CONFIGURATION"
  | "RAZORPAY_OR_PLATFORM"
  | "SUBSCRIPTION_RETRY_EXHAUSTED"
  | "UNKNOWN";
export type EligibilityDecision = "ELIGIBLE" | "WAIT" | "STOP" | "REVIEW";
export type RecoveryDisposition =
  | "CUSTOMER_ACTION_REQUIRED"
  | "RETRY_LATER"
  | "ALTERNATE_METHOD_PREFERRED"
  | "MERCHANT_FIX_REQUIRED"
  | "RECOVERY_STRATEGY_REQUIRED"
  | "MANUAL_REVIEW"
  | "UNKNOWN";
export type RecoveryAction =
  | "NO_ACTION"
  | "WAIT"
  | "REQUEST_RETRY"
  | "CREATE_RECOVERY_LINK"
  | "REQUEST_PAYMENT_METHOD_UPDATE"
  | "ESCALATE_TO_HUMAN";
export type PolicyResult = "AUTHORIZED" | "REQUIRES_APPROVAL" | "BLOCKED";
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED";
export type ExecutionStatus =
  | "PREPARED"
  | "IN_PROGRESS"
  | "SUCCEEDED"
  | "FAILED"
  | "INDETERMINATE"
  | "COMPENSATION_REQUIRED"
  | "CANCELLED";
export type OutcomeStatus =
  | "PENDING"
  | "RECOVERED"
  | "EXPIRED"
  | "CANCELLED"
  | "REVIEW_REQUIRED";

export interface DashboardSummary {
  provider_mode: ProviderMode;
  currency: string;
  cases_evaluated: number;
  revenue_at_risk_minor: number;
  recovery_actions_succeeded: number;
  recovered_cases: number;
  recovered_revenue_minor: number;
  recovery_rate_by_cases: number;
  recovery_rate_by_amount: number;
  awaiting_outcome: number;
  requires_attention: number;
}

export interface CaseListItem {
  case_reference: string;
  amount_minor: number | null;
  currency: string | null;
  current_state: CaseState;
  resolution_kind: ResolutionKind;
  payment_method: string | null;
  failure_category: FailureCategory | null;
  recovery_disposition: RecoveryDisposition | null;
  eligibility_status: EligibilityDecision | null;
  detected_at: string;
  resolved_at: string | null;
  strategy_action: RecoveryAction | null;
  strategy_provenance: StrategyProvenance;
  policy_result: PolicyResult | null;
  approval_status: ApprovalStatus | null;
  recovery_execution_status: ExecutionStatus | null;
  outcome_status: OutcomeStatus | null;
  recovered_amount_minor: number | null;
  provider_mode: ProviderMode | null;
  data_origin: DataOrigin | null;
}

export interface CaseDetail {
  data_origin: DataOrigin | null;
  case: {
    case_reference: string;
    amount_minor: number | null;
    currency: string | null;
    current_state: CaseState;
    resolution_kind: ResolutionKind;
    payment_method: string | null;
    attempt_count: number;
    contact_attempt_count: number;
    detected_at: string;
    resolved_at: string | null;
  };
  diagnosis: {
    eligibility_status: EligibilityDecision | null;
    eligibility_reason_code: string | null;
    failure_category: FailureCategory | null;
    recovery_disposition: RecoveryDisposition | null;
    diagnosis_reason_code: string | null;
    diagnosed_at: string | null;
  };
  strategy: {
    action: RecoveryAction;
    source: "RULE" | "AI";
    provenance: StrategyProvenance;
    model: string | null;
    reason_code: string;
    explanation: string;
    confidence: number | null;
    confidence_authority: "MODEL_OBSERVABILITY_ONLY" | null;
    created_at: string;
  } | null;
  policy: {
    result: PolicyResult;
    reason_code: string;
    explanation: string;
    approval_threshold_minor: number | null;
    evaluated_at: string;
  } | null;
  approval: {
    approval_request_id: string;
    approval_status: ApprovalStatus;
    requested_at: string;
    decided_at: string | null;
  } | null;
  execution: {
    action: RecoveryAction;
    execution_status: ExecutionStatus;
    provider: string;
    external_status: string | null;
    execution_attempt_count: number;
    executed_at: string | null;
    next_evaluation_at: string | null;
  } | null;
  outcome: {
    outcome_status: OutcomeStatus;
    provider_mode: ProviderMode;
    provider_status: string;
    amount_expected_minor: number;
    amount_paid_minor: number;
    currency: string;
    observed_at: string;
  } | null;
  attribution: {
    provider_mode: ProviderMode;
    recovered_amount_minor: number;
    currency: string;
    reason_code: string;
    attributed_at: string;
  } | null;
}

export interface TimelineItem {
  stage: string;
  title: string;
  status: "complete" | "pending" | "blocked";
  timestamp: string;
  detail: string | null;
  action: RecoveryAction | null;
  authority: string | null;
  strategy_provenance: StrategyProvenance | null;
  strategy_model: string | null;
  result: string | null;
  amount_minor: number | null;
  currency: string | null;
  provider_mode: ProviderMode | null;
  data_origin: DataOrigin | null;
}

export interface ApprovalQueueItem {
  approval_request_id: string;
  case_reference: string;
  amount_minor: number | null;
  currency: string | null;
  strategy_action: RecoveryAction;
  strategy_provenance: StrategyProvenance;
  policy_reason_code: string;
  approval_status: ApprovalStatus;
  requested_at: string;
  decided_at: string | null;
  data_origin: DataOrigin | null;
}

export interface RecoveryActionItem {
  case_reference: string;
  action: RecoveryAction;
  strategy_provenance: StrategyProvenance;
  execution_status: ExecutionStatus;
  provider: string;
  external_status: string | null;
  execution_attempt_count: number;
  executed_at: string | null;
  next_evaluation_at: string | null;
  outcome_status: OutcomeStatus | null;
  provider_mode: ProviderMode | null;
  data_origin: DataOrigin | null;
}

export interface CaseFilters {
  state?: CaseState;
  failureCategory?: FailureCategory;
  providerMode?: ProviderMode;
  limit?: number;
  offset?: number;
}

export interface HealthResponse {
  status: "ok";
  service: "arc-api";
}

export interface EvaluationSummary {
  evaluation_name: string;
  evaluation_version: string;
  dataset_version: string;
  evidence_class: "SYNTHETIC_EVALUATION";
  strategy_mode: "OFFLINE";
  status: "PASS";
  case_count: number;
  metrics: {
    cases_evaluated: number;
    revenue_evaluated_minor: number;
    revenue_at_risk_minor: number;
    eligible_cases: number;
    ai_or_strategy_cases: number;
    deterministic_bypass_cases: number;
    automated_actions_authorized: number;
    human_approval_required: number;
    wait_cases: number;
    safe_stop_cases: number;
    already_captured_protected: number;
    duplicate_actions_prevented: number;
    synthetic_recovered_cases: number;
    synthetic_recovered_amount_minor: number;
    synthetic_recovery_rate_by_cases: number;
    synthetic_recovery_rate_by_amount: number;
    unresolved_cases: number;
    policy_violations_executed: number;
    unsafe_actions_after_capture: number;
    duplicate_executions: number;
    strategy_failures_or_fallbacks: number;
  };
}
