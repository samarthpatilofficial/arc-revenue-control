# AGENTS.md

## 1. Project Identity

**Project:** ARC — Autonomous Revenue Control  
**Subtitle:** Policy-Governed AI Revenue Recovery for Razorpay Merchants  
**Hackathon:** Razorpay AI Buildathon  
**Track:** Track 03 — AI Revenue Recovery  
**Repository:** `https://github.com/samarthpatilofficial/arc-revenue-control`

This project direction is **locked unless the project owner explicitly changes it**.

ARC is not a reminder bot, generic failed-payment dashboard, chatbot, CRM, or thin LLM wrapper. ARC is an event-driven, policy-governed revenue-recovery control plane that determines whether revenue is genuinely at risk, reconciles the current payment state, diagnoses failure context, recommends the safest next action, enforces deterministic financial policies, executes only authorized actions, observes outcomes, and measures recovered revenue.

Primary recovery loop:

`detect -> reconcile -> diagnose -> decide -> authorize -> execute -> observe -> measure`

The product must feel like credible fintech infrastructure built by an experienced engineering team, not a student demo.

---

## 2. Product Objective

ARC is designed to help merchants recover revenue lost after payment and subscription failures without blindly retrying payments, repeatedly contacting customers, or allowing an AI model to perform unrestricted financial actions.

The objective is not merely to detect a failed payment. The objective is to safely close the recovery loop:

`detect -> reconcile -> diagnose -> decide -> authorize -> execute -> observe -> measure`

ARC has five primary engineering objectives:

1. Prevent duplicate, stale, or premature recovery actions.
2. Select context-aware recovery interventions.
3. Enforce merchant-defined limits, stopping rules, and human approval gates.
4. Maintain a complete, explainable decision and action audit trail.
5. Quantitatively measure revenue recovery across a realistic batch of test/synthetic cases.

---

## 3. Problem ARC Solves

A failed payment is not automatically lost revenue.

A transaction can fail and then succeed moments later. A subscription may already be in an existing platform retry cycle. The customer may need to update a payment method. Repeated retries may be inappropriate. A duplicate webhook may arrive. Events may arrive out of order. A high-value recovery action may require human approval.

The real problem is therefore **revenue recovery decisioning**:

- Is this revenue truly at risk?
- What is the current transaction truth?
- Why did the payment fail?
- Should ARC intervene at all?
- What is the next-best recovery action?
- Is that action permitted by merchant policy?
- When should automation stop?
- Did ARC actually recover the money?

ARC converts fragmented payment events into managed recovery cases and gives merchants a controlled, auditable recovery workflow.

Expected product value:

- fewer unnecessary customer contacts;
- fewer duplicate recovery attempts;
- fewer missed recoverable payments;
- lower manual finance-operations effort;
- safer use of AI in money-related workflows;
- explainable decisions;
- measurable recovered revenue.

---

## 4. Engineering Standard

Treat this repository as financial infrastructure.

Priorities, in order:

1. Correctness and safety.
2. Deterministic financial controls.
3. Idempotency and state integrity.
4. Auditability and explainability.
5. Failure recovery.
6. Clear domain boundaries.
7. Measured business outcomes.
8. Production-like repository quality.
9. UI polish only after the core is reliable.

Prefer a smaller system that is correct, testable, and demonstrable over a larger system with superficial features.

Do not add complexity merely to make the architecture look sophisticated.

---

## 5. Core Architectural Principle

**AI proposes. Policy authorizes. The executor acts.**

An LLM must never directly perform unrestricted financial actions.

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

### 5.1 Webhook Gateway

Responsibilities:

- accept Razorpay webhook events;
- retain the raw body for signature verification;
- verify webhook authenticity;
- obtain the Razorpay event identifier;
- reject invalid signatures;
- pass valid events to durable persistence.

### 5.2 Immutable Event Ledger

Responsibilities:

- preserve accepted external events before business processing;
- support idempotency;
- retain payload and processing metadata;
- provide an auditable history;
- preserve failures instead of losing the original event.

### 5.3 State Reconciler

