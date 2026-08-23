# ARC — Autonomous Revenue Control

**Policy-Governed AI Revenue Recovery for Razorpay Merchants**

**Hackathon:** Razorpay AI Buildathon  
**Track:** Track 03 — AI Revenue Recovery  
**Repository:** `https://github.com/samarthpatilofficial/arc-revenue-control`

---

## 1. Executive Summary

ARC — Autonomous Revenue Control is an event-driven, policy-governed revenue-recovery control plane for merchants using Razorpay.

ARC is built around a simple but important observation: **a payment failure is not automatically lost revenue, and a recovery action is not automatically the right action.** A transaction may succeed moments later, an existing retry may already be scheduled, the customer may need a different payment method, repeated retries may be inappropriate, or a high-value case may require human approval.

ARC therefore does not treat every payment failure as a trigger to “retry” or “send a reminder.” Instead, ARC determines the current payment truth, diagnoses the failure context, decides whether intervention is necessary, recommends the safest next action, validates that action against deterministic merchant policies, executes only authorized recovery steps, observes the outcome, and measures whether revenue was actually recovered.

The core recovery loop is:

```text
detect -> reconcile -> diagnose -> decide -> authorize -> execute -> observe -> measure
```

The system is designed to demonstrate four things strongly:

1. **Problem taste** — solve the real decision gap between payment failure and safe recovery.
2. **Build quality** — reliable, structured, testable, auditable infrastructure.
3. **AI judgment** — use AI only where contextual reasoning adds value.
4. **Failure recovery** — handle duplicates, stale state, malformed output, API failures, and recovery edge cases safely.

---

## 2. Product Vision

ARC should feel like a serious fintech control system rather than a student AI project.

The product vision is:

> **Give merchants a controlled system for deciding when revenue recovery should happen — and proving when it worked.**

ARC is not intended to be a fully autonomous financial system with unrestricted AI authority. Instead, ARC deliberately separates responsibilities:

- deterministic software establishes financial truth;
- AI recommends a bounded next-best action;
- deterministic policy decides whether the action is allowed;
- the executor performs only approved actions;
- the audit layer records every meaningful step.

This separation is central to the project.

---

## 3. Problem Statement

Payment failures create an operational gap between **what happened** and **what should happen next**.

A merchant may receive a failure signal, but that signal alone does not answer:

- Is the payment still actually failed?
- Did the payment succeed shortly afterward?
- Is Razorpay already retrying the subscription?
- Was the failure caused by insufficient funds, customer authentication, an issuer problem, a gateway problem, or another reason?
- Should ARC wait, retry, create a new recovery path, request a payment-method update, or escalate to a person?
- How many times has this customer already been contacted or retried?
- Is the transaction too high-value for autonomous recovery?
- Is the proposed action permitted under merchant policy?
- When must ARC stop?
- Did the recovery action actually recover money?

Naive automation can create new problems:

- duplicate recovery requests;
- unnecessary customer contact;
- repeated attempts after payment has already succeeded;
- bad retry timing;
- conflicting workflows;
- unsafe financial actions from an AI model;
- unclear responsibility when something goes wrong;
- no reliable attribution of recovered revenue.

ARC addresses this decision and control gap.

---

## 4. What ARC Solves

ARC turns fragmented payment and subscription events into managed revenue-recovery cases.

For each case, ARC aims to answer five questions:

1. **What is the current financial truth?**
2. **Why is the revenue at risk?**
3. **Should ARC act at all?**
4. **What is the safest allowed next action?**
5. **Did that action recover the revenue?**

Expected value for merchants:

- reduce duplicate recovery actions;
- reduce premature or unnecessary outreach;
- identify recoverable revenue more systematically;
- reduce manual finance-operations effort;
- enforce recovery limits and approval rules;
- provide explainable decision traces;
- measure recovery outcomes across a batch rather than individual anecdotes.

---

## 5. Project Objectives

ARC has five primary objectives.

