# ARC — Technical Architecture

**Project:** ARC — Autonomous Revenue Control  
**Subtitle:** Policy-Governed AI Revenue Recovery for Razorpay Merchants  
**Hackathon Track:** Razorpay AI Buildathon — Track 03: AI Revenue Recovery  
**Status:** Architecture baseline for the three-day build

---

## 1. Purpose of This Document

This document defines the technical architecture for ARC.

`docs/PROJECT.md` explains **what ARC is and why it exists**.  
`AGENTS.md` explains **how Codex must behave while implementing it**.  
This file explains **how the system is structured technically, how data moves through it, where trust boundaries exist, and which components are allowed to make which decisions**.

The architecture is intentionally designed for a three-day hackathon build while preserving the engineering principles expected from a serious fintech prototype.

The goal is not to imitate a large production platform with unnecessary infrastructure. The goal is to build a small system with strong boundaries, clear failure behavior, measurable outcomes, and a credible path to production evolution.

---

## 2. Architecture Goals

ARC should satisfy the following architectural goals.

### 2.1 Financial state correctness

The system must establish current payment truth before attempting recovery.

### 2.2 Idempotent processing

Duplicate webhook delivery must not create duplicate cases, duplicate decisions, or duplicate recovery actions.

### 2.3 Safe event ordering

Webhook arrival order must not be assumed to equal transaction-state order.

### 2.4 Bounded AI

AI may recommend recovery strategy, but it must not control state truth, policy enforcement, or unrestricted financial execution.

### 2.5 Deterministic authorization

All recovery actions must pass explicit machine-testable merchant policy before execution.

### 2.6 Auditability

Every meaningful external event, internal transition, decision, policy result, action, and outcome should be reconstructable.

### 2.7 Graceful failure

Invalid, incomplete, stale, duplicated, unsupported, or externally failed operations should not cause unsafe financial behavior.

### 2.8 Measurability

The architecture must support batch evaluation and direct calculation of revenue-at-risk and recovered-revenue metrics.

### 2.9 Pragmatic implementation

The system should remain implementable within three days using a modular monolith rather than premature distributed infrastructure.

---

## 3. Architectural Style

ARC will use a **modular monolith with event-driven domain processing**.

This means:

- one primary backend application;
- clear internal modules with explicit responsibilities;
- PostgreSQL as the authoritative persistence layer;
- webhook events as the primary external event source;
- synchronous processing where safe and simple during the prototype;
- internal boundaries designed so asynchronous workers can be introduced later without rewriting the domain model.

This is deliberate.

ARC does **not** require Kafka, Kubernetes, Redis, Celery, or multiple microservices to demonstrate the core engineering problem.

The modular-monolith approach gives us:

- lower implementation risk;
- easier local setup;
- simpler debugging;
- transactional integrity;
- faster test execution;
- clearer auditability;
- a credible migration path if the system later needs independent workers or queues.

---

## 4. System Context

```text
                         +----------------------+
                         |    Merchant / Ops    |
                         | dashboard + approval |
                         +----------+-----------+
                                    |
                                    v
+------------------+      +---------+----------+       +-------------------+
| Razorpay Test    |----->|       ARC API      |------>|    OpenAI API     |
| Mode / Webhooks  |      |  Control Plane     |       | bounded strategy  |
+------------------+      +---------+----------+       +-------------------+
                                    |
                                    v
                         +----------+-----------+
                         |      PostgreSQL      |
                         | source of ARC truth  |
                         +----------------------+
```

External systems:

- **Razorpay Test Mode** — payment/subscription events and recovery API operations.
- **OpenAI API** — bounded contextual strategy generation, introduced on Day 2.
- **Merchant / Operator** — reviews recovery state and approves high-value cases when required.

Internal source of truth:

- **PostgreSQL** — ARC event history, current recovery state, decisions, policies, action records, and evaluation data.

---

## 5. High-Level Component Architecture