Responsibilities:

- determine current business truth;
- prevent stale or out-of-order events from regressing state;
- resolve already-paid/captured cases;
- ensure action decisions use current state rather than webhook arrival order.

### 5.4 Eligibility / Preconditions Gate

Asks whether ARC should even consider intervention.

Examples:

- already captured -> no recovery action;
- duplicate event -> no new processing;
- stale event -> no state regression;
- platform retry still active -> wait/observe;
- incomplete context -> manual review or safe hold.

### 5.5 Failure Intelligence

Interprets structured failure context using deterministic logic first.

Relevant fields may include:

- `error_code`
- `error_description`
- `error_source`
- `error_step`
- `error_reason`

The classifier should produce explicit reason codes and categories rather than vague natural-language labels.

### 5.6 AI Strategy Engine

The AI layer is used for contextual strategy, not state truth or safety enforcement.

It receives bounded context such as:

- amount;
- payment method;
- failure source/step/reason;
- number of attempts;
- previous payment history when available;
- subscription state;
- recovery history;
- time since failure;
- merchant policy constraints.

It must return a structured response that can be validated.

### 5.7 Deterministic Policy & Authorization Gate

Validates an AI/rule/human proposal against explicit policy.

Examples:

- action allowlist;
- automation enabled/disabled;
- maximum automated attempts;
- maximum contact attempts;
- recovery window;
- high-value threshold;
- approval requirement;
- stopping rules;
- already-paid protection;
- duplicate-action protection.

### 5.8 Action Executor

Executes only approved actions.

It must not accept arbitrary tool instructions directly from an LLM.

### 5.9 Outcome Observer

Observes what happened after an action:

- payment captured;
- recovery still pending;
- payment failed again;
- case exhausted;
- case escalated;
- action cancelled because the underlying payment succeeded.

### 5.10 Recovery Attribution + Audit

ARC must be able to answer:

- what happened;
- why ARC made a decision;
- which policy allowed or blocked it;
- what action was attempted;
- whether money was recovered;
- how much was recovered;
- what could not be resolved.

---

## 6. Financial Safety Invariants

These are non-negotiable unless explicitly changed by the project owner:

- Never assume webhook arrival order equals transaction-state order.
- Never execute the same recovery action twice because of duplicate delivery.
- Persist accepted external events before business processing.
- Preserve raw external events and internal case history for auditability.
- Verify Razorpay webhook signatures using the raw request body.
- Use the Razorpay event identifier for idempotency and back it with a database uniqueness constraint.
- A captured/paid state must not be regressed by a later-arriving failed event.
- Stop or cancel pending recovery when the underlying payment is confirmed successful.
- AI output must be structured, bounded, validated, and rejectable.
- Policy enforcement must be deterministic and testable.
- High-risk or high-value actions must be able to require human approval.
- Unknown or malformed events must fail safely.
- A processing exception must not destroy the original event.
- Unknown event types must not crash the service.
- No unrestricted arbitrary tool execution from the model.
- Never commit credentials, API keys, webhook secrets, tokens, real customer-sensitive data, or production secrets.
- Synthetic/test-mode outcomes must never be presented as real merchant outcomes.

---

## 7. Recovery Case Lifecycle

Use explicit state transitions rather than arbitrary state assignments scattered through the code.

Current lifecycle:

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

Not every case needs to visit every state, but invalid backwards transitions must be prevented.

Important examples:

- `payment.failed` may create a case and lead to diagnosis;
- `payment.captured` should resolve a corresponding case;
- a stale failure after capture must not move the case backward;
- an action awaiting payment moves to `WAITING_FOR_OUTCOME`;
- a successful payment after recovery moves to `RECOVERED`;
- retry exhaustion with no safe automatic recovery may become `ESCALATED` or `EXHAUSTED`.

---

## 8. Bounded Action Vocabulary

The AI strategy engine may recommend only from an explicit action allowlist.

Initial vocabulary:

- `NO_ACTION`
- `WAIT`
- `REQUEST_RETRY`
- `CREATE_RECOVERY_LINK`
- `REQUEST_PAYMENT_METHOD_UPDATE`
- `ESCALATE_TO_HUMAN`

