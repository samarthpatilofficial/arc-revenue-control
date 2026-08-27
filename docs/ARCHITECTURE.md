# ARC — Technical Architecture

ARC is a policy-governed revenue-recovery control plane for Razorpay merchants. It treats payment failure as a signal to establish current truth, not as permission to retry or contact a customer.

This document describes the implementation in this repository. Future production evolution is labelled explicitly and is not an implementation claim.

## 1. System purpose

ARC closes an auditable recovery loop:

```text
detect -> reconcile -> diagnose -> decide -> authorize -> execute -> observe -> measure
```

The system is designed to prevent duplicate, stale, premature, or unauthorized recovery while preserving enough evidence to explain each decision and attribute a successful recovery exactly once.

ARC is implemented as a FastAPI modular monolith with a React operator console and PostgreSQL as the concurrency, persistence, and audit authority. It does not use Redis, Celery, Kafka, or a model-controlled tool layer.

## 2. Core principle

> **AI proposes. Policy authorizes. The executor acts. Provider evidence proves recovery.**

Responsibility is deliberately separated:

- Razorpay reads establish provider truth.
- deterministic eligibility and diagnosis interpret bounded facts;
- the strategy boundary proposes one bounded action;
- merchant policy and, when required, a human authorize that exact proposal;
- the executor performs only the authorized operation;
- authoritative Payment Link evidence determines recovery;
- attribution and metrics are calculated from durable evidence.

Model output never determines whether a payment is paid, grants itself authority, or increments recovered-revenue metrics.

## 3. System context

```text
Razorpay Test Mode / webhooks       OpenAI Responses API
              |                           |
              v                           v
        +---------------------------------------+
        |             ARC FastAPI               |
        | webhook, domain, policy, execution,   |
        | outcome, audit, and read services     |
        +-------------------+-------------------+
                            |
                            v
                     +-------------+
                     | PostgreSQL  |
                     | source of   |
                     | ARC truth   |
                     +------+------+
                            |
                            v
                 Read-only React console
```

External boundaries are:

- **Razorpay** for signed webhook triggers, authoritative payment and subscription reads, governed Standard Payment Link operations, and Payment Link outcome reads;
- **OpenAI** for tool-free, structured strategy proposals;
- **the operator** for viewing sanitized state; the internal approval service records policy-scoped human decisions when invoked by a trusted backend workflow;
- **the browser** for read-only display contracts.

The demonstrated provider-backed recovery uses Razorpay Test Mode. Provider mode is derived from private credentials and retained as `TEST` or `LIVE` on outcome evidence and attribution so metrics cannot mix modes.

### 3.1 Evaluator deployment (not a product requirement)

The live evaluator hosts the existing product boundaries without changing the
control loop:

```text
GitHub main
  |-- Cloudflare Workers Static Assets
  |     React/Vite read-only SPA
  |     https://arc-revenue-control-ui.samarthpatilofc.workers.dev
  |
  `-- Render Free Docker Web Service (Singapore)
        https://arc-revenue-control.onrender.com
        |
        `-- Neon PostgreSQL 18 (Singapore / TLS)
```

The public backend starts in fail-closed `ARC_PUBLIC_DEMO_MODE`, exposes only
the health/read surface, omits provider credentials, and reads a sanitized
evidence replica. It does not rerun Razorpay or OpenAI operations. Cloudflare,
Render, and Neon are evaluator hosting choices, not intrinsic ARC product
requirements.

## 4. Recovery control loop

| Stage | Implemented owner | Result |
| --- | --- | --- |
| Detect | webhook gateway + event ledger | Authenticated event retained once. |
| Reconcile | Razorpay reader + reconciliation service | Current provider state projected without terminal regression. |
| Diagnose | eligibility + failure classifier | Bounded eligibility, category, disposition, and reason codes. |
| Decide | deterministic rule or OpenAI strategy provider | One proposal from the fixed action vocabulary. |
| Authorize | merchant policy + optional human approval | `AUTHORIZED`, `REQUIRES_APPROVAL`, or `BLOCKED`. |
| Execute | governed recovery executor | Internal action or one idempotent Standard Payment Link operation. |
| Observe | outcome service | Authoritative Payment Link and captured-payment evidence. |
| Measure | recovery attribution + read models | Exact-once, mode-scoped recovered amount and audit trace. |

## 5. Trust boundaries

### 5.1 Webhook trust

Incoming webhook JSON is untrusted until ARC verifies `X-Razorpay-Signature` as HMAC-SHA256 over the exact raw request bytes. The event identifier is validated separately. Invalid signatures and malformed envelopes do not enter the event ledger.