```text
                         RAZORPAY TEST MODE
                                |
                                v
                    +-------------------------+
                    |     Webhook Gateway     |
                    | signature / event id    |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    | Immutable Event Ledger  |
                    | persist before process  |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    |     State Reconciler    |
                    | current financial truth |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    | Eligibility / Preconditions|
                    | should ARC consider action?|
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    |   Failure Intelligence  |
                    | deterministic diagnosis |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    |    AI Strategy Engine   |
                    | bounded recommendation  |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    | Policy & Authorization  |
                    | deterministic controls  |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    |     Action Executor     |
                    | approved actions only   |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    |    Outcome Observer     |
                    | success/failure/timeout |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    | Recovery Attribution    |
                    | + Audit + Metrics       |
                    +-------------------------+
```

The key design rule is:

> **AI proposes. Policy authorizes. The executor acts.**

---

## 6. Backend Module Boundaries

Preferred backend module structure:

```text
arc/
|-- domain/
|   |-- states.py
|   |-- events.py
|   |-- cases.py
|   |-- decisions.py
|   `-- actions.py
|
|-- ingestion/
|   `-- webhook_service.py
|
|-- reconciliation/
|   `-- payment_reconciler.py
|
|-- diagnosis/
|   `-- failure_classifier.py
|
|-- policy/
|   |-- eligibility.py
|   `-- authorization.py
|
|-- intelligence/
|   |-- strategy_service.py
|   `-- schemas.py
|
|-- execution/
|   |-- action_executor.py
|   `-- recovery_link.py
|
`-- audit/
    |-- case_timeline.py
    `-- attribution.py
```

Integration code belongs outside the domain layer:

```text
integrations/
`-- razorpay/
    |-- client.py
    |-- signature.py
    |-- schemas.py
    `-- mapper.py
```

The domain layer must not depend directly on HTTP request objects, FastAPI, Razorpay SDK internals, or OpenAI SDK objects.

---

## 7. Trust Boundaries

ARC operates across three primary trust boundaries.

### 7.1 External payment event boundary

Incoming webhook payloads are untrusted until signature verification succeeds.

Required controls:

- retain raw request body;
- validate signature before financial-state mutation;
- capture Razorpay event id;
- reject invalid signature;
- never trust user-controlled payload fields simply because JSON parsing succeeds.

### 7.2 AI boundary

Model output is untrusted until schema and policy validation succeed.

Required controls:

- structured output;
- strict enum action vocabulary;
- bounded confidence fields;
- required reason code;
- no arbitrary tool names;
- no arbitrary URLs or API payloads;
- deterministic policy validation after model output;
- safe fallback on timeout or malformed output.

### 7.3 Execution boundary

A valid recommendation is still not permission to act.

The action executor accepts only a policy-authorized internal action object, not raw model output.

---

## 8. Webhook Processing Flow

The webhook path is one of ARC's most important correctness boundaries.

```text
HTTP POST /webhooks/razorpay
        |
        v
Read raw body
        |
        v
Verify signature
        |
        +---- invalid ----> reject request / no case mutation
        |
        v
Read event identifier
        |
        v
Check / insert event ledger row
        |
        +---- duplicate ---> return idempotent success / no duplicate processing
        |
        v
Persist event
        |
        v
Process event
        |
        v
Create/update payment case
        |
        v
Append internal case event
        |
        v