### 5.1 Prevent unsafe or redundant recovery

The system must prevent:

- duplicate processing of the same event;
- duplicate execution of the same recovery action;
- action on stale state;
- recovery after the payment has already succeeded;
- invalid backwards state transitions;
- uncontrolled autonomous actions.

### 5.2 Make context-aware recovery decisions

The system should consider structured context such as:

- payment amount;
- payment method;
- failure source;
- failure step;
- failure reason;
- number of attempts;
- previous successful payments when available;
- subscription state;
- previous recovery attempts;
- time since failure;
- merchant recovery policy.

### 5.3 Enforce deterministic merchant policy

ARC must support explicit controls such as:

- automation enabled or disabled;
- allowed recovery actions;
- maximum automated attempts;
- maximum customer contacts;
- high-value thresholds;
- human-approval thresholds;
- recovery windows;
- stopping rules.

### 5.4 Maintain a full decision audit trail

The merchant should be able to understand:

- what event ARC received;
- whether the event was valid;
- how ARC reconciled the state;
- what failure ARC identified;
- what action was recommended;
- why policy allowed or blocked the action;
- what action was executed;
- what happened afterward;
- how much revenue was recovered.

### 5.5 Measure business outcome

ARC should evaluate performance across a realistic test-mode or synthetic batch.

The final submission should report measured results generated by the system, not hand-written impressive numbers.

---

## 6. Product Principles

### 6.1 AI proposes. Policy authorizes.

The AI strategy engine does not directly control unrestricted financial APIs.

### 6.2 Store first. Process second.

Accepted external events should be persisted before business processing so failures do not erase evidence.

### 6.3 Current state matters more than arrival order.

Webhook arrival order must never be treated as guaranteed transaction order.

### 6.4 Explicit states over hidden behavior.

Recovery cases should move through a visible lifecycle.

### 6.5 Depth over breadth.

A small number of well-engineered flows is better than many half-built features.

### 6.6 Measured outcomes over screenshots.

The final product should show real test/synthetic batch results generated by the system.

### 6.7 Safe failure over clever failure

When input is malformed, incomplete, duplicated, stale, or unavailable, ARC should fail safely and explain why.

---

## 7. Target Users

### Primary user

A merchant finance, payments, or revenue-operations team that wants to understand and recover revenue lost through payment and subscription failures.

### Secondary user

A merchant operator or manager responsible for approving high-risk/high-value recovery actions and reviewing unresolved cases.

### Reviewer / audit user

A technical or operations reviewer who wants to inspect why ARC made a decision and whether the process was safe.

---

## 8. Primary User Experience

ARC should feel like a financial operations console.

The main product experience is **not** a chatbot.

### 8.1 Revenue Control Dashboard

The home screen should prioritize operational metrics such as:

- Revenue Evaluated
- Revenue at Risk
- Recovery Attempted
- Revenue Recovered
- Recovery Rate
- Under Recovery
- Awaiting Customer
- Escalated
- Duplicate Actions Prevented
- Premature Actions Prevented
- Unresolved Cases

### 8.2 Recovery Case Table

Suggested columns:

- Case ID
- Amount
- Payment / Subscription Reference
- Diagnosis
- Recommended Action
- Policy Result
- Current State
- Recovery Outcome

### 8.3 Case Detail View

Each case should expose a decision timeline such as:

```text
Event received
Signature verified
Event persisted
State reconciled
Failure classified
Strategy generated
Policy evaluated
Action authorized/rejected
Action executed
Outcome received
Revenue attributed
```

A case should clearly answer:

- **Why this action was chosen**
- **Why another action was not chosen**
- **What policy controlled the decision**
- **Whether the action actually worked**

### 8.4 Approval View

High-value or policy-sensitive cases should be able to move to a human approval queue.

The approver should see:

- amount at risk;
- failure diagnosis;
- recommended action;
- rationale;
- relevant merchant policy;
- risk/approval requirement;
- approve / reject outcome;
- audit history.