### 5.2 Authoritative provider state

A valid webhook is a processing trigger, not financial truth. Payment and subscription signals are reconciled through authenticated Razorpay `GET` operations. Payment Link outcome events likewise trigger a fresh authoritative Payment Link read.

### 5.3 AI output trust

OpenAI output is untrusted until it passes strict Structured Output parsing, local Pydantic validation, the bounded action vocabulary, disposition/action compatibility, and current-state fingerprint checks. The model receives no tools.

### 5.4 Policy authority

The deterministic policy engine owns action allowlists, automation controls, recovery windows, attempt and contact limits, stopping rules, amount thresholds, and approval requirements. Model confidence is observability metadata and is not an authorization input.

### 5.5 Execution authority

The executor accepts the current unsuperseded strategy and policy decision, or an exact approved human-approval record. It recomputes current authorization before any operation and again after an external request.

### 5.6 Outcome evidence

Recovery requires matching provider identity, stable reference, amount, currency, amount paid, and captured-payment evidence. A created action or paid-looking webhook alone does not qualify.

## 6. Current component architecture

The backend is organized by responsibility under `arc/`:

| Module | Implemented responsibility |
| --- | --- |
| `arc/config.py` | Typed environment settings and secret wrappers. |
| `arc/db/` | SQLAlchemy metadata, engine, and session lifecycle. |
| `arc/domain/` | Controlled enums and persisted SQLAlchemy models. |
| `arc/persistence/` | Race-safe event, case, policy, and audit persistence helpers. |
| `arc/reconciliation/` | Event claims, Razorpay reads, state projection, and lifecycle guards. |
| `arc/assessment.py` | Transactional eligibility and diagnosis projection. |
| `arc/diagnosis/` | Deterministic structured failure classification. |
| `arc/intelligence/` | Minimum-data context, strict strategy schema, compatibility, fingerprints, and proposal service. |
| `arc/integrations/openai/` | Tool-free OpenAI Responses API adapter. |
| `arc/policy/` | Strict policy parsing, pure authorization rules, fingerprints, and persisted decisions. |
| `arc/approval/` | Decision-scoped human approval and permission checks. |
| `arc/execution/` | Idempotent action ledger, execution lease, provider fencing, and compensation. |
| `arc/integrations/razorpay/` | Webhook security, bounded entity reads, and Standard Payment Link gateway. |
| `arc/outcomes/` | Provider evidence classification, observation, attribution, and metrics. |
| `arc/read_models/` | Display-safe projections for the operator API. |
| `arc/demo/` | Controlled scenario seeding and read-only semantic preflight. |

`services/api/` contains the FastAPI application, dependencies, health route, Razorpay webhook ingress, and read-only operator routes. `frontend/` contains the React and TypeScript operator console. `migrations/` contains the Alembic schema history.

The domain modules do not depend on FastAPI request objects. External adapters implement narrow protocols so tests can exercise provider behavior without network access.

## 7. Persistence model

PostgreSQL stores ten principal tables:

| Table | Purpose and important controls |
| --- | --- |
| `webhook_events` | Immutable accepted payload ledger; unique Razorpay event id; raw-body and canonical-payload hashes; processing status, lease, attempts, and sanitized error. |
| `payment_cases` | Current reconciled case projection; deterministic case reference; amount in minor units; lifecycle, assessment, failure, and exact attempt/contact counters. |
| `case_events` | Append-only internal audit timeline with bounded event types and structured metadata. |
| `strategy_proposals` | Append-friendly rule/AI proposals; one current proposal per case; input fingerprints and bounded model metadata. |
| `merchant_policies` | Merchant action allowlist, automation controls, limits, thresholds, recovery window, and typed stopping-rule JSON. |
| `policy_decisions` | Exact deterministic authorization result and observed inputs; one current decision per case. |
| `approval_requests` | One irreversible, decision-scoped pending/approved/rejected human decision. |
| `recovery_actions` | Idempotent execution intent, lease, attempt count, sanitized provider projection, and final execution state. |
| `recovery_outcome_observations` | Append-friendly normalized authoritative Payment Link evidence, unique per action and evidence fingerprint. |
| `recovery_attributions` | Exact-once recovered amount linked to one action, one observation, and one unique provider payment. |

Database uniqueness and check constraints are correctness controls, not only validation conveniences. Timestamps are timezone-aware and financial amounts use integer minor units.

`webhook_events` rejects updates to accepted payload and identity fields. `case_events` rejects updates and deletes. Operational status fields remain mutable where crash recovery requires it.