Mark webhook event processed or failed
```

### Store first, process second

A valid accepted webhook should be durably recorded before complex business processing.

If processing fails after persistence, ARC should retain:

- original event;
- processing status;
- error details;
- ability to inspect/retry manually or through a later worker.

---

## 9. Event Idempotency Design

ARC requires idempotency at more than one layer.

### 9.1 Event-level idempotency

`webhook_events.razorpay_event_id` should have a database unique constraint.

This protects against:

- webhook redelivery;
- concurrent duplicate requests;
- application-level race conditions.

Application checks alone are not sufficient; the database constraint is the final authority.

### 9.2 Case-level idempotency

Multiple legitimate events about the same payment should update the same logical recovery case rather than create unrelated duplicate cases.

The case lookup strategy should use payment/subscription identifiers and explicit domain rules.

### 9.3 Action-level idempotency

Day 2 action execution must have its own idempotency protection.

A duplicate model decision, retry, or API request must not create a second recovery action.

Recommended internal key concept:

```text
action_idempotency_key = case_id + action_type + strategy_version/recovery_attempt
```

Exact implementation may evolve, but action execution must be independently protected from event ingestion.

---

## 10. State Reconciliation

State reconciliation determines **current truth** before ARC decides what to do.

This layer must be deterministic.

It should answer:

- What case does this event belong to?
- What is the current ARC state?
- Is the incoming event newer, stale, duplicate, or terminally superseded?
- Has the payment already succeeded?
- Is the case still recoverable?

### Important invariant

A successful/captured payment must not be moved backward into failed/recovery state because a stale `payment.failed` event arrives later.

Possible implementation strategies:

- explicit event precedence rules;
- terminal-state guards;
- reconciliation against known current payment state when necessary;
- timestamps only as supporting signals, never as the sole correctness mechanism.

The reconciler should produce an explicit result object, for example:

```text
ReconciliationResult
- case_id
- previous_state
- resolved_state
- changed: bool
- reason_code
- should_continue_processing: bool
```

---

## 11. Recovery Lifecycle State Machine

ARC case lifecycle:

```text
DETECTED
   |
   v
RECONCILING
   |
   v
DIAGNOSED
   |
   v
DECISIONED
   |
   v
POLICY_VALIDATED
   |
   v
ACTIONED
   |
   v
WAITING_FOR_OUTCOME
   |
   +-------------+-------------+
   |             |             |
   v             v             v
RECOVERED     EXHAUSTED     ESCALATED
```

### Transition design

State transition validity should live in one explicit domain policy rather than ad-hoc assignments throughout services.

Example rules:

- `DETECTED -> RECONCILING` allowed;
- `RECONCILING -> DIAGNOSED` allowed;
- `DIAGNOSED -> DECISIONED` allowed;
- `DECISIONED -> POLICY_VALIDATED` allowed;
- `POLICY_VALIDATED -> ACTIONED` allowed when approved;
- `POLICY_VALIDATED -> ESCALATED` allowed when approval required;
- `ACTIONED -> WAITING_FOR_OUTCOME` allowed;
- `WAITING_FOR_OUTCOME -> RECOVERED` allowed;
- `WAITING_FOR_OUTCOME -> EXHAUSTED` allowed;
- any active state -> `RECOVERED` may be allowed when authoritative successful payment truth arrives;
- `RECOVERED -> DIAGNOSED` must not be allowed.

The implementation should test invalid transitions explicitly.

---

## 12. Failure Intelligence

Failure intelligence interprets payment failure data using deterministic logic before AI is involved.

Input signals may include:

- error code;
- error description;
- error source;
- error step;
- error reason;
- payment method;
- subscription state;
- attempt count.

The classifier should produce a normalized category and reason code.

Example categories:

```text
CUSTOMER_FUNDS
CUSTOMER_AUTHENTICATION
PAYMENT_INSTRUMENT
ISSUER_OR_BANK
GATEWAY_OR_NETWORK
PLATFORM_RETRY_ACTIVE
RETRY_EXHAUSTED
UNKNOWN_OR_INCOMPLETE
```

These names are internal design candidates and may be refined during implementation.

The important requirement is that downstream components receive structured diagnosis rather than relying on free-form text parsing.

---

## 13. Eligibility / Preconditions Gate

The eligibility gate runs before AI strategy generation where possible.

Its job is to avoid unnecessary AI calls and prevent obviously invalid recovery attempts.

Example rules:

```text
IF payment already captured
THEN NO_ACTION

IF duplicate event
THEN NO_NEW_PROCESSING

IF subscription retry still active
THEN WAIT

IF stale event after terminal success
THEN NO_ACTION

IF required identifiers missing
THEN MANUAL_REVIEW / SAFE_HOLD