Any expansion must be deliberate and accompanied by policy logic and tests.

Example structured decision shape:

```json
{
  "action": "WAIT",
  "reason_code": "PLATFORM_RETRY_ACTIVE",
  "explanation": "Existing retry flow is still active; ARC should not create a competing recovery action.",
  "confidence": 0.94,
  "requires_human_approval": false,
  "re_evaluate_after_seconds": 120
}
```

The exact schema may evolve, but the model output must remain structured and policy-validatable.

---

## 9. Initial Razorpay Scope

Do not integrate the entire Razorpay platform at once.

Initial webhook/event scope:

- `payment.failed`
- `payment.captured`
- `subscription.pending`
- `subscription.halted`

ARC must not claim to invent or replace retry behavior Razorpay already provides.

Expected behavior examples:

### `payment.failed`

- persist event;
- reconcile case state;
- capture structured failure metadata;
- classify failure;
- determine eligibility;
- create deterministic/AI decision depending on build phase.

### `payment.captured`

- reconcile to paid/captured truth;
- stop or cancel unnecessary recovery;
- resolve case safely.

### `subscription.pending`

- recognize that platform retry may still be active;
- default toward `WAIT`/observation unless evidence supports another safe path.

### `subscription.halted`

- recognize retry exhaustion;
- classify revenue as potentially recovery eligible;
- later allow an approved recovery strategy such as a fresh recovery checkout or human escalation.

Unknown but valid events should be persisted safely and marked unsupported rather than crashing the system.

---

## 10. Product Experience / Dashboard Direction

The final UI should feel like a financial operations console, not a chatbot.

The primary screen should communicate revenue state and recovery outcomes.

Candidate metrics:

- Revenue Evaluated
- Revenue at Risk
- Recovery Attempted
- Revenue Recovered
- Recovery Rate
- Awaiting Customer
- Under Recovery
- Escalated
- Duplicate Actions Prevented
- Premature Actions Prevented

Example case table columns:

- Case ID
- Amount
- Diagnosis
- Decision
- Policy Result
- State
- Recovery Outcome

A case detail view should show a **decision trace / audit timeline** such as:

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

The interface should expose **why an action was chosen** and **why an action was blocked**.

Do not make “chat with your revenue assistant” the core experience.

---

## 11. Core Persistence Model

Start with a small, understandable model.

### 11.1 `webhook_events`

Purpose: immutable/auditable external event receipt and processing state.

Preserve at minimum:

- internal id;
- `razorpay_event_id` with database uniqueness constraint;
- event type;
- account/reference metadata where available;
- raw/JSON payload;
- signature verification status;
- received timestamp;
- processing status;
- processed timestamp;
- processing error.

### 11.2 `payment_cases`

Purpose: current business state of a recovery case.

Preserve fields such as:

- id / case reference;
- payment id;
- subscription id;
- customer id;
- amount;
- currency;
- current lifecycle state;
- failure code;
- failure source;
- failure step;
- failure reason;
- attempt count;
- detected timestamp;
- last reconciled timestamp;
- resolved timestamp;
- created/updated timestamps.

### 11.3 `case_events`

Purpose: append-only internal audit timeline.

Example internal event types:

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

### 11.4 `decisions`

Persist decisions separately from current case state.

Preserve fields such as:

- case id;
- decision type;
- decision source;
- reason code;
- explanation;
- confidence when applicable;
- policy result;
- timestamp.

Decision source should distinguish at least:

- `RULE`
- `AI`
- `AI_WITH_OVERRIDE`
- `HUMAN`

### 11.5 `merchant_policies`

Store explicit deterministic automation constraints such as:

- merchant id;
- automation enabled;
- allowed actions;
- maximum automated attempts;
- maximum contact attempts;
- recovery window;
- high-value threshold;
- human approval threshold;
- stopping rules;
- created/updated timestamps.

Additional persistence models may be introduced later only when there is a clear domain need.

---

## 12. Technology Baseline

