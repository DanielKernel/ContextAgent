# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY context_agent/ context_agent/
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip setuptools wheel \
    && /app/.venv/bin/pip install ".[pulsar,openjiuwen]"

FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv .venv
COPY context_agent/ context_agent/
COPY README.md pyproject.toml ./

EXPOSE 8080

CMD ["python", "-m", "context_agent.api.http_handler"]