IF case exhausted by policy
THEN EXHAUSTED
```

The eligibility result should be persisted as part of the decision/audit history where meaningful.

---

## 14. AI Strategy Engine

The AI Strategy Engine is introduced only after the Day 1 deterministic core is stable.

### Input contract

The model should receive only the context needed for strategy generation.

Candidate input:

```json
{
  "case_id": "RC-1024",
  "amount": 18500,
  "currency": "INR",
  "payment_method": "card",
  "failure_category": "PAYMENT_INSTRUMENT",
  "failure_reason": "...",
  "attempt_count": 3,
  "subscription_state": "halted",
  "recovery_attempts": 0,
  "time_since_failure_seconds": 420,
  "merchant_policy_summary": {
    "max_automated_attempts": 2,
    "approval_threshold": 25000,
    "allowed_actions": [
      "NO_ACTION",
      "WAIT",
      "CREATE_RECOVERY_LINK",
      "ESCALATE_TO_HUMAN"
    ]
  }
}
```

### Output contract

The model must return structured output matching a strict schema.

Candidate output:

```json
{
  "action": "CREATE_RECOVERY_LINK",
  "reason_code": "RETRY_EXHAUSTED_VALID_CUSTOMER",
  "explanation": "Platform retries are exhausted and the case remains recoverable through a fresh payment path.",
  "confidence": 0.91,
  "requires_human_approval": false,
  "re_evaluate_after_seconds": null
}
```

### Bounded action vocabulary

Initial values:

- `NO_ACTION`
- `WAIT`
- `REQUEST_RETRY`
- `CREATE_RECOVERY_LINK`
- `REQUEST_PAYMENT_METHOD_UPDATE`
- `ESCALATE_TO_HUMAN`

### Failure behavior

If the model:

- times out;
- returns invalid JSON;
- returns an unknown action;
- violates schema;
- produces insufficient reasoning;

ARC must not execute a recovery action automatically.

Safe fallback options include:

- deterministic `WAIT`;
- `ESCALATE_TO_HUMAN`;
- retrying model generation within a bounded limit;
- marking strategy generation failed for operator review.

---

## 15. Policy & Authorization Engine

This layer is the final deterministic authority before execution.

Inputs:

- current reconciled case state;
- proposed action;
- merchant policy;
- recovery attempt history;
- action history;
- approval threshold;
- case amount;
- stop conditions.

Example rules:

```text
IF automation_enabled = false
THEN require human approval

IF proposed_action not in allowed_actions
THEN reject

IF payment already captured
THEN reject

IF automated_attempts >= max_automated_attempts
THEN reject or escalate

IF amount >= approval_threshold
THEN require human approval

IF same action already executed for same attempt
THEN reject duplicate

IF recovery window expired
THEN escalate or exhaust
```

Output should be explicit:

```text
PolicyDecision
- result: APPROVED | REJECTED | REQUIRES_APPROVAL
- reason_code
- explanation
- evaluated_rules
- evaluated_at
```

The AI model must not be able to override this result.

---

## 16. Action Execution

The action executor performs only policy-authorized actions.

The executor should expose explicit typed functions rather than arbitrary tool invocation.

Example interface:

```text
execute_wait(...)
execute_request_retry(...)
execute_create_recovery_link(...)
execute_request_payment_method_update(...)
execute_escalation(...)
```

For the hackathon, the most important externally exercised action is expected to be a Razorpay Test Mode recovery payment path such as a Payment Link where appropriate.

Execution requirements:

- idempotency;
- policy authorization reference;
- case-state validation immediately before execution;
- API error capture;
- response persistence;
- audit event creation;
- no secret leakage into logs.

### Pre-execution recheck

Before performing an externally visible recovery action, the executor should confirm that the case has not already become terminal/successful.

This reduces the risk of executing a recovery request after a late `payment.captured` event.

---

## 17. Human Approval Path

High-value or policy-sensitive cases may require operator approval.

Architecture flow:

```text
AI / Rule Recommendation
        |
        v
Policy = REQUIRES_APPROVAL
        |
        v
Case -> ESCALATED / approval queue
        |
        v
Operator reviews
        |
        +---- reject ----> decision/audit recorded
        |
        v
approve
        |
        v
revalidate current state + policy
        |
        v