Unless a concrete constraint requires a justified change:

### Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- PostgreSQL
- Alembic
- httpx
- pytest

### Local / Infrastructure

- Docker Compose
- GitHub Actions

### Frontend

Day 2 onward:

- React + Vite is the default planned choice unless implementation constraints justify another lightweight option.

### AI

- OpenAI API using structured output / schema validation where suitable;
- model selection should favor reliability, latency, and cost appropriate to a three-day prototype;
- AI is not permitted to replace deterministic financial state reconciliation or policy enforcement.

### Deployment

Choose a pragmatic deployment path suitable for a hackathon prototype. Avoid infrastructure that consumes time without improving the judging criteria.

### Explicitly avoid unless a real need emerges

- Kafka
- Redis
- Celery
- Kubernetes
- vector databases
- LangChain / agent frameworks
- unnecessary microservices
- distributed architecture for appearance only.

---

## 13. Repository Structure Direction

Keep the repository easy to navigate.

Preferred structure:

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
|   |-- architecture.md
|   |-- build-log.md
|   |-- threat-model.md
|   `-- decisions/
|
`-- .github/
    `-- workflows/
        `-- ci.yml
```

The exact structure may evolve when justified, but preserve clear boundaries between domain logic, Razorpay integration, AI intelligence, policy, execution, audit, and evaluation.

---

## 14. Three-Day Build Plan

### DAY 1 — Financial Core

**Goal:** establish safe event ingestion, state integrity, deterministic diagnosis, policies, and auditability.

End-to-end milestone:

`Webhook -> persisted event -> idempotency -> case -> reconciliation -> diagnosis -> deterministic policy decision -> audit trail`

Required capabilities:

- FastAPI service starts locally;
- PostgreSQL persistence available;
- Alembic migrations succeed;
- Razorpay webhook endpoint exists;
- raw request body retained;
- signature verification works;
- accepted events persisted before business processing;
- duplicate events are idempotent;
- event ledger remains auditable;
- payment/recovery cases modeled explicitly;
- state reconciliation prevents stale or out-of-order regression;
- deterministic failure classification exists;
- merchant recovery policies represented explicitly;
- internal case events create an audit timeline;
- tests cover critical safety behavior;
- CI runs the test suite.

Day 1 acceptance behaviors:

1. Valid signed webhook accepted and persisted.
2. Invalid signature rejected without mutating financial state.
3. Duplicate event id does not trigger duplicate processing.
4. `payment.failed` creates/updates the correct case and captures failure metadata.
5. `payment.captured` resolves the corresponding case.
6. Late/out-of-order failed event cannot regress a captured case.
7. `subscription.pending` produces a safe wait/observe result while platform retry is active.
8. `subscription.halted` is recognized as retry exhaustion and can become recovery eligible.
9. Unknown but validly signed event is stored safely and marked unsupported.
10. Database uniqueness protects against concurrent duplicate ingestion.

Do not begin autonomous money-recovery execution before the Day 1 core is demonstrably correct.

### DAY 2 — Autonomous Recovery

**Goal:** add bounded AI strategy, policy authorization, safe execution, outcome observation, recovery attribution, and the core operator UI.

Target end-to-end flow:

```text
Failure
  -> Reconcile
  -> Diagnose
  -> AI Strategy
  -> Policy Authorization
  -> Action
  -> Outcome
  -> Recovery detected
  -> Recovered amount attributed
