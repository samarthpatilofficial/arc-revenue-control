# ARC — Autonomous Revenue Control

This repository currently contains ARC's Day 1 backend financial core: a FastAPI application, typed environment configuration, PostgreSQL/SQLAlchemy infrastructure, Alembic migrations, secure webhook ingress, an immutable external event ledger, authoritative read-only Razorpay reconciliation, a deterministic recovery preconditions gate, and deterministic failure diagnosis.

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

The migration creates the core `webhook_events`, `payment_cases`, `case_events`, and `merchant_policies` tables.

The API is available at `http://localhost:8000`. Its liveness endpoint is:

```text
GET /health
```

### Webhook development

Configure `RAZORPAY_WEBHOOK_SECRET` in the private `.env` file. This signing secret is separate from `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`, which authenticate authoritative Razorpay Test Mode entity reads. Then send Razorpay events to:

```text
POST /webhooks/razorpay
```

ARC verifies `X-Razorpay-Signature` using HMAC-SHA256 over the exact raw request bytes before parsing JSON. `x-razorpay-event-id` is required and protected by database uniqueness. During secret rotation, `RAZORPAY_WEBHOOK_PREVIOUS_SECRET` can temporarily validate retries signed with the former secret.

The currently recognized event types are `payment.failed`, `payment.captured`, `subscription.pending`, and `subscription.halted`. Other correctly signed events are safely recorded as unsupported. The HTTP endpoint only authenticates, normalizes, and persists events so ingress remains fast.

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

AI strategy, merchant authorization, recovery execution, Payment Links, human approval workflows, recovery-attempt changes, and revenue attribution are not implemented yet. The deterministic assessment projection does not choose or execute a customer recovery action.

Run the tests with:

```powershell
python -m pytest
```

If using Compose, stop its database with `docker compose down`. Add `--volumes` only when you intentionally want to remove local PostgreSQL data.