Action Executor
```

Approval must not bypass state revalidation.

A case may have changed between recommendation time and human approval time.

---

## 18. Outcome Observation

ARC must observe what happens after action execution.

Sources of outcome truth may include:

- subsequent Razorpay webhooks;
- explicit Razorpay API state checks where required;
- controlled test-mode simulation for scenarios that cannot be exercised directly.

Outcome types may include:

```text
PAYMENT_RECOVERED
PAYMENT_FAILED_AGAIN
STILL_PENDING
CUSTOMER_ACTION_REQUIRED
ACTION_CANCELLED
RECOVERY_EXHAUSTED
ESCALATED
```

Outcome processing must use the same reconciliation rules as initial event processing.

---

## 19. Recovery Attribution

ARC should distinguish between:

- revenue that was at risk;
- revenue for which ARC initiated a recovery workflow;
- revenue that recovered independently before ARC acted;
- revenue recovered after ARC action;
- revenue unresolved/exhausted.

This is essential for credible evaluation.

Suggested attribution fields/concepts:

```text
case_id
amount_at_risk
recovery_action_id
recovery_started_at
payment_captured_at
attribution_status
attributed_recovered_amount
```

Candidate attribution statuses:

```text
NOT_APPLICABLE
RECOVERED_WITHOUT_ARC_ACTION
ARC_ACTION_ASSOCIATED
UNRESOLVED
EXHAUSTED
```

The exact attribution rule must be documented and applied consistently across the batch evaluation.

The prototype must not claim causal certainty beyond what the implemented test scenario supports.

---

## 20. Audit Model

ARC uses two related histories.

### External event history

`webhook_events`

Records what external systems sent ARC.

### Internal case history

`case_events`

Records what ARC did with that information.

Example internal event sequence:

```text
CASE_DETECTED
STATE_RECONCILED
FAILURE_DIAGNOSED
ELIGIBILITY_EVALUATED
STRATEGY_GENERATED
POLICY_APPROVED
ACTION_EXECUTED
OUTCOME_OBSERVED
CASE_RECOVERED
```

Each important event should include timestamp and structured metadata.

Audit entries should be append-oriented.

Do not silently mutate historical decisions to make current state look cleaner.

---

## 21. Persistence Architecture

PostgreSQL is the system of record for ARC.

Core tables:

```text
webhook_events
payment_cases
case_events
decisions
merchant_policies
```

Day 2 may introduce an action execution table if required.

Recommended additional concept:

```text
recovery_actions
```

Possible fields:

- id;
- case_id;
- action_type;
- status;
- idempotency_key;
- policy_decision_id;
- external_reference;
- request metadata;
- response metadata;
- executed_at;
- completed_at;
- error code/message.

This separates strategy decisions from externally executed operations.

### Transaction boundaries

Where practical, use database transactions to ensure logically related updates remain consistent, for example:

- create webhook ledger row + mark duplicate status;
- create/update case + append case event;
- persist policy decision + create action intent.

External API calls should not remain inside long database transactions.

Recommended pattern:

1. validate current state;
2. persist action intent;
3. commit;
4. call external API;
5. persist result;
6. append audit event.

---

## 22. API Surface

Initial API surface should stay small.

### System

```text
GET /health
```

### Razorpay integration

```text
POST /webhooks/razorpay
```

### Operator / dashboard APIs — Day 2

Candidate endpoints:

```text
GET  /api/cases
GET  /api/cases/{case_id}
GET  /api/cases/{case_id}/timeline
GET  /api/metrics
GET  /api/approvals
POST /api/approvals/{case_id}/approve
POST /api/approvals/{case_id}/reject
```

### Evaluation — internal/admin

Candidate endpoints or CLI commands:

```text
POST /api/evaluation/run
GET  /api/evaluation/{run_id}
```

A CLI batch runner may be simpler and is acceptable for the hackathon.

Do not create endpoints merely because CRUD generation is easy.

---

## 23. Dashboard Architecture

The frontend should consume backend APIs and should not duplicate financial decision logic.

The web application should be a thin operator interface over ARC state.

Primary views:

```text
Overview / Revenue Control
Recovery Cases
Case Detail / Decision Trace
Human Approvals
Evaluation Results
```

The frontend must not:

- infer whether a case is safe to recover;
- reconstruct policy logic independently;
- call Razorpay directly with secrets;
- call OpenAI directly from the browser.

All sensitive integrations belong in the backend.

---

## 24. Security Architecture

### Secret management

Required environment variables may include:

```text
DATABASE_URL
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
OPENAI_API_KEY
```

Only `.env.example` belongs in Git.

Actual values must never be committed.

### Logging

Logs must avoid:

- full secrets;
- authorization headers;
- private keys;
- unnecessary customer-sensitive fields.

### Webhook security

Invalid signature must result in rejection before financial-state mutation.

### AI security

Model output must be treated as untrusted input.

### Operator actions

For hackathon scope, authentication may be intentionally simplified, but the limitation must be documented. Do not pretend the prototype has enterprise IAM if it does not.

---

## 25. Observability

ARC should provide enough visibility to debug and demonstrate behavior.

Minimum observability:

- structured application logs;
- correlation by webhook event id;
- correlation by recovery case id;
- action id/reference;
- processing status;
- processing error;
- decision reason codes;
- policy result;
- outcome result.

Useful structured log context:

```text
request_id
event_id
case_id
action_id
event_type
case_state
reason_code
```

Do not build a full observability platform for the hackathon.

---

## 26. Testing Architecture

ARC should use layered tests.

### 26.1 Unit tests

Target pure or nearly pure logic:

- state transitions;
- failure classification;
- eligibility rules;
- policy authorization;
- strategy schema validation;
- recovery attribution.

### 26.2 Integration tests

Target boundaries:

- FastAPI webhook endpoint;
- signature validation;
- database persistence;
- event uniqueness;
- case update flow;
- out-of-order event behavior;
- action persistence;
- approval flow.

### 26.3 Contract tests / mocked external tests

Target:

- Razorpay API client request/response mapping;
- OpenAI structured output handling;
- error/timeout handling.

### 26.4 Live Test Mode verification

Where practical, exercise real Razorpay Test Mode behavior for the final demo.

Do not label a mocked test as live integration.

---

## 27. Required Adversarial Scenarios

The architecture must be able to survive these scenarios:

### Duplicate webhook

Expected:

- one external event processed;
- duplicate acknowledged safely;
- no duplicate case/action.

### Out-of-order event

Example:

```text
payment.captured
payment.failed
```

Expected:

- case remains successful/resolved;
- stale failure recorded but cannot regress state.

### Late capture

Example:

```text
payment.failed
ARC begins evaluation
payment.captured
```

Expected:

- pending recovery becomes unnecessary;
- action blocked/cancelled before unsafe duplicate customer request where possible.

### AI malformed output

Expected:

- schema rejection;
- no execution;
- safe fallback or escalation.

### AI timeout

Expected:

- bounded retry or fallback;
- no uncontrolled action.

### Razorpay API error

Expected:

- action recorded as failed;
- error captured;
- case remains recoverable/reviewable;
- no false success metric.

### Duplicate action execution request

Expected:

- idempotency prevents second external action.

### High-value action

Expected:

- policy returns `REQUIRES_APPROVAL`;
- no automatic action before approval.

### Missing context

Expected:

- safe hold/manual review rather than invented data.

---

## 28. Batch Evaluation Architecture

The evaluation system should use the same domain services as the live system wherever possible.

Do not create a separate simplified evaluation implementation that bypasses production logic.

Suggested flow:

```text
Synthetic Scenario Generator
        |
        v