```

Required Day 2 capabilities:

- OpenAI-powered strategy engine with structured output;
- bounded action schema / allowlist;
- deterministic policy validator;
- policy approval/rejection reasons;
- Payment Link recovery path using Razorpay Test Mode where appropriate;
- human approval path for threshold/high-risk cases;
- action idempotency / duplicate action protection;
- action execution audit entries;
- outcome listener;
- recovery attribution;
- case-level decision trace;
- finance-operations dashboard;
- key recovery metrics;
- graceful handling of model timeout/malformed response;
- no unbounded financial tool access by the model.

Important Day 2 demo scenarios:

1. Failed payment -> diagnosed -> approved recovery action -> payment captured -> revenue attributed.
2. Subscription pending -> AI/policy chooses `WAIT`; no unnecessary action.
3. Subscription halted -> recovery strategy proposed -> policy authorizes or escalates.
4. High-value case -> strategy proposed -> human approval required.
5. AI malformed output -> safe rejection/fallback.
6. AI timeout -> safe deterministic fallback or escalation.

### DAY 3 — Break, Measure, Polish, Submit

**Goal:** prove reliability and depth rather than adding random features.

Deliberately test:

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
- unknown webhook event;
- processing failure after event persistence.

Day 3 work:

- run adversarial/failure scenarios;
- fix genuine defects;
- record real failures and fixes in `docs/build-log.md`;
- run batch evaluation;
- finalize metrics;
- complete README;
- complete architecture documentation;
- complete threat model;
- create screenshots;
- finalize deployment;
- record 5-minute pitch video;
- fill application form accurately.

Do not fabricate implementation obstacles. The final “Build Challenges & Technical Obstacles” answer must come from actual issues encountered during the build.

---

## 15. Batch Evaluation Strategy

Razorpay's Track 03 bar requires demonstrating measured recovered money across a batch, not one hand-picked transaction.

Create a realistic synthetic/test-mode batch, approximately 100–250 cases depending on implementation time.

Scenario mix should include combinations such as:

- UPI failures;
- card authentication failures;
- insufficient funds;
- issuer/gateway errors;
- subscription pending;
- subscription halted;
- repeated failures;
- already-recovered transactions;
- high-value payments;
- duplicate webhook events;
- out-of-order events;
- late successful payments;
- missing/incomplete context.

Evaluation should measure meaningful outcomes, for example:

- cases evaluated;
- revenue evaluated;
- revenue classified at risk;
- workflows initiated;
- waits/no-actions;
- human escalations;
- duplicate actions prevented;
- premature actions prevented;
- recovered cases;
- recovered revenue;
- recovery rate;
- unresolved cases;
- policy violations executed;
- model/fallback failures.

Do not hard-code impressive numbers into the product or documentation. Metrics must be generated from the implemented evaluation run.

Always label synthetic/test-mode data as synthetic/test-mode data.

---

## 16. Critical Demo Scenarios

The final live/demo flow should emphasize engineering judgment.

### Scenario A — Successful Recovery

```text
payment.failed
  -> ARC stores event
  -> state reconciled
  -> failure diagnosed
  -> recovery strategy proposed
  -> policy approves
  -> recovery payment flow created
  -> outcome webhook arrives
  -> payment captured
  -> case RECOVERED
  -> amount attributed to ARC
```

### Scenario B — Duplicate Webhook

```text
same event delivered twice
  -> first processed
  -> second recognized as duplicate
  -> no duplicate case/action
  -> audit shows idempotency protection
```

### Scenario C — Failed Then Captured

```text
payment.failed
  -> ARC holds/reconciles
payment.captured arrives later
  -> pending intervention cancelled/stopped
  -> case resolved
  -> no unnecessary customer action
```

### Scenario D — High-Value Human Approval

```text
high-value revenue at risk
  -> AI strategy generated
  -> deterministic policy requires approval
  -> action not executed automatically
  -> human approval/rejection recorded
