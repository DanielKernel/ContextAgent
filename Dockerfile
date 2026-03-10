# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /app
RUN pip install uv
COPY pyproject.toml ./
RUN uv sync --no-dev --extra pulsar

FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv .venv
COPY context_agent/ context_agent/

EXPOSE 8080

CMD ["python", "-m", "context_agent.api.http_handler"]
