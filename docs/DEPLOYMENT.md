# ARC Deployment

## Architecture

ARC's evaluator deployment keeps the existing product boundaries:

```text
GitHub main
  |-- Cloudflare Pages (frontend/, static React/Vite, HTTPS *.pages.dev)
  `-- Northflank combined service (root Dockerfile, FastAPI, HTTPS *.code.run)
        `-- Northflank PostgreSQL 18 addon (private networking only)
```

The frontend reads the backend origin from `VITE_ARC_API_BASE_URL`. The
backend reads its private PostgreSQL connection from `DATABASE_URL`. No proxy,
Pages Function, Worker, queue, or additional hosting provider is involved.

## Public-demo safety boundary

`ARC_PUBLIC_DEMO_MODE=true` creates an evaluator-only HTTP boundary. Liveness,
readiness, evaluation, dashboard, case, timeline, approval-list, and
recovery-action-list reads remain available. Razorpay webhook ingress is not
registered, and there are no HTTP approval, execution, OpenAI, or seeding
routes.

Public-demo mode fails startup when `ARC_DEMO_MODE=true` or when any OpenAI,
Razorpay API, or Razorpay webhook credential is configured. Credentials are
rejected rather than ignored so accidental external access is impossible.
The hosted service therefore needs no provider credential.

This boundary is for a read-only evaluator replica. Internal domain services
remain available to trusted operator CLIs and normal local development when
public-demo mode is false.

## Backend container

Northflank builds the root `Dockerfile` from the repository root. It uses
Python 3.12 slim, installs the project from `pyproject.toml` without development
dependencies, runs as an unprivileged user, and exposes port `8000`.

The container starts with:

```text
python -m alembic upgrade head
python -m uvicorn services.api.main:app --host 0.0.0.0 --port 8000
```

The startup script uses `set -eu` and `exec`. A failed migration stops startup;
the API is never served against an outdated schema.

## Database migration

The Northflank service applies all committed Alembic revisions to its private
database before Uvicorn starts. Evidence import happens only after the empty
database is migrated.

## Evidence replica

The public evaluator database is a sanitized replica of the accepted persisted
Razorpay Test Mode, genuine OpenAI-on-synthetic-input, and controlled offline
demo evidence. Deployment does not rerun provider or model actions. A copied
Test Mode snapshot does not mean a new provider operation happened in
Northflank.

The operator-only workflow is:

```text
local accepted PostgreSQL
  -> explicit read-only export
  -> versioned checksummed JSON bundle (gitignored)
  -> secure private-database forwarding
  -> transactional import into an empty migrated database
  -> read-model verification
```

No webhook payload, raw prompt/model response, secret, Payment Link URL, real
provider identifier, or customer identifier is included.

The explicit local commands are:

```powershell
python -m scripts.export_public_demo_bundle
python -m scripts.import_public_demo_bundle --bundle var/deployment/public-demo-bundle.json
python -m scripts.verify_public_demo_database
```

The first command reads the configured accepted database in a PostgreSQL
read-only transaction. The latter two use the `DATABASE_URL` configured in the
private operator shell for the forwarded cloud database.

## Cloudflare Pages configuration

Use these fields in a Cloudflare Pages project:

| Field | Value |
| --- | --- |
| Repository | `samarthpatilofficial/arc-revenue-control` |
| Production branch | `main` |
| Root directory | `frontend` |
| Framework preset | React / Vite |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variable | `VITE_ARC_API_BASE_URL=https://<NORTHFLANK_BACKEND_HOST>` |

The build is a static React Router SPA. Cloudflare Pages serves SPA fallback
for this build because it contains no top-level `404.html`; no routing function
or worker is required.

## Northflank configuration

Create one evaluator/demo project, using Asia South / Delhi when the account
offers it.

Database addon:

| Field | Value |
| --- | --- |
| Addon | PostgreSQL 18 |
| Networking | Private only; **not publicly accessible** |
| TLS | Preferred when compatible with the private connection configuration |

Combined backend service:

| Field | Value |
| --- | --- |
| Source | GitHub repository, `main` branch |
| Build type | Dockerfile |
| Build context | Repository root |
| Dockerfile path | `./Dockerfile` |
| Public HTTP port | `8000` |
| Domain | Northflank-generated HTTPS `*.code.run` |
| CI/CD | Deploy from `main` |

Keep the service and PostgreSQL addon in the same Northflank project and bind
`DATABASE_URL` from the addon's private connection details.

## Environment variable names

Northflank runtime:

```text
ARC_PUBLIC_DEMO_MODE
ARC_DEMO_MODE
DEBUG
DATABASE_URL
CORS_ALLOWED_ORIGINS
```

Required values are `ARC_PUBLIC_DEMO_MODE=true`, `ARC_DEMO_MODE=false`, and
`DEBUG=false`. `CORS_ALLOWED_ORIGINS` must be a JSON array containing only the
final Cloudflare Pages production origin. Do not configure localhost, a
wildcard, OpenAI credentials, Razorpay API credentials, or webhook secrets.

Cloudflare build:

```text
VITE_ARC_API_BASE_URL
```

## Secure evidence import

1. Run the explicit exporter against the accepted local database.
2. Verify the reported bundle checksum and that the file remains ignored.
3. Use the official Northflank CLI secure forwarding mechanism to forward the
   private PostgreSQL addon to the operator machine temporarily. Do not enable
   the addon's public-access option.
4. Point a private operator shell's `DATABASE_URL` at that forwarded endpoint.
5. Run Alembic, then the bundle importer with its explicit bundle path.
6. Run the public-demo database verifier.
7. Stop the forwarding session.

The import is a CLI operation only. There is no HTTP import or seed endpoint.

## CORS rollout sequence

1. Deploy Northflank first with `CORS_ALLOWED_ORIGINS=[]`.
2. Obtain the generated `*.code.run` HTTPS backend URL.
3. Create Cloudflare Pages with that URL as `VITE_ARC_API_BASE_URL`.
4. Obtain the production `*.pages.dev` URL.
5. Set Northflank `CORS_ALLOWED_ORIGINS` to the JSON array containing exactly
   that HTTPS Pages origin.
6. Redeploy or restart the backend, then rebuild Pages only if its backend URL
   changed.

This sequence never needs temporary wildcard CORS.

## Health and readiness

`GET /health` is a process liveness probe and does not query PostgreSQL.
`GET /ready` performs a minimal database query. Database failure returns `503`
with a sanitized error and never exposes host, database, username, driver,
connection URL, or traceback.

## CI/CD

GitHub Actions continues to run backend migrations/tests and frontend lint,
tests, and production build on `main`. Northflank performs the authoritative
container build and deploy. Cloudflare Pages builds the static frontend from
the same accepted commit.

## Limitations

This is an evaluator/demo deployment, not a production merchant environment.
It is intentionally read-only, uses a sanitized evidence replica, has one
backend process, and does not expose operational mutation controls. Production
merchant deployment would require separate identity, authorization, secret
management, observability, backup, and operational-security work.
