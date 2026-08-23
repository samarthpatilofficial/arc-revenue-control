# ARC — Autonomous Revenue Control

This repository contains ARC's backend financial core and governed recovery loop: secure webhook ingress, authoritative reconciliation, deterministic eligibility and diagnosis, bounded strategy proposals, merchant policy authorization, crash-safe Payment Link execution, authoritative outcome observation, and strict recovered-revenue attribution.

## Local setup

Requirements: Python 3.12+ and access to PostgreSQL. A native PostgreSQL installation is fully supported; Docker Compose is an optional alternative.

### Install the application

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Configure PostgreSQL

For native PostgreSQL, create a local ARC development database, a separate database whose name ends in `_test`, and a login role using your preferred PostgreSQL administration tool. Then set the private `.env` file to the matching connection URLs:

```dotenv
DATABASE_URL=postgresql+psycopg://<username>:<password>@localhost:5432/<database>
TEST_DATABASE_URL=postgresql+psycopg://<username>:<password>@localhost:5432/<database>_test
```

The test database name must end in `_test`; destructive test setup refuses any other target. Never commit `.env`. The repository tracks only `.env.example` with non-secret placeholder values.

If Docker is available, its PostgreSQL service can be used instead:

```powershell
docker compose up -d postgres
```

The `POSTGRES_*` values and `DATABASE_URL` in `.env` must describe the same database when using Compose.

### Run the foundation

```powershell
python -m alembic upgrade head
python -m uvicorn services.api.main:app --reload
```

The migrations create the event/case ledger, merchant policies, bounded strategy and policy records, governed recovery actions, outcome observations, and recovery attributions.

The API is available at `http://localhost:8000`. Its liveness endpoint is:

```text
GET /health
```

### Read API

The versioned operator API is read-only and exposes display-safe projections:

```text
GET /api/v1/dashboard/summary?provider_mode=TEST&currency=INR
GET /api/v1/cases
GET /api/v1/cases/{case_reference}
GET /api/v1/cases/{case_reference}/timeline
GET /api/v1/approvals
GET /api/v1/recovery-actions
```

Responses omit customer, merchant, payment, subscription, and provider-payment identifiers; raw webhook/provider data; fingerprints and idempotency keys; credentials; and Payment Link URLs. Dashboard recovery metrics always require one provider mode and currency, and are calculated only from persisted outcome evidence. Configure explicit frontend origins with `CORS_ALLOWED_ORIGINS`, using JSON array syntax. The default is no cross-origin access, and wildcard origins are rejected.

### Controlled demo scenarios

Synthetic demo seeding is disabled by default. To create the three idempotent offline scenarios in the configured database, enable it only for the command process:

```powershell
$env:ARC_DEMO_MODE = "true"
python -m scripts.seed_demo
Remove-Item Env:ARC_DEMO_MODE
```

The seeder makes no Razorpay or OpenAI calls and creates no Payment Link. Each scenario is marked `SYNTHETIC_DEMO` through a bounded audit event. The existing evidence-backed Razorpay Test Mode recovery remains separately labelled `TEST_MODE`.

**TEST MODE != LIVE MONEY. SYNTHETIC DEMO != PROVIDER EVIDENCE.** Synthetic cases do not increase evidence-backed recovered-revenue metrics.

### Webhook development

Configure `RAZORPAY_WEBHOOK_SECRET` in the private `.env` file. This signing secret is separate from `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`, which authenticate authoritative Razorpay Test Mode entity reads. Then send Razorpay events to:

```text
POST /webhooks/razorpay
```

ARC verifies `X-Razorpay-Signature` using HMAC-SHA256 over the exact raw request bytes before parsing JSON. `x-razorpay-event-id` is required and protected by database uniqueness. During secret rotation, `RAZORPAY_WEBHOOK_PREVIOUS_SECRET` can temporarily validate retries signed with the former secret.

The currently recognized event types are `payment.failed`, `payment.captured`, `subscription.pending`, `subscription.halted`, `payment_link.paid`, `payment_link.cancelled`, `payment_link.expired`, and `payment_link.partially_paid`. Other correctly signed events are safely recorded as unsupported. The HTTP endpoint only authenticates, normalizes, and persists events so ingress remains fast.