---

## 9. System Architecture

Target architecture:

```text
Razorpay Test Mode
        |
        v
Webhook Gateway
        |
        v
Immutable Event Ledger
        |
        v
State Reconciler
        |
        v
Eligibility / Preconditions Gate
        |
        v
Failure Intelligence
        |
        v
AI Strategy Engine
        |
        v
Deterministic Policy & Authorization Gate
        |
        v
Action Executor
        |
        v
Outcome Observer
        |
        v
Recovery Attribution + Audit
```

---

## 10. Component Responsibilities

### 10.1 Webhook Gateway

Responsibilities:

- receive Razorpay webhook events;
- preserve raw request body;
- verify authenticity;
- capture the event identifier;
- reject invalid requests;
- forward only accepted events to persistence.

### 10.2 Immutable Event Ledger

Responsibilities:

- store accepted external events before processing;
- support event-level idempotency;
- preserve raw and parsed payloads;
- track processing status;
- preserve processing errors;
- provide a durable audit record.

### 10.3 State Reconciler

Responsibilities:

- determine the current business truth;
- match events to the correct recovery case;
- prevent state regression;
- resolve already-paid cases;
- ignore stale state transitions;
- protect against out-of-order events.

### 10.4 Eligibility / Preconditions Gate

Determines whether ARC should consider recovery.

Examples:

- payment already captured -> `NO_ACTION`;
- duplicate event -> no new processing;
- subscription retry still active -> `WAIT`;
- insufficient context -> manual review;
- stale event -> no regression;
- invalid state -> no action.

### 10.5 Failure Intelligence

Interprets structured failure context.

Relevant signals may include:

- `error_code`
- `error_description`
- `error_source`
- `error_step`
- `error_reason`

Failure classification should use explicit reason codes/categories instead of free-form text wherever possible.

### 10.6 AI Strategy Engine

The AI strategy engine reasons about the next-best recovery action within a bounded action set.

It may consider:

- amount;
- payment method;
- failure reason/source/step;
- retry history;
- subscription state;
- prior recovery history;
- time since failure;
- merchant policy context;
- customer/payment history when available.

The AI output must be structured and validated.

### 10.7 Deterministic Policy & Authorization Gate

Validates the proposed action against merchant controls.

Examples:

- action allowlist;
- automation enabled/disabled;
- attempt limit;
- customer-contact limit;
- high-value threshold;
- approval threshold;
- recovery time window;
- already-paid protection;
- stopping rules;
- duplicate-action protection.

### 10.8 Action Executor

Executes only actions authorized by policy.

Possible actions include:

- wait;
- request a retry path;
- create a recovery payment path/link;
- request a payment-method update;
- escalate to a human.

### 10.9 Outcome Observer

Monitors what happened after the action.

Possible outcomes:

- payment captured;
- payment still pending;
- payment failed again;
- customer action required;
- action exhausted;
- case escalated;
- intervention cancelled because payment succeeded independently.

### 10.10 Recovery Attribution + Audit

Records whether the recovery sequence produced a successful outcome and how much revenue was recovered.

The system must distinguish test-mode/synthetic results from real-world revenue.

---

## 11. Recovery Case Lifecycle

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
   +----------+-----------+
   |          |           |
   v          v           v