Scenario Dataset
        |
        v
ARC Processing Services
        |
        v
Outcome Simulation / Test Mode Events
        |
        v
Recovery Attribution
        |
        v
Evaluation Aggregator
        |
        v
JSON/CSV + Dashboard Metrics
```

Scenario dataset should include approximately 100–250 cases depending on available time.

Metrics may include:

- cases evaluated;
- revenue evaluated;
- revenue at risk;
- workflows initiated;
- no-action decisions;
- wait decisions;
- human escalations;
- duplicate actions prevented;
- premature actions prevented;
- recovered cases;
- recovered amount;
- recovery rate;
- unresolved amount;
- model failures;
- policy violations executed.

The expected value for `policy violations executed` should be zero if the architecture works correctly.

---

## 29. Deployment Topology — Hackathon

The final deployment should remain simple.

Possible topology:

```text
Browser
   |
   v
Frontend hosting
   |
   v
FastAPI backend
   |
   +---------> OpenAI API
   |
   +---------> Razorpay Test Mode
   |
   v
Managed PostgreSQL
```

Deployment provider selection should prioritize:

- fast setup;
- stable HTTPS endpoint for webhooks;
- environment variable support;
- logs;
- PostgreSQL connectivity;
- low operational overhead.

Do not redesign the domain architecture around a hosting provider.

---

## 30. Scaling Path Beyond the Hackathon

The prototype architecture should have a credible evolution path without pretending those components already exist.

If production traffic required it, possible future evolution could include:

```text
Webhook Gateway
      |
      v