## 8. Webhook processing and crash-safe lease

`POST /webhooks/razorpay` performs this sequence:

```text
read exact bytes
  -> verify current/previous webhook secret
  -> parse strict JSON envelope
  -> validate event id and bounded identifiers
  -> insert immutable event with PostgreSQL ON CONFLICT
  -> return a payload-free acknowledgement
```

Supported event families are payment failure/capture, subscription pending/halted, and Payment Link paid/cancelled/expired/partially-paid triggers. Valid unknown event types are retained as `UNSUPPORTED` and do not enter financial processing.

Business processing uses `SELECT ... FOR UPDATE` to claim the event. A claim moves `RECEIVED` or `FAILED` to `PROCESSING`, sets `processing_started_at`, increments `processing_attempt_count`, and clears stale error metadata.

The processing lease is 120 seconds:

- a recent `PROCESSING` claim returns `EVENT_ALREADY_PROCESSING`;
- a missing or expired lease is reclaimed transactionally;
- completion checks the claim attempt number so an abandoned worker cannot overwrite a newer claim;
- handled failures become retryable `FAILED` rows with bounded, sanitized errors;
- successful rows become idempotent `PROCESSED` rows.

No distributed queue or background worker is required for this crash-recovery property.

## 9. Reconciliation and terminal non-regression

The Razorpay adapter exposes bounded `GET` readers for payments and subscriptions. Responses are projected into strict Pydantic snapshots while unknown future status strings are preserved for fail-safe handling.

Payment reconciliation:

- creates one deterministic case for a confirmed failed payment;
- refreshes structured amount, currency, method, customer correlation, and failure fields from provider truth;
- moves captured truth to `RECOVERED` and refunded truth to `EXHAUSTED`;
- does not create a recovery case for a standalone confirmed capture;
- retains non-final or unrecognized truth without advancing recovery.

Subscription reconciliation:

- treats `pending` as active platform retry;
- treats `halted` as exhausted platform retry and eligible for assessment;
- resolves active truth without competing recovery;
- stops terminal cancelled/completed/expired truth.

The explicit state machine allows forward or authoritative terminal transitions only. `RECOVERED`, `EXHAUSTED`, and `ESCALATED` are terminal. A later failure signal cannot move a terminal case backwards.

## 10. Eligibility and deterministic diagnosis

Eligibility is evaluated from persisted, recently reconciled facts. The assessment freshness window is five minutes. Results are one of:

- `ELIGIBLE` — confirmed failed payment or halted subscription;
- `WAIT` — reconciliation required/stale, non-final payment, active retry, or another pending state;
- `STOP` — already captured, refunded, active, or terminal;
- `REVIEW` — missing, conflicting, malformed, or unknown current truth.

Only `ELIGIBLE` cases are diagnosed. The classifier uses structured `error_reason`, then `error_source`, then `error_step`; it never machine-classifies `error_description`. Implemented categories cover customer authentication, funds, interruption, instrument restriction, bank/issuer, gateway/network, merchant configuration, platform issues, subscription retry exhaustion, and unknown context.

Assessment inputs are fingerprinted. Reassessment preserves historical bounded values in append-only `CaseEvent` rows while updating the current case projection.

## 11. AI Strategy Engine

The strategy service receives only validated, PII-minimized context:

- amount and currency;
- normalized payment method and current status;
- bounded failure category, disposition, and reason code;
- structured error reason/source/step;
- attempt count and payment/subscription kind.

The OpenAI adapter uses the Responses API with:

- strict JSON Schema Structured Outputs;
- `store: false`;
- no tools;
- bounded output tokens and request timeout;
- a fixed developer instruction separated from serialized case data;
- local schema validation after the response.

The action vocabulary is:

```text
NO_ACTION
WAIT
REQUEST_RETRY
CREATE_RECOVERY_LINK
REQUEST_PAYMENT_METHOD_UPDATE
ESCALATE_TO_HUMAN
```

Unknown/manual-review/merchant-fix dispositions bypass AI and produce a deterministic human escalation. Other model actions must match the disposition compatibility matrix.

Inference occurs outside a database transaction. Before persistence, ARC row-locks the case and recomputes assessment context and fingerprints. Changed truth causes the proposal to be discarded and audited as stale.

## 12. Deterministic policy and human approval

Merchant policy is parsed into a strict typed configuration. Malformed JSON, unknown actions, invalid values, or missing policy fail closed for external recovery.

Authorization applies hard-stop-first precedence:

1. internal `NO_ACTION`, `WAIT`, and `ESCALATE_TO_HUMAN` remain safety-preserving;
2. external actions require a valid configured policy and allowlist membership;
3. failure-category and payment-method stopping rules block first;
4. recovery-window, automated-attempt, and customer-contact limits block;
5. missing amount blocks external recovery;
6. configured action or amount thresholds require approval;
7. disabled automation requires approval;
8. only then is an external action authorized.

Hard-stop decisions move a case to `EXHAUSTED`; other blocked decisions escalate. Authorized and approval-required decisions remain `POLICY_VALIDATED` but have distinct decision records.

A human approval is bound to one exact current policy decision. Approval cannot transfer to a reevaluated decision, reverse after reaching a terminal choice, or bypass current case and policy validation. Rejection escalates the case. Approval grants executor permission only for that exact decision.

## 13. Governed execution

Execution uses a durable action ledger and never accepts raw model output. The service recomputes assessment, strategy, policy, counters, amount, recovery window, and approval before claiming work.

Safety controls include:

- one recovery action per policy decision;
- a SHA-256 idempotency key bound to the exact proposal and authorization;
- a request fingerprint covering the complete PII-free operation;
- a stable `arc_...` reference generated before any provider write;
- a 120-second database execution lease with stale reclaim;
- lookup-by-reference before Payment Link creation;
- adoption of one matching existing link after an uncertain write;
- refusal to create when lookup is unavailable or ambiguous;
- no customer PII, notifications, reminders, or partial payments in the request;
- post-request state and authorization fencing;
- cancellation compensation when truth changed during a provider write.

Attempt and contact counters increment exactly once, only after a provider action is confirmed and persisted. Duplicate calls return the same action row without another external operation or counter increment.

`WAIT`, `NO_ACTION`, and `ESCALATE_TO_HUMAN` have bounded internal executors. `CREATE_RECOVERY_LINK` is the implemented external executor. `REQUEST_RETRY` and `REQUEST_PAYMENT_METHOD_UPDATE` fail safely as unimplemented executor actions.

## 14. Outcome observation and recovery attribution

Outcome observation is a two-transaction operation:

1. row-lock and validate the action/case, then commit;
2. fetch the Payment Link outside a database transaction;
3. row-lock again, verify context is unchanged, classify evidence, and persist.

A recovered classification requires all of the following:

- expected Payment Link id;
- expected stable reference;
- exact amount and currency;
- provider status `paid`;
- `amount_paid` equal to the expected amount;
- exactly one captured payment for the expected amount;
- no conflicting Payment Link identity.

Partial payment, ambiguity, mismatch, or unknown provider status becomes `REVIEW_REQUIRED`. Expired or cancelled zero-paid links exhaust a waiting case without attribution.

Attribution is unique by recovery action, outcome observation, and provider payment id. It is created only with `ARC_PAYMENT_LINK_CAPTURED` evidence. Existing recovery or attribution conflicts fail into review rather than double-counting.

Every observation and attribution stores `TEST` or `LIVE` provider mode. Metrics require an explicit mode and currency, so Test Mode proof cannot be reported as Live revenue.

## 15. Read API and frontend trust boundary

The implemented API surface is:

```text
GET  /health
POST /webhooks/razorpay
GET  /api/v1/dashboard/summary
GET  /api/v1/evaluation/summary
GET  /api/v1/cases
GET  /api/v1/cases/{case_reference}
GET  /api/v1/cases/{case_reference}/timeline
GET  /api/v1/approvals
GET  /api/v1/recovery-actions
```

The operator endpoints use closed Pydantic response models. They omit credentials, customer and merchant identifiers, provider payment identifiers, Payment Link URLs, raw webhook/provider payloads, fingerprints, and idempotency keys.

The React console performs display and navigation only. It does not reproduce financial policy, call Razorpay/OpenAI, or expose mutation controls. CORS is deny-by-default; configured origins must be explicit HTTP(S) origins and only `GET` methods are allowed cross-origin.

Historical timeline items are rendered from bounded values stored with each event. Arbitrary `event_data`, assessment evidence, external statuses, and fingerprints are not passed through to display output.

## 16. Demonstration and synthetic-data separation

The repository supports three distinct evidence classes:

- a provider-backed Razorpay Test Mode recovery with authoritative observation and attribution;
- three controlled `SYNTHETIC_DEMO` safety scenarios for approval, already-captured protection, and hard stopping.
- one explicit `SYNTHETIC_INPUT` case whose proposal is produced by the genuine OpenAI Responses API integration and then stopped by deterministic non-execution policy.