RECOVERED  EXHAUSTED   ESCALATED
```

Not every case must pass through every state, but invalid backwards transitions must be blocked.

Examples:

- a captured case cannot return to a failed state because a stale event arrives later;
- a duplicate event cannot create a second recovery case;
- a pending recovery can be cancelled if payment succeeds before execution;
- high-value action can transition to escalation instead of automatic execution.

---

## 12. Bounded Recovery Actions

Initial action vocabulary:

- `NO_ACTION`
- `WAIT`
- `REQUEST_RETRY`
- `CREATE_RECOVERY_LINK`
- `REQUEST_PAYMENT_METHOD_UPDATE`
- `ESCALATE_TO_HUMAN`

The AI should not invent arbitrary actions outside this list.

Example strategy output:

```json
{
  "action": "WAIT",
  "reason_code": "PLATFORM_RETRY_ACTIVE",
  "explanation": "An existing retry flow is still active, so ARC should not create a competing recovery path.",
  "confidence": 0.94,
  "requires_human_approval": false,
  "re_evaluate_after_seconds": 120
}
```

The exact schema may evolve during implementation, but output must remain structured, bounded, and policy-validatable.

---

## 13. Initial Razorpay Event Scope

Initial scope is intentionally narrow.

Supported event types:

- `payment.failed`
- `payment.captured`
- `subscription.pending`
- `subscription.halted`

### `payment.failed`

Expected ARC behavior:

- store event;
- reconcile case state;
- capture failure metadata;
- classify failure;
- determine recovery eligibility;
- produce a rule/AI decision depending on phase.

### `payment.captured`

Expected ARC behavior:

- reconcile to successful payment truth;
- stop/cancel unnecessary recovery;
- resolve the case safely;
- avoid state regression from later stale failures.

### `subscription.pending`

Expected ARC behavior:

- recognize that an existing platform retry may still be active;
- default toward `WAIT` / observation;
- avoid competing recovery unless justified later.

### `subscription.halted`

Expected ARC behavior:

- recognize retry exhaustion;
- classify the case as potentially recovery eligible;
- allow a new recovery strategy or human escalation.

### Unknown valid event

Expected ARC behavior:

- persist safely;
- mark unsupported;
- do not crash;
- do not create unsafe financial actions.

---

## 14. Financial Safety Requirements

The following are mandatory system invariants:

- Never trust webhook arrival order as transaction order.
- Never execute the same recovery action twice because of duplicate delivery.
- Store accepted events before business processing.
- Preserve raw events and case history for auditability.
- Verify webhook signatures using the raw request body.
- Use the Razorpay event identifier for idempotency.
- Back event idempotency with a database uniqueness constraint.
- Never regress an already-captured payment back to failed.
- Stop pending recovery when payment is confirmed successful.
- AI output must be validated and rejectable.
- Policy enforcement must remain deterministic.
- High-risk/high-value actions must support human approval.
- Unknown or malformed inputs must fail safely.
- Processing exceptions must not destroy event history.
- Do not expose unrestricted arbitrary tools to the LLM.
- Never commit secrets or real sensitive payment/customer data.
- Never present test-mode or synthetic metrics as real merchant revenue.

---

## 15. Persistence Model

The initial persistent domain model consists of five core concepts.

### 15.1 `webhook_events`

Purpose: external event ledger.

Suggested fields:

- `id`
- `razorpay_event_id` — unique
- `event_type`
- `account_id`
- `payload_json`
- raw payload representation if needed
- `signature_verified`
- `received_at`
- `processing_status`
- `processed_at`
- `processing_error`

### 15.2 `payment_cases`

Purpose: current recovery-case state.

Suggested fields:

- `id`
- `case_reference`
- `payment_id`
- `subscription_id`
- `customer_id`
- `amount`
- `currency`
- `current_state`
- `failure_code`
- `failure_source`
- `failure_step`
- `failure_reason`
- `attempt_count`
- `detected_at`
- `last_reconciled_at`
- `resolved_at`
- `created_at`
- `updated_at`

### 15.3 `case_events`

Purpose: append-only internal case timeline.

Possible event types:

- `CASE_DETECTED`
- `STATE_RECONCILED`
- `FAILURE_DIAGNOSED`
- `ACTION_ELIGIBLE`
- `DECISION_CREATED`
- `POLICY_APPROVED`
- `POLICY_REJECTED`
- `ACTION_EXECUTED`
- `ACTION_CANCELLED`
- `OUTCOME_OBSERVED`
- `CASE_RECOVERED`
- `CASE_ESCALATED`
- `CASE_EXHAUSTED`

### 15.4 `decisions`

Purpose: preserve every decision independently from current state.

Suggested fields:

- `id`
- `case_id`
- `decision_type`
- `decision_source`
- `reason_code`
- `explanation`
- `confidence`
- `policy_result`
- `created_at`

Decision source should support:

- `RULE`
- `AI`
- `AI_WITH_OVERRIDE`
- `HUMAN`

### 15.5 `merchant_policies`

Purpose: deterministic recovery constraints.

Suggested fields:

- `id`
- `merchant_id`
- `automation_enabled`
- `allowed_actions`
- `max_automated_attempts`
- `max_contact_attempts`
- `recovery_window_minutes`
- `high_value_threshold`
- `require_approval_above`
- stopping-rule configuration
- `created_at`
- `updated_at`

Additional tables should be introduced only when a concrete domain requirement appears.

---

## 16. Technology Baseline

### Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- PostgreSQL
- Alembic
- httpx
- pytest

### Local / Dev Infrastructure

- Docker Compose
- GitHub Actions

### Frontend

Planned from Day 2:

- React + Vite unless a clear implementation constraint justifies another lightweight approach.

### AI

- OpenAI API
- structured output/schema validation where suitable
- bounded action vocabulary
- deterministic fallback and policy enforcement

### Explicitly Avoid Unless Needed

- Kafka
- Redis
- Celery
- Kubernetes
- vector databases
- LangChain or large agent frameworks
- unnecessary microservices
- distributed infrastructure added only for appearance.

---

## 17. Repository Structure Direction

```text
arc-revenue-control/
|
|-- AGENTS.md
|-- README.md
|-- pyproject.toml
|-- docker-compose.yml
|-- .env.example
|-- .gitignore
|
|-- apps/
|   `-- web/
|
|-- services/
|   `-- api/
|
|-- arc/
|   |-- domain/
|   |-- ingestion/
|   |-- reconciliation/
|   |-- diagnosis/
|   |-- policy/
|   |-- intelligence/
|   |-- execution/
|   `-- audit/
|
|-- integrations/
|   `-- razorpay/
|
|-- evaluation/
|   |-- scenarios/
|   |-- synthetic_generator.py
|   |-- batch_runner.py
|   `-- results/
|
|-- tests/
|   |-- unit/
|   |-- integration/
|   `-- fixtures/
|
|-- migrations/
|
|-- docs/
|   |-- PROJECT.md
|   |-- architecture.md
|   |-- build-log.md
|   |-- threat-model.md
|   `-- decisions/
|
`-- .github/
    `-- workflows/
        `-- ci.yml
