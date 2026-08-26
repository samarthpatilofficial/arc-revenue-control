# ARC Deployment

## Architecture

ARC's evaluator deployment preserves the existing product boundaries:

```text
GitHub main
  |-- Cloudflare Pages (frontend/, static React/Vite, HTTPS *.pages.dev)
  `-- Render Free Web Service (root Dockerfile, FastAPI, Singapore)
        `-- Neon PostgreSQL 18 (Singapore, TLS required)
```

The frontend reads the backend origin from `VITE_ARC_API_BASE_URL`. The
backend reads the private Neon connection string from `DATABASE_URL`. No
proxy, Pages Function, Worker, queue, or additional runtime is required.

## Public-demo safety boundary

`ARC_PUBLIC_DEMO_MODE=true` creates an evaluator-only HTTP boundary. Liveness,
readiness, evaluation, dashboard, case, timeline, approval-list, and
recovery-action-list reads remain available. Razorpay webhook ingress is not
registered, and there are no HTTP approval, execution, OpenAI, import, or
seeding routes.

Public-demo mode fails startup when `ARC_DEMO_MODE=true` or when any OpenAI,
Razorpay API, or Razorpay webhook credential is configured. Credentials are
rejected rather than ignored. Do not configure any OpenAI or Razorpay
credential on Render.

This boundary is for a read-only evaluator replica. Internal domain services
remain available to trusted operator CLIs and normal local development when
public-demo mode is false.

## Backend container and Render port

Render builds the root `Dockerfile` from the repository root. It uses Python
3.12 slim, installs the project without development dependencies, runs as an
unprivileged user, and starts through `scripts/start_backend.sh`.

The startup sequence is:

```text
python -m alembic upgrade head
python -m uvicorn services.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

Render supplies `PORT`; local container runs retain the `8000` default. The
script uses POSIX `set -eu` and `exec`. A failed migration stops startup, so
the API is never served against an outdated schema.

## Neon database

Create a Neon project with PostgreSQL 18 in Singapore. Use its private
connection string only in operator shells and Render's secret environment
settings. TLS must remain required. Neon connection strings commonly use a
driverless `postgresql://` scheme; ARC selects SQLAlchemy's psycopg driver at
runtime while preserving the remaining URL, including query parameters such
as `sslmode=require&channel_binding=require`. URLs that already specify a
driver are unchanged. The same rule applies to `TEST_DATABASE_URL` when it is
configured.

Never paste the Neon connection string into Git, Cloudflare Pages, logs,
issues, screenshots, or command output.

## Sanitized evidence replica

The public evaluator database is a sanitized replica of accepted persisted
Razorpay Test Mode, genuine OpenAI-on-synthetic-input, and controlled offline
demo evidence. Deployment does not rerun provider or model actions. A copied
Test Mode snapshot does not mean a new provider operation happened on Render.

The existing versioned, checksummed, gitignored bundle remains the source for
the replica. Do not export a new bundle merely to deploy. The operator-only
workflow is:

```text
accepted local PostgreSQL
  -> existing sanitized bundle
  -> Alembic against empty Neon database
  -> transactional CLI import
  -> read-model verification
```

In a private operator PowerShell, set the placeholder to the Neon connection
string without echoing it, then run:

```powershell
$env:DATABASE_URL = "<NEON_DATABASE_URL>"
python -m alembic upgrade head
python -m scripts.import_public_demo_bundle --bundle var/deployment/public-demo-bundle.json
python -m scripts.verify_public_demo_database
Remove-Item Env:DATABASE_URL
```

The target must be empty except for the schema created by Alembic. The importer
is transactional and the verifier uses the same sanitized read-model checks.
There is no HTTP import route and no Neon CLI dependency.

## Render Free Web Service configuration

Create a Render **Web Service** with these settings:

| Field | Value |
| --- | --- |
| Repository | `samarthpatilofficial/arc-revenue-control` |
| Branch | `main` |
| Runtime | Docker |
| Dockerfile path | `./Dockerfile` |
| Region | Singapore |
| Instance type | Free |
| Health check path | `/health` |

Configure these runtime environment variables:

```text
ARC_PUBLIC_DEMO_MODE=true
ARC_DEMO_MODE=false
DEBUG=false
ENVIRONMENT=public-demo
DATABASE_URL=<PRIVATE_NEON_DATABASE_URL>
CORS_ALLOWED_ORIGINS=[]
```

Do not set OpenAI keys, Razorpay keys, Razorpay webhook secrets, or
`TEST_DATABASE_URL`. Render will assign the service URL in the form
`https://<service>.onrender.com`; record the real generated value only after
creation.

## Cloudflare Pages configuration

Create a Cloudflare Pages project with these fields:

| Field | Value |
| --- | --- |
| Repository | `samarthpatilofficial/arc-revenue-control` |
| Production branch | `main` |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variable | `VITE_ARC_API_BASE_URL=https://<render-service>.onrender.com` |

The build is a static React Router SPA. No Pages Function or Worker is needed.
Use the actual Render hostname when configuring the build variable.

## Exact two-phase CORS rollout

1. Create Neon and privately migrate/import/verify the empty database.
2. Create Render with `CORS_ALLOWED_ORIGINS=[]` and all other settings above.
3. Wait for `/health` and `/ready` to succeed on the generated Render URL.
4. Create Cloudflare Pages with that exact Render URL in
   `VITE_ARC_API_BASE_URL`.
5. Copy the actual production `https://<project>.pages.dev` origin.
6. Change Render's `CORS_ALLOWED_ORIGINS` to a JSON array containing exactly
   that one origin, for example `["https://<project>.pages.dev"]`.
7. Redeploy Render, then verify the Pages console can read the API.

Never use wildcard CORS, even temporarily. Keep localhost out of the public
service configuration.

## Render Free cold starts

The frontend expects the Free Web Service to sleep. On first load it shows
`Checking backend…`; after an unsuccessful health request it shows
`Waking demo backend…`. Only `GET /health` is retried, every 9 seconds, for a
maximum of 10 attempts (about 90 seconds). A successful response changes the
status to `Operational` and ends all health polling. Exhaustion changes it to
`API unavailable` and exposes a manual `Retry` control.

If Overview data fails while health is checking or waking, the page says:
`Demo backend is waking up. This can take up to a minute on the free evaluator
deployment.` It does not substitute fake data. ARC does not use keepalive
requests or third-party pings to prevent Render from sleeping.

## Health and readiness

`GET /health` is a process liveness probe and does not query PostgreSQL.
`GET /ready` performs a minimal database query. Database failure returns `503`
with a sanitized error and never exposes host, database, username, driver,
connection URL, or traceback. Render's health check must use `/health`.

## CI/CD

GitHub Actions continues to run backend migrations/tests and frontend lint,
tests, and production build on `main`. Render builds the root Dockerfile and
Cloudflare Pages builds the static frontend from the same accepted branch.
This repository configuration does not perform a deployment itself.

## Limitations

This is an evaluator/demo deployment, not a production merchant environment.
It is intentionally read-only, uses a sanitized evidence replica, has one
backend process, and does not expose operational mutation controls. Render
Free cold starts can delay first access. Production merchant deployment would
require separate identity, authorization, secret management, observability,
backup, and operational-security work.