```

These scenarios are more valuable than a long feature list.

---

## 17. AI Judgment Expectations

The project should visibly demonstrate where AI is used and where it is deliberately not used.

Use deterministic software for:

- signature validation;
- idempotency;
- state reconciliation;
- state transition validity;
- action allowlisting;
- monetary thresholds;
- approval rules;
- attempt/contact limits;
- already-paid protection;
- duplicate-action prevention;
- stopping rules;
- final authorization.

Use AI for contextual reasoning such as:

- synthesizing failure context;
- ranking next-best recovery strategies;
- deciding between wait/retry/recovery-link/escalation within a bounded vocabulary;
- producing an explainable recommendation;
- considering customer/recovery history if available.

The AI layer must never be necessary for determining basic payment truth.

---

## 18. Failure Recovery Expectations

Failure recovery is a first-class judging dimension.

The system should fail safely when:

- webhook signature is invalid;
- event is duplicated;
- events arrive out of order;
- model response is invalid;
- model request times out;
- Razorpay API call fails;
- action execution is retried;
- a case becomes paid before action execution;
- required context is missing;
- an unknown event type is received;
- database conflicts occur during duplicate ingestion.

Each failure should produce a useful audit record and avoid unsafe financial action.

---

## 19. Documentation Expectations

Maintain documentation as the system evolves.

Expected files:

- `README.md` — concise external overview, architecture summary, setup, demo, evaluation, limitations.
- `docs/architecture.md` — architecture, boundaries, data flow, state machine.
- `docs/build-log.md` — actual implementation obstacles, root causes, fixes, lessons.
- `docs/threat-model.md` — security, abuse, AI safety, financial-safety considerations.
- `docs/decisions/` — ADRs for material architectural trade-offs.

Never fabricate:

- production readiness;
- merchant adoption;
- recovered real-world revenue;
- unsupported integrations;
- metrics;
- security certifications;
- build challenges.

---

## 20. Application Submission Fields

The final application requires the following. Keep implementation and documentation aligned so these can be answered truthfully and strongly.

### Project Name / Title

**ARC — Autonomous Revenue Control**

Suggested subtitle:

**Policy-Governed AI Revenue Recovery for Razorpay Merchants**

### Project Objectives

Working direction:

ARC is an event-driven revenue recovery control plane designed to help merchants recover revenue lost after payment and subscription failures. It consumes Razorpay payment events, reconciles the true transaction state, diagnoses revenue risk, selects a next-best recovery action using deterministic logic plus bounded AI decisioning, validates that action against merchant policies, executes only authorized actions, observes outcomes, and measures recovered revenue.

The objective is to safely close the recovery loop while preventing duplicate or premature actions, enforcing approval/stopping rules, maintaining an explainable audit trail, and measuring outcomes across a batch rather than a single demo case.

Do not copy this wording blindly if implementation changes; update it to match what was actually built.

### What Does It Solve?

Working direction:

ARC solves the decision gap between a payment failure and a safe recovery action. Payment failures may later resolve, may already be in a platform retry flow, or may require different interventions depending on context. ARC reconciles the current state before acting, interprets failure context, selects a bounded strategy, enforces merchant policies, executes approved actions, stops when payment is already successful, and tracks whether revenue was actually recovered.

Again, final submission wording must match implemented behavior.

### GitHub Repository URL

`https://github.com/samarthpatilofficial/arc-revenue-control`

The repository is currently private during development. Make any visibility change only when the owner explicitly decides to do so for submission.

### 5-Min Pitch Video Link

Not available yet. It will be produced after the working system, evaluation, and final demo are complete.

### Build Challenges & Technical Obstacles

Do not prewrite fake challenges.

During implementation, record actual issues in `docs/build-log.md`, including:

- what broke;
- symptoms;
- root cause;
- attempted fixes;
- final fix;
- verification/tests;
- trade-offs or remaining limitations.

Likely challenge categories may include webhook idempotency, event ordering, late capture, model reliability, API failure, action idempotency, recovery attribution, and batch evaluation, but only real encountered problems should appear in the final submission.

---

## 21. Five-Minute Pitch Video Plan

The final video should be product-led, not five minutes of slides.

Target structure:

### 0:00–0:35 — Problem

Explain that a failed payment is not automatically lost revenue and that blindly retrying/contacting customers can create duplicate or unsafe recovery actions.

### 0:35–1:10 — ARC Architecture

Explain the closed loop:

`Detect -> Reconcile -> Diagnose -> Decide -> Authorize -> Execute -> Measure`

Briefly emphasize:

**AI proposes. Policy authorizes.**

### 1:10–3:25 — Live Demo

Prioritize real working flows:

1. failed payment -> recovery -> success;
2. duplicate webhook blocked;
3. failed then captured -> unnecessary intervention cancelled;
4. high-value case -> human approval.

### 3:25–4:15 — Batch Evaluation