```

This structure may evolve during implementation, but architectural boundaries should remain clear.

---

## 18. Day 1 — Financial Core

### Goal

Build the trusted financial/event foundation before any AI or dashboard work.

### End-to-End Milestone

```text
Webhook
  -> persisted event
  -> idempotency
  -> recovery case
  -> reconciliation
  -> diagnosis
  -> deterministic policy decision
  -> audit trail
```

### Required Day 1 Capabilities

- FastAPI service starts locally.
- PostgreSQL persistence available.
- Alembic migrations succeed.
- Razorpay webhook endpoint exists.
- Raw request body retained.
- Signature verification works.
- Accepted events persisted before processing.
- Duplicate events are idempotent.
- Event ledger remains auditable.
- Recovery cases modeled explicitly.
- State reconciliation blocks stale regression.
- Deterministic failure classification exists.
- Merchant policy model exists.
- Case events form an audit timeline.
- Critical tests exist.
- CI runs the test suite.

### Day 1 Acceptance Scenarios

1. Valid signed webhook is accepted and persisted.
2. Invalid signature is rejected without changing financial state.
3. Duplicate event id does not create duplicate processing.
4. `payment.failed` creates/updates the correct case.
5. Failure metadata is captured.
6. `payment.captured` resolves the correct case.
7. Out-of-order failed event cannot regress captured state.
8. `subscription.pending` produces safe wait/observe behavior.
9. `subscription.halted` becomes recovery eligible.
10. Unknown valid events persist safely.
11. Database uniqueness protects concurrent duplicate ingestion.

### Day 1 Non-Goals

Do not add:

- frontend;
- chatbot;
- OpenAI API integration;
- Payment Link execution;
- customer messaging;
- voice automation;
- unnecessary infrastructure.

---

## 19. Day 2 — Autonomous Recovery

### Goal

Add bounded AI strategy, deterministic authorization, safe execution, outcome observation, recovery attribution, and the operational UI.

### Target Flow

```text
Failure
  -> Reconcile
  -> Diagnose
  -> AI Strategy
  -> Policy Authorization
  -> Action
  -> Outcome
  -> Recovery detected
  -> Revenue attributed
