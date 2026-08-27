# ARC Live Evaluator Deployment

## Actual evaluator architecture

```text
GitHub main
  |
  |-- Cloudflare Workers Static Assets
  |     React/Vite SPA
  |     https://arc-revenue-control-ui.samarthpatilofc.workers.dev
  |
  `-- Render Free Docker Web Service
        https://arc-revenue-control.onrender.com
        |
        `-- Neon PostgreSQL 18
            Singapore / TLS
```

This is the verified evaluator topology. Cloudflare Workers serves only the
compiled static frontend with SPA fallback. Render runs the FastAPI container
in Singapore, and the backend reads its private Neon PostgreSQL connection
from `DATABASE_URL`.

## Public-demo safety boundary

`ARC_PUBLIC_DEMO_MODE=true` creates an evaluator-only HTTP boundary. Liveness,
readiness, evaluation, dashboard, case, timeline, approval-list, and
recovery-action-list reads remain available. Razorpay webhook ingress is not
registered, and there are no HTTP approval, execution, OpenAI, import, or
seeding routes.

Public-demo mode fails startup when `ARC_DEMO_MODE=true` or when any OpenAI,
Razorpay API, or Razorpay webhook credential is configured. The hosted
evaluator has no provider credentials and does not rerun Razorpay or OpenAI
operations. Its Razorpay evidence is Test Mode evidence, not live money, and
synthetic evaluation metrics are not merchant revenue.

This is a read-only evaluator replica, not a production merchant environment.
Internal domain services remain available to trusted operator CLIs and normal
local development when public-demo mode is false.

## Render Free Web Service

The backend uses these settings:

| Field | Value |
| --- | --- |
| Service type | Web Service |
| Repository | `samarthpatilofficial/arc-revenue-control` |
| Branch | `main` |
| Runtime | Docker |
| Dockerfile path | `./Dockerfile` |
| Region | Singapore |
| Instance type | Free |
| Health check path | `/health` |
| Public URL | `https://arc-revenue-control.onrender.com` |

Runtime configuration:

```text
ARC_PUBLIC_DEMO_MODE=true
ARC_DEMO_MODE=false
DEBUG=false
ENVIRONMENT=public-demo
DATABASE_URL=<PRIVATE_NEON_DATABASE_URL>
CORS_ALLOWED_ORIGINS=["https://arc-revenue-control-ui.samarthpatilofc.workers.dev"]
```

`DATABASE_URL` remains private in Render configuration. Do not configure
OpenAI keys, Razorpay keys, Razorpay webhook secrets, or `TEST_DATABASE_URL`.

Render builds the root Dockerfile and starts through
`scripts/start_backend.sh`:

```text
python -m alembic upgrade head
python -m uvicorn services.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

Render supplies `PORT`; local container runs retain the `8000` default. A
failed migration stops startup before the API is served.

## Neon PostgreSQL

The evaluator database is Neon PostgreSQL 18 in Singapore with TLS required.
Its hostname, username, password, and complete connection string are private.
Driverless `postgresql://` URLs are normalized to SQLAlchemy's psycopg driver
without changing the remaining URL or TLS query parameters.

The database contains a sanitized replica of accepted persisted Razorpay Test
Mode, genuine OpenAI-on-synthetic-input, and controlled offline demo evidence.
Copying accepted evidence does not perform a new provider or model operation.

The existing checksummed, gitignored bundle is the source for the replica. In
a private operator shell, an empty Neon database can be prepared and verified
without exposing a network import endpoint:

```powershell
$env:DATABASE_URL = "<NEON_DATABASE_URL>"
python -m alembic upgrade head
python -m scripts.import_public_demo_bundle --bundle var/deployment/public-demo-bundle.json
python -m scripts.verify_public_demo_database
Remove-Item Env:DATABASE_URL
```

The importer is transactional, and the verifier uses sanitized read-model
checks. There is no HTTP import route or Neon CLI dependency. The bundle,
database connection, and imported provider identifiers must never be
committed.

## Cloudflare Workers Static Assets

The frontend is built from `frontend/` with the public API origin embedded at
build time:

```powershell
Set-Location .\frontend
$env:VITE_ARC_API_BASE_URL = "https://arc-revenue-control.onrender.com"
npm run build
npx wrangler deploy
Remove-Item Env:VITE_ARC_API_BASE_URL
```

Wrangler reads the tracked `frontend/wrangler.jsonc`:

```json
{
  "name": "arc-revenue-control-ui",
  "compatibility_date": "2026-08-28",
  "assets": {
    "directory": "./dist",
    "not_found_handling": "single-page-application"
  }
}
```

The deployment publishes `frontend/dist/` as static assets at
`https://arc-revenue-control-ui.samarthpatilofc.workers.dev`. SPA fallback
makes direct refreshes of routes such as case decision traces resolve to the
React application. No Worker JavaScript runtime, API proxy, or Cloudflare Git
auto-deploy is configured by this repository. Generated `dist/` contents stay
ignored and untracked. Cloudflare authentication remains private operator
configuration; no token or account identifier belongs in Git.

Render CORS contains exactly the production frontend origin:

```json
["https://arc-revenue-control-ui.samarthpatilofc.workers.dev"]
```

Wildcard or localhost origins must not be added to the public service.

## Render Free cold starts

Render Free services may spin down after inactivity. The first request after
an idle period may take about a minute while the backend wakes; this is a
hosting limitation, not ARC's normal processing latency.

The frontend presents these bounded states:

```text
Checking backend…
Waking demo backend…
Operational
API unavailable
```

Only `GET /health` is retried, every 9 seconds, for at most 10 attempts—an
approximately 90-second bounded window. Polling stops immediately after
success or exhaustion. Exhaustion exposes a manual `Retry`. ARC sends no
keepalive traffic and uses no scheduled ping service.

If Overview data fails while health is checking or waking, the page explains
that the evaluator backend is waking and does not substitute fabricated data.

## Health, readiness, and verified evaluator state

`GET /health` is a process liveness probe and does not query PostgreSQL.
`GET /ready` performs a minimal database query. Database failure returns `503`
with a sanitized error and never exposes connection details or a traceback.

The live evaluator was manually verified end to end:

- `/health` returned the ARC API liveness response;
- `/ready` confirmed database readiness;
- Overview displayed persisted evidence;
- all five evidence cases and their decision traces loaded;
- both pending approval cases loaded;
- the provider-backed Test Mode recovery action loaded;
- the OpenAI-on-synthetic-input evidence route loaded without rerunning inference;
- direct refresh of a deep React route succeeded;
- the health badge reached `Operational`;
- no Razorpay or OpenAI operation ran during deployment.

The sanitized database verifier reported five cases, one provider-backed Test
Mode recovery attributed at ₹10.00, one OpenAI evidence case with zero OpenAI
executions or attributions, one already-captured protection, one hard stop,
two approval cases, and zero exposed provider identifiers or Payment Link
URLs.

## Source and CI

GitHub Actions validates backend migrations/tests and frontend lint, tests,
and production build on `main`. Render uses the repository's Docker service
configuration. The current frontend release was built locally and deployed as
Workers Static Assets through Wrangler; Cloudflare Git auto-deploy is not an
implementation claim.

## Limitations

The live endpoint is an evaluator/demo deployment, not a production merchant
system. It is intentionally read-only, uses a sanitized evidence replica, has
one backend process, and exposes no operational mutation controls. Render Free
cold starts can delay initial evaluator access. Production deployment would
require identity, authorization, tenant isolation, managed secrets,
observability, backup, and additional operational-security work.
