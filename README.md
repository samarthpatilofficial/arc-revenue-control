# ARC — Autonomous Revenue Control

This repository currently contains the backend foundation for ARC: a FastAPI application, typed environment configuration, PostgreSQL/SQLAlchemy infrastructure, Alembic migrations, and automated tests.

## Local setup

Requirements: Python 3.12+, Docker, and Docker Compose.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
docker compose up -d postgres
python -m alembic upgrade head
python -m uvicorn services.api.main:app --reload
```

The API is available at `http://localhost:8000`. Its liveness endpoint is:

```text
GET /health
```

Run the tests with:

```powershell
python -m pytest
```

Stop the local database with `docker compose down`. Add `--volumes` only when you intentionally want to remove local PostgreSQL data.