```

### Required Day 2 Capabilities

- OpenAI-powered strategy engine;
- structured model output;
- bounded action allowlist;
- deterministic policy validator;
- clear policy approval/rejection reasons;
- recovery Payment Link path in Razorpay Test Mode where appropriate;
- human approval workflow;
- duplicate action protection;
- execution audit entries;
- outcome listener;
- recovery attribution;
- case-level decision trace;
- finance-operations dashboard;
- key recovery metrics;
- graceful AI timeout handling;
- graceful malformed model-output handling;
- no unrestricted AI financial actions.

### Day 2 Demo Scenarios

1. Failed payment -> strategy -> policy approval -> recovery action -> payment captured -> recovered revenue attributed.
2. Subscription pending -> `WAIT`; no competing recovery.
3. Subscription halted -> recovery strategy proposed.
4. High-value case -> human approval required.
5. Malformed AI output -> safe rejection/fallback.
6. AI timeout -> safe fallback/escalation.

---

## 20. Day 3 — Break, Measure, Polish, Submit

### Goal

Prove reliability, measure results, document genuine engineering challenges, and finalize the submission.

### Deliberate Failure Tests

- duplicate webhook;
- out-of-order webhook;
- stale failure after capture;
- malformed AI output;
- LLM timeout;
- Razorpay API failure;
- duplicate action request;
- high-value action;
- retry exhaustion;
- missing customer information;
- unknown event type;
- processing failure after persistence.

### Day 3 Work

- run adversarial scenarios;
- fix real defects;
- document actual failures and fixes;
- run batch evaluation;
- finalize metrics;
- complete README;
- complete architecture documentation;
- complete threat model;
- prepare screenshots;
- stabilize deployment;
- record 5-minute pitch video;
- complete application answers accurately.

---

## 21. Batch Evaluation Strategy

The final system should demonstrate results across a batch, not a cherry-picked transaction.

Target batch size:

**Approximately 100–250 synthetic/test-mode cases**, depending on implementation time and performance.

### Scenario Mix

- UPI failures;
- card authentication failures;
- insufficient funds;
- issuer failures;
- gateway failures;
- subscription pending;
- subscription halted;
- repeated failures;
- already-recovered transactions;
- high-value payments;
- duplicate events;
- out-of-order events;
- late successful payments;
- missing/incomplete context.

### Evaluation Metrics

Candidate metrics:

- Cases Evaluated
- Revenue Evaluated
- Revenue Classified at Risk
- Recovery Workflows Initiated
- Wait / No-Action Decisions
- Human Escalations
- Duplicate Actions Prevented
- Premature Actions Prevented
- Cases Recovered
- Revenue Recovered
- Recovery Rate
- Unresolved Cases
- Policy Violations Executed
- Model Failures / Fallbacks

The system must generate the final values from the evaluation run.

No fabricated numbers.

---

## 22. Critical Final Demo Scenarios

### Scenario A — Successful Recovery

```text
payment.failed
  -> event stored
  -> state reconciled
  -> failure diagnosed
  -> recovery strategy proposed
  -> policy approves
  -> recovery path created
  -> outcome webhook received
  -> payment captured
  -> case RECOVERED
  -> recovered amount attributed