Read projections derive strategy provenance from persisted proposal evidence: `RULE` is deterministic, the known `arc-demo-offline-strategy-v1` model is an offline simulation, and other `AI` proposals originate from ARC's only external strategy adapter, OpenAI. The API may expose the bounded model name but never the provider response id, prompt, raw output, or strategy fingerprint.

The OpenAI evidence script reuses `StrategyService`, its stale-context fencing, strict Structured Outputs, and the merchant authorization service. It has no execution or Razorpay client dependency. A valid external-action proposal requires human approval; safe internal proposals may be authorized but are never executed by this workflow. Provider recovery actions and attribution are verified absent before the script reports readiness.

Synthetic scenario seeding is disabled unless `ARC_DEMO_MODE=true`. The seeder is idempotent and makes no Razorpay or OpenAI request. Reserved audit markers label synthetic cases, and preflight verifies that they have no provider attribution and do not affect evidence-backed recovery metrics.

`python -m scripts.demo_preflight` runs inside a PostgreSQL read-only transaction. It checks the real Test Mode attribution, controlled scenarios, evidence consistency, mode isolation, and sanitized output. It does not seed, execute, or observe anything.

## 17. Batch evaluation boundary

The batch evaluator is an isolated, persistence-free evidence path:

```text
Synthetic Dataset
      |
      v
ARC Domain Logic
      |
      v
Bounded Strategy Provider
      |
      v
Deterministic Policy
      |
      v
Controlled Synthetic Outcome
      |
      v
Evaluation Metrics
```

The default fixed-seed run uses transient cases and the implemented
eligibility, diagnosis, strategy-schema, action-compatibility, policy, and
execution-idempotency logic. Its offline strategy fixtures conform to the same
bounded output contract as the OpenAI client but make no network request. The
optional live-model subset remains read-only and cannot call Razorpay.

Each transient case yields a bounded decision record through eligibility,
diagnosis, strategy, policy, simulated execution, and controlled outcome.
Only aggregate metrics and scenario breakdowns enter the tracked artifact;
the operational database retains its own append-only audit history.

Evaluation metrics and artifacts are stored separately from operational
recovery observations and attribution. A synthetic successful outcome never
creates a `RecoveryAttribution`, never changes Test or Live dashboard metrics,
and is always labelled synthetic evidence.

`GET /api/v1/evaluation/summary` validates and returns only bounded aggregate fields from the tracked `evaluation/results/latest.json` artifact. It exposes no scenario identifiers or operational database data, so the frontend has one source of truth without combining synthetic and provider-backed metrics.

## 18. Security properties

Implemented security and financial-safety properties include:

- environment-only secrets represented by Pydantic `SecretStr`;
- exact-body webhook HMAC verification with bounded secret rotation;
- immutable accepted webhook identity and payload fields;
- PostgreSQL uniqueness for event, proposal, decision, action, observation, and attribution identities;
- row locks and leases for crash-safe claims;
- no full provider payload logging or persistence outside the immutable webhook ledger;
- sanitized external error classes and bounded persisted errors;
- PII-minimized OpenAI and Payment Link requests;
- no model tools or arbitrary action names;
- deterministic terminal-state, policy, approval, and counter authority;
- evidence-based, mode-scoped revenue metrics;
- read-model allowlists instead of persistence-object serialization.

## 19. Current limitations

- Provider-backed proof is Razorpay Test Mode, not live merchant money.
- The operator console is read-only and has no approval or execution controls.
- There is no production operator identity, authentication, authorization, or tenant isolation.
- There is no automatic polling scheduler or background worker.
- `REQUEST_RETRY` and `REQUEST_PAYMENT_METHOD_UPDATE` have no external executor.
- Partial-payment attribution is not supported.
- ARC does not capture or refund payments.
- ARC sends no customer communications.
- PostgreSQL is required for integration tests and operational persistence.

## 20. Future production evolution — not implemented

A production deployment would require authenticated multi-tenant operator access, managed secret storage, encrypted sensitive fields, stronger observability and alerting, scheduled outcome polling, explicit retry operations, operational reconciliation tooling, and deployment-specific availability controls.

At higher traffic, the durable PostgreSQL ledger and idempotent service boundaries could feed queue-backed workers. No queue, distributed worker, production IAM, or deployment topology is implemented in this repository.

## 21. Architectural invariant

For every recovery case, ARC is designed to answer:

> **What happened? What is true now? Why was this action proposed? Was it allowed? What was executed? What provider evidence exists? What amount, if any, can be attributed?**

That evidence chain—not component count—is the architecture's measure of correctness.