ARC treats a webhook as a signal, not current financial truth. A separate application service reconciles supported stored events using only these read operations:

```text
GET /v1/payments/{payment_id}
GET /v1/subscriptions/{subscription_id}
```

The fetched status is stored separately from ARC's guarded case lifecycle. A captured payment or active subscription can safely resolve an existing case without trusting webhook order. After reconciliation, ARC's assessment service applies this bounded sequence:

```text
authoritative reconciliation -> precondition gate -> deterministic diagnosis
```

A captured payment produces `STOP`; a `pending` subscription produces `WAIT` so ARC does not compete with Razorpay retries; and a `halted` subscription is eligible for deterministic diagnosis because automatic retries are exhausted. Payment diagnosis uses structured Razorpay reason, source, and step fields in that precedence order, with bounded future-tolerant fallbacks.

Eligible `DIAGNOSED` cases can now move through the governed recovery loop:

```text
detect -> reconcile -> diagnose -> decide -> authorize -> execute -> observe -> measure
```

AI proposals use the OpenAI Responses API with strict Structured Outputs and the fixed action vocabulary `NO_ACTION`, `WAIT`, `REQUEST_RETRY`, `CREATE_RECOVERY_LINK`, `REQUEST_PAYMENT_METHOD_UPDATE`, and `ESCALATE_TO_HUMAN`. Manual-review and merchant-fix dispositions bypass AI and produce deterministic rule proposals. Strategy generation sends no customer PII or external payment/subscription identifiers, and a post-inference database fence discards output if reconciled facts changed while the model was running.

Set `OPENAI_API_KEY` privately only when AI strategy generation is needed; application startup and automated tests do not require a real key. `OPENAI_MODEL` defaults to `gpt-5.6-luna`.

Merchant authorization is deterministic. It validates the action allowlist, automated-attempt and customer-contact limits, recovery window, approval threshold, and a small typed stopping-rule schema. Missing or malformed policy fails closed for external recovery actions. Safe internal actions remain available, and high-value cases can require human approval. Model confidence is observability data and cannot bypass policy.

**AI proposes. Policy authorizes. Human approval clears only the exact approval-required decision. The executor performs only that governed action.** `POLICY_VALIDATED` alone is not permission to execute: the executor rechecks current assessment, diagnosis, strategy, policy, counters, recovery window, and any exact approved record immediately before claiming work.

Standard Razorpay Payment Link creation is ARC's first real external recovery side effect. `CREATE_RECOVERY_LINK` uses a stable `arc_<action-uuid>` reference, disables partial payments, reminders, SMS, and email, sends no customer PII, and recovers uncertain create outcomes through lookup-before-create. A PostgreSQL action ledger provides one row per policy decision, execution leases, exact-once counters, sanitized provider projections, and post-request compensation when financial truth changes during creation. `WAIT`, `NO_ACTION`, and `ESCALATE_TO_HUMAN` are bounded internal actions. `REQUEST_RETRY` and `REQUEST_PAYMENT_METHOD_UPDATE` fail safely as not implemented because ARC has no valid Razorpay retry or customer-delivery executor for them.

Creating a Payment Link is not recovered revenue. A Payment Link webhook is only a trigger: ARC matches it to an existing governed action and then performs an authoritative `GET /v1/payment_links/{id}`. Revenue is attributed only when the link id, stable reference, amount, paid amount, currency, and exactly one captured payment all match the original action and case. Partial, ambiguous, conflicting, or unknown evidence is escalated for review. Evidence fingerprints, action uniqueness, and provider-payment uniqueness prevent duplicate events or repeated polls from double-counting revenue.

Every attribution is explicitly tagged `TEST` or `LIVE` from private credential metadata; metrics require an explicit provider-mode and currency scope, so test-mode revenue is never silently aggregated with live merchant revenue. No customer object, Payment Link URL, raw provider response, or credential is copied into outcome or attribution storage.

There is no public approval UI, automatic polling scheduler, frontend, or production operator identity system yet. ARC does not capture or refund payments, send customer communications, support partial-payment attribution, or infer recovery attribution from generic `payment.captured` events.

Run the tests with:

```powershell
python -m pytest
```

If using Compose, stop its database with `docker compose down`. Add `--volumes` only when you intentionally want to remove local PostgreSQL data.
