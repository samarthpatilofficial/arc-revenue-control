FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system arc && useradd --system --gid arc arc

COPY pyproject.toml README.md ./
COPY arc ./arc
COPY services ./services
RUN python -m pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
COPY evaluation/results/latest.json ./evaluation/results/latest.json
COPY scripts ./scripts

RUN chmod 0555 scripts/start_backend.sh && chown -R arc:arc /app

USER arc

EXPOSE 8000

CMD ["sh", "scripts/start_backend.sh"]