Durable Event Queue
      |
      v
Independent Processing Workers
      |
      +--> Reconciliation Worker
      +--> Decision Worker
      +--> Action Worker
      +--> Outcome Worker
```

Other future capabilities could include:

- merchant multi-tenancy;
- stronger IAM/RBAC;
- encrypted sensitive fields;
- dedicated secret manager;
- queue-based retries;
- distributed tracing;
- dead-letter queues;
- policy versioning;
- model version tracking;
- richer recovery experimentation;
- production reconciliation workflows.

These are architectural evolution notes, **not current implementation claims**.

---

## 31. Architecture Decisions to Capture as ADRs

Material decisions should be recorded in `docs/decisions/` as implementation proceeds.

Recommended initial ADRs:

### ADR-001 — Modular monolith instead of microservices

Reason: three-day build, transactional integrity, lower operational overhead, clear internal boundaries.

### ADR-002 — PostgreSQL as source of truth

Reason: durable relational state, uniqueness constraints, transactional support, audit-friendly model.

### ADR-003 — AI proposes, deterministic policy authorizes

Reason: financial safety and explainability.

### ADR-004 — Persist accepted webhook before processing

Reason: preserve audit evidence and failure recoverability.

### ADR-005 — Database-enforced event idempotency

Reason: application-only deduplication is insufficient under concurrent delivery.

### ADR-006 — No Kafka/Redis/Celery in initial prototype

Reason: no demonstrated need during three-day scope.

Do not create an ADR merely to increase file count; only material decisions need one.

---

## 32. Day-by-Day Architecture Delivery

### Day 1

Architecture implemented:

```text
Webhook Gateway
-> Event Ledger
-> State Reconciler
-> Eligibility Gate
-> Failure Intelligence
-> Deterministic Decision/Policy
-> Audit Trail
```

No AI in the critical path.

### Day 2

Extend architecture with:

```text
AI Strategy Engine
-> Policy Authorization
-> Action Executor
-> Human Approval
-> Outcome Observer
-> Recovery Attribution
-> Dashboard
```

### Day 3

Validate architecture through:

```text
Failure injection
-> adversarial scenarios
-> batch evaluation
-> defect fixes
-> documentation
-> stable demo deployment
```

---

## 33. Architecture Definition of Done

The architecture can be considered successfully implemented for the hackathon when:

1. valid Razorpay events enter through a verified webhook boundary;
2. events are persisted and deduplicated;
3. recovery cases reconcile to safe current state;
4. stale or out-of-order events cannot regress paid state;
5. failure context is normalized;
6. eligibility can stop unnecessary recovery before AI use;
7. AI recommendations are structured and bounded;
8. deterministic policy can approve, reject, or require human approval;
9. executor performs only authorized actions;
10. action execution is idempotent;
11. outcomes update cases safely;
12. recovered revenue is attributed using documented rules;
13. operators can inspect the decision trace;
14. batch evaluation uses the same core domain logic;
15. failure scenarios are tested and documented;
16. no secrets or fake production claims are present.

---

## 34. Final Architectural Principle

ARC should never be judged by the number of components in the diagram.

The architecture succeeds if the system can answer, for every recovery case:

> **What happened? What is true now? Why did ARC recommend this? Was it allowed? What action actually happened? Did it recover the money?**

That is the architecture ARC is designed to support.