```

### Scenario B — Duplicate Webhook

```text
same event delivered twice
  -> first event processed
  -> second identified as duplicate
  -> no duplicate case
  -> no duplicate recovery action
  -> audit shows protection
```

### Scenario C — Failure Followed by Capture

```text
payment.failed
  -> case detected/reconciled
payment.captured later
  -> pending intervention cancelled/stopped
  -> case resolved
  -> unnecessary recovery avoided
```

### Scenario D — High-Value Human Approval

```text
high-value revenue at risk
  -> strategy generated
  -> deterministic policy requires approval
  -> action blocked from automatic execution
  -> human approval/rejection recorded
```

These four scenarios are more important than building a long feature list.

---

## 23. AI Usage Strategy

The system should make it obvious where AI is useful and where AI is deliberately excluded.

### Deterministic Software Owns

- signature validation;
- event idempotency;
- financial-state reconciliation;
- transition validity;
- already-paid protection;
- duplicate-action prevention;
- action allowlisting;
- monetary thresholds;
- approval rules;
- attempt/contact limits;
- stopping rules;
- final authorization.

### AI Owns

- synthesizing structured failure context;
- ranking next-best recovery strategies;
- deciding among a bounded action vocabulary;
- producing an explainable recommendation;
- considering recovery/customer context when available.

### AI Must Not Own

- truth about whether a payment is paid;
- unrestricted financial API access;
- bypassing merchant policy;
- overriding approval thresholds silently;
- arbitrary tool choice.

---

## 24. Failure-Recovery Strategy

Failure recovery is a first-class product feature.

The system should fail safely when:

- webhook signature is invalid;
- event is duplicated;
- event is stale;
- events arrive out of order;
- model output is invalid;
- model request times out;
- Razorpay API fails;
- action execution is retried;
- payment succeeds before recovery execution;
- required context is missing;
- database conflict occurs;
- unsupported event is received.

Every meaningful failure should be reflected in the audit trail.

---

## 25. Threat and Safety Considerations

The project should treat the following as important security/safety areas:

- webhook authenticity;
- replay/duplicate protection;
- idempotent action execution;
- secret management;
- least-privilege API use;
- validation of model output;
- prevention of arbitrary action/tool invocation;
- approval rules for high-value cases;
- auditability;
- test data isolation;
- prevention of false claims about real recovered revenue.

A dedicated `docs/threat-model.md` should be completed before submission.

---

## 26. Explicit Non-Goals

ARC should not expand into a broad fintech platform during the buildathon.

Unless the core is complete and there is a compelling reason, do not add:

- generic chatbot;
- CRM;
- fraud-detection suite;
- chargeback platform;
- finance reconciliation system;
- voice-recovery agent;
- WhatsApp campaign engine;
- marketing automation;
- multiple hackathon tracks;
- vector-search/RAG for appearance only;
- many AI agents when one bounded strategy engine is sufficient;
- infrastructure that does not improve judging criteria.

Depth over breadth.

---

## 27. Submission Requirements

The buildathon application requires:

- Project Name / Title
- Project Objectives
- What does it solve?
- GitHub Repository URL
- 5-min Pitch Video Link
- Build Challenges & Technical Obstacles
- What issues were faced while building and how they were solved

The repository and documentation should make each answer easy to support truthfully.

### Project Name / Title

**ARC — Autonomous Revenue Control**

Subtitle:

**Policy-Governed AI Revenue Recovery for Razorpay Merchants**

### Project Objectives — Working Draft

ARC is an event-driven revenue recovery control plane designed to help merchants recover revenue lost after payment and subscription failures. It consumes Razorpay payment events, reconciles the true transaction state, diagnoses revenue risk, selects a next-best recovery action using deterministic logic plus bounded AI decisioning, validates that action against merchant policies, executes only authorized actions, observes outcomes, and measures recovered revenue.

The objective is to safely close the recovery loop while preventing duplicate or premature actions, enforcing approval and stopping rules, maintaining an explainable audit trail, and measuring outcomes across a batch rather than a single demo case.

The final wording must be updated if implementation differs.

### What Does It Solve? — Working Draft

ARC solves the decision gap between a payment failure and a safe recovery action. Payment failures may later resolve, may already be in a platform retry flow, or may require different interventions depending on context. ARC reconciles current state before acting, interprets failure context, selects a bounded strategy, enforces merchant policies, executes approved actions, stops when payment is already successful, and tracks whether revenue was actually recovered.

The final wording must match the implemented system.

### GitHub Repository

`https://github.com/samarthpatilofficial/arc-revenue-control`

### Pitch Video

To be produced after the product, evaluation, and demo are complete.

### Build Challenges & Technical Obstacles

Do not prewrite fake challenges.

Maintain `docs/build-log.md` during implementation with:

- what broke;
- symptoms;
- root cause;
- attempted fixes;
- final fix;
- verification/tests;
- remaining limitations.

Only genuine issues should appear in the final application.

---

## 28. Five-Minute Pitch Video Plan

The video should be product-led, not slide-led.

### 0:00–0:35 — Problem

Explain that a failed payment is not automatically lost revenue and that blindly retrying or contacting the customer can create duplicate or unsafe recovery actions.

### 0:35–1:10 — ARC Architecture

Explain:

```text
Detect -> Reconcile -> Diagnose -> Decide -> Authorize -> Execute -> Measure
```

Emphasize:

**AI proposes. Policy authorizes.**

### 1:10–3:25 — Live Demo

Show working flows:

1. failed payment -> recovery -> success;
2. duplicate webhook -> blocked;
3. failed then captured -> intervention cancelled;
4. high-value case -> human approval.

### 3:25–4:15 — Batch Evaluation

Show the actual batch run and generated test-mode/synthetic metrics.

### 4:15–4:45 — AI Judgment and Safety

Show a decision trace and explain why the model cannot perform arbitrary financial actions.

### 4:45–5:00 — Close

Core message:

> **ARC does not automate payment chasing. It gives merchants a controlled system for deciding when revenue recovery should happen — and proving when it worked.**

---

## 29. Definition of Done

### Day 1 Done

The following works end to end with tests:

```text
Webhook -> persisted event -> idempotency -> case -> reconciliation -> diagnosis -> deterministic policy decision -> audit trail
```

### Day 2 Done

The following works end to end in Razorpay Test Mode or clearly labeled controlled simulation where an external limitation exists:

```text
Failure -> reconciliation -> bounded AI strategy -> deterministic policy authorization -> action -> outcome -> recovery attribution -> audit
```

The dashboard shows real system state and decision traces.

### Day 3 Done

- critical adversarial scenarios tested;
- genuine defects fixed and documented;
- batch evaluation completed;
- metrics generated from actual results;
- README completed;
- architecture docs completed;
- threat model completed;
- application answers aligned with implementation;
- deployment stable enough for review;
- 5-minute pitch video recorded;
- no secrets or fabricated claims in repository.

---

## 30. Final Product Standard

The final ARC submission should convince an experienced reviewer that:

- the problem was chosen thoughtfully;
- the architecture respects financial-system safety;
- the project does not use AI where deterministic controls are better;
- the AI is bounded, explainable, and policy-governed;
- duplicate and out-of-order events are handled correctly;
- the system can stop unsafe or unnecessary recovery;
- failures are visible rather than hidden;
- the product produces measurable recovery outcomes;
- the repository is structured, tested, and documented;
- the team understood that **revenue recovery is a control problem, not just a messaging problem**.

The goal is not maximum feature count.

The goal is a **working, measurable, explainable, safe revenue-recovery system that feels credible as a serious fintech prototype.**