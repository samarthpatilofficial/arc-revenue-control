# ARC — Autonomous Revenue Control

This repository currently contains the backend foundation for ARC: a FastAPI application, typed environment configuration, PostgreSQL/SQLAlchemy infrastructure, Alembic migrations, an immutable external event ledger, and automated tests for the core persistence schema.

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

Run the tests with:

```powershell
python -m pytest
```

If using Compose, stop its database with `docker compose down`. Add `--volumes` only when you intentionally want to remove local PostgreSQL data.
