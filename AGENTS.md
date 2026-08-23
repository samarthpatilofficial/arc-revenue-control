# AGENTS.md

## Project

**ARC — Autonomous Revenue Control** is a policy-governed AI control plane for payment recovery, being built for the Razorpay AI Buildathon under **Track 03 — AI Revenue Recovery**.

ARC is not a reminder bot, chatbot, or generic failed-payment dashboard. Its purpose is to determine whether revenue is genuinely at risk, reconcile the current payment state, diagnose the failure context, recommend the safest next action, enforce deterministic merchant policies, execute only authorized recovery actions, and measure whether revenue was actually recovered.

Primary recovery loop:

`detect -> reconcile -> diagnose -> decide -> authorize -> execute -> observe -> measure`

## Engineering Standard

Treat this repository as financial infrastructure, not a student prototype.

Priorities, in order:

1. Correctness and safety.
2. Deterministic financial controls.
3. Auditability and explainability.
4. Failure handling and idempotency.
5. Clear domain boundaries.
6. Measured outcomes.
7. UI polish only after the core is reliable.

Prefer a smaller system that is correct and testable over a larger system with superficial features.

## Core Architectural Principle

**AI proposes. Policy authorizes. The executor acts.**

The intended architecture is:

`Razorpay Test Mode`
`-> Webhook Gateway`
`-> Immutable Event Ledger`
`-> State Reconciler`
`-> Eligibility / Preconditions Gate`
`-> Failure Intelligence`
`-> AI Strategy Engine`
`-> Deterministic Policy & Authorization Gate`
`-> Action Executor`
`-> Outcome Observer`
`-> Recovery Attribution + Audit`

Do not allow an LLM to directly perform unrestricted financial actions.

The eligibility/preconditions gate determines whether ARC should consider intervention at all. The authorization gate validates whether a proposed action is allowed under merchant policies, thresholds, retry/contact limits, approval requirements, and stopping rules.

## Financial Safety Invariants

These rules are non-negotiable unless the project specification is explicitly changed:

- Never assume webhook arrival order equals transaction-state order.
- Never execute the same recovery action twice because of duplicate delivery.
- Persist accepted external events before business processing.
- Preserve an auditable record of raw external events and internal case transitions.
- Verify Razorpay webhook signatures using the raw request body.
- Use the Razorpay event identifier for idempotency and back it with a database uniqueness constraint.
- A captured/paid state must not be regressed by a later-arriving failed event.
- Stop or cancel pending recovery when the underlying payment is confirmed successful.
- AI output must be structured, bounded, validated, and rejectable.
- Policy enforcement must be deterministic and testable.
- High-risk or high-value actions must be able to require human approval.
- Unknown or malformed events must fail safely and must not create unintended financial actions.
- Never commit credentials, API keys, webhook secrets, or customer-sensitive data.

## Recovery Case Lifecycle

Use explicit lifecycle transitions rather than arbitrary state assignments scattered through the code.

Current lifecycle:

- `DETECTED`
- `RECONCILING`
- `DIAGNOSED`
- `DECISIONED`
- `POLICY_VALIDATED`
- `ACTIONED`
- `WAITING_FOR_OUTCOME`
- `RECOVERED`
- `EXHAUSTED`
- `ESCALATED`

Not every workflow needs to visit every state, but invalid backwards transitions must be prevented.

## Bounded Action Vocabulary

When the AI strategy layer is introduced, it must recommend from an explicit allowlist rather than inventing arbitrary operations.

Initial action vocabulary:

- `NO_ACTION`
- `WAIT`
- `REQUEST_RETRY`
- `CREATE_RECOVERY_LINK`
- `REQUEST_PAYMENT_METHOD_UPDATE`
- `ESCALATE_TO_HUMAN`

Any expansion of this set should be deliberate and accompanied by policy rules and tests.

## Initial Razorpay Scope

Do not integrate the entire Razorpay platform at once.

Initial webhook/event scope:

- `payment.failed`
- `payment.captured`
- `subscription.pending`
- `subscription.halted`

For failed payments, preserve structured failure context where available, including:

- `error_code`
- `error_description`
- `error_source`
- `error_step`
- `error_reason`

ARC must not pretend to replace retry behavior that Razorpay already provides. For example, a subscription in a pending/retry state should generally lead ARC toward observation or waiting, while a halted/retry-exhausted state may become eligible for a separate recovery strategy.

## Day 1 Scope

Day 1 is the financial core only.

Target end-to-end milestone:

`Webhook -> ARC -> Case created/updated -> Reconciliation -> Diagnosis -> Deterministic policy decision`

Required Day 1 capabilities:

- FastAPI service starts locally.
- PostgreSQL persistence is available.
- Alembic migrations run successfully.
- Razorpay webhook endpoint exists.
- Raw request body is retained for signature verification.
- Signature verification works.
- Valid events are persisted before processing.
- Duplicate events are idempotent.
- Event ledger is append-oriented/auditable.
- Payment/recovery cases are modeled explicitly.
- State reconciliation prevents stale or out-of-order regressions.
- Deterministic failure classification exists.
- Merchant recovery policies are represented explicitly.
- Internal case events form an audit timeline.
- Tests cover the critical safety behaviors.
- CI runs the test suite.

Do **not** implement Day 2 features until the Day 1 acceptance criteria pass.

## Out of Scope for Day 1

Do not add these merely to make the repository appear sophisticated:

- frontend/dashboard
- chatbot
- OpenAI API integration
- Payment Link execution
- customer messaging
- voice agents
- Redis
- Kafka
- Celery
- Kubernetes
- vector databases
- LangChain or other agent frameworks
- unnecessary microservices

Use simple, explicit components first. Introduce infrastructure only when there is a demonstrated requirement.

## Technology Baseline

Unless a concrete implementation constraint requires a change:

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- PostgreSQL
- Alembic
- pytest
- httpx
- Docker Compose
- GitHub Actions

Prefer typed interfaces, explicit domain models, and testable pure functions for decision logic.

## Domain Persistence

Start with a small, understandable model. The initial persistent concepts are:

### `webhook_events`

Immutable/auditable external event receipt and processing state. Preserve at minimum the Razorpay event ID, event type, account/reference metadata where available, raw/JSON payload, signature status, processing status, timestamps, and processing errors.

### `payment_cases`

Current business state of a revenue-recovery case, including payment/subscription/customer references, amount/currency, current lifecycle state, failure metadata, attempt count, and reconciliation/resolution timestamps.

### `case_events`

Append-only internal timeline of meaningful case transitions and decisions.

### `decisions`

Persist decisions separately from current case state. Preserve decision type/source, reason code, explanation, confidence when applicable, policy result, and timestamp.

Decision source should be able to distinguish at least:

- `RULE`
- `AI`
- `AI_WITH_OVERRIDE`
- `HUMAN`

### `merchant_policies`

Explicit deterministic automation constraints such as whether automation is enabled, maximum automated attempts, recovery window, allowed actions, high-value thresholds, and approval requirements.

Avoid adding tables without a clear domain reason.

## Required Day 1 Behaviors

At minimum, ensure the implementation can demonstrate:

1. Valid signed webhook is accepted and persisted.
2. Invalid signature is rejected without mutating financial state.
3. Duplicate Razorpay event ID does not trigger duplicate business processing.
4. `payment.failed` creates or updates the correct case and captures failure metadata.
5. `payment.captured` resolves the corresponding case.
6. A late/out-of-order failed event cannot regress an already captured case.
7. `subscription.pending` results in a safe wait/observe decision when platform retry is still active.
8. `subscription.halted` is recognized as retry exhaustion and can become recovery eligible.
9. An unknown but validly signed event is persisted safely and marked unsupported rather than crashing the service.
10. Database-level uniqueness protects against concurrent duplicate ingestion.

## Testing Expectations

Tests are part of the implementation, not cleanup work.

Use unit tests for pure domain/policy logic and integration tests for webhook + database behavior.

Important failure scenarios include:

- duplicate webhook delivery
- out-of-order events
- stale failure after capture
- invalid signature
- unknown event type
- missing optional failure fields
- concurrent duplicate ingestion
- processing exception after event persistence

Later phases must additionally test malformed AI output, AI timeout, Razorpay API failure, duplicate action requests, high-value approvals, retry exhaustion, and missing customer information.

## Repository Conventions

Keep the repository easy to navigate. Prefer a structure along these lines:

```text
apps/
services/
arc/
  domain/
  ingestion/
  reconciliation/
  diagnosis/
  policy/
  intelligence/
  execution/
  audit/
integrations/
  razorpay/
evaluation/
tests/
docs/
.github/workflows/
```

The exact internal layout may evolve when justified, but preserve clear boundaries between domain logic, integrations, policy, AI intelligence, execution, and audit.

## Documentation

Maintain documentation as the system evolves.

Expected documentation includes:

- `README.md` — concise external project overview and run instructions.
- `docs/architecture.md` — system architecture and data flow.
- `docs/build-log.md` — real implementation obstacles, root causes, and fixes.
- `docs/decisions/` — Architecture Decision Records for material trade-offs.
- `docs/threat-model.md` — security, abuse, and financial-safety considerations.

Do not fabricate metrics, integrations, production readiness, merchant adoption, recovered revenue, or build challenges.

Synthetic or test-mode evaluation results must always be labeled as synthetic/test-mode results.

## Build Quality

Before calling a task complete:

- run relevant tests;
- run formatting/linting/type checks if configured;
- inspect the diff;
- ensure no secrets are present;
- ensure public interfaces remain understandable;
- document material architectural trade-offs;
- report known limitations rather than hiding them.

Prefer meaningful incremental commits over one giant final commit.

## Working With Codex

When implementing a task:

1. Read this file first.
2. Inspect existing code and documentation before creating parallel abstractions.
3. Make the smallest coherent change that satisfies the current milestone.
4. Do not silently redesign the architecture or broaden scope.
5. If a requirement conflicts with a financial-safety invariant, stop and explain the conflict.
6. If external API behavior is uncertain, do not invent it; flag the assumption for verification against current official Razorpay documentation.
7. Keep domain decisions deterministic where possible; reserve AI for contextual strategy, not basic state truth or safety enforcement.
8. Add or update tests with behavior changes.
9. Record genuine implementation obstacles in the build log when they occur.
10. At the end of a task, summarize changed files, tests run/results, assumptions, limitations, and unresolved issues.

## Definition of Done for Day 1

Day 1 is complete only when the following works end to end and the relevant tests pass:

`Webhook -> persisted event -> idempotency -> case -> reconciliation -> diagnosis -> deterministic policy decision -> audit trail`

Do not proceed to autonomous recovery execution merely because scaffolding exists. The financial core must first be demonstrably correct.