Show the real batch run and measured test-mode/synthetic metrics.

### 4:15–4:45 — AI Judgment + Safety

Show a decision trace and explain why the LLM cannot directly perform arbitrary financial actions.

### 4:45–5:00 — Close

Core message:

**ARC does not automate payment chasing. It gives merchants a controlled system for deciding when revenue recovery should happen — and proving when it worked.**

---

## 22. Explicit Non-Goals

Do not turn ARC into a broad fintech platform during the buildathon.

Unless core scope is complete and there is a compelling reason, do not add:

- generic chatbot;
- CRM;
- fraud-detection platform;
- voice agent;
- WhatsApp automation;
- marketing campaign engine;
- chargeback management;
- finance reconciliation suite;
- multi-track hackathon features;
- vector-search/RAG for appearance only;
- multiple AI agents where one bounded strategy service is sufficient;
- complex infrastructure without demonstrated need.

Depth over breadth.

---

## 23. Build Quality Expectations

Before calling any task complete:

- run relevant tests;
- run formatting/linting/type checks if configured;
- inspect the diff;
- ensure no secrets are present;
- ensure public interfaces remain understandable;
- ensure event/state behavior is deterministic where required;
- update documentation when architecture changes;
- record genuine build failures in the build log;
- report known limitations instead of hiding them.

Prefer meaningful incremental commits over one giant final commit.

Commit messages should explain the engineering change, not generic messages such as `update`, `changes`, or `final`.

---

## 24. Working With Codex

For every implementation task:

1. Read this file first.
2. Inspect existing code and documentation before creating new abstractions.
3. Respect the current day/milestone; do not jump ahead unless explicitly instructed.
4. Make the smallest coherent change that satisfies the milestone.
5. Do not silently redesign the product or broaden scope.
6. If a requested change conflicts with a financial-safety invariant, stop and explain the conflict.
7. If Razorpay/OpenAI behavior is uncertain, do not invent API behavior; flag it for verification against current official documentation.
8. Keep state truth and policy enforcement deterministic.
9. Use AI only for bounded contextual strategy.
10. Add/update tests with behavior changes.
11. Record real implementation obstacles when they happen.
12. At task completion, report:
    - files changed;
    - architecture decisions;
    - commands run;
    - tests run/results;
    - assumptions;
    - known limitations;
    - failures encountered and how they were fixed;
    - unresolved issues.

Do not claim a test passed unless it was run.

Do not claim an integration works unless it was exercised.

---

## 25. Phase Definitions of Done

### Day 1 Done

The following works end to end with tests:

`Webhook -> persisted event -> idempotency -> case -> reconciliation -> diagnosis -> deterministic policy decision -> audit trail`

### Day 2 Done

The following works end to end in Razorpay Test Mode or clearly labeled controlled simulation where an external limitation exists:

`Failure -> reconciliation -> bounded AI strategy -> deterministic policy authorization -> action -> outcome -> recovery attribution -> audit`

The dashboard can show real system state and decision traces.

### Day 3 Done

- critical adversarial scenarios tested;
- real defects fixed and documented;
- batch evaluation completed;
- metrics generated from actual evaluation results;
- README and architecture docs complete;
- threat model complete;
- application answers match implemented behavior;
- demo deployment stable enough for review;
- 5-minute pitch video recorded;
- no secrets or fabricated claims in repository.

---

## 26. Final Product Standard

The final submission should demonstrate all four qualities emphasized by the buildathon:

### Problem Taste

ARC addresses the real decision gap between payment failure and safe recovery, rather than merely sending reminders after a failed transaction.

### Build Quality

The system runs, has clear architecture, tests critical flows, persists an audit trail, and handles financial state carefully.

### AI Judgment

AI is used where contextual reasoning adds value and deliberately excluded from state truth and deterministic authorization.

### Failure Recovery

The system demonstrates what happens when events are duplicated, reordered, delayed, malformed, rejected, or external services fail.

The goal is not maximum feature count. The goal is a convincing, working, measurable, safe revenue-recovery system that an experienced reviewer could trust as a serious prototype.