.PHONY: lint type-check test test-int test-perf build clean install

PYTHON := python
UV := uv
VERSION ?= $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
IMAGE_NAME := context-agent:$(VERSION)

install:
	$(UV) sync --extra dev

lint:
	$(UV) run ruff check context_agent/ tests/
	$(UV) run ruff format --check context_agent/ tests/

format:
	$(UV) run ruff check --fix context_agent/ tests/
	$(UV) run ruff format context_agent/ tests/

type-check:
	$(UV) run mypy context_agent/

test:
	$(UV) run pytest tests/unit/ -v --cov=context_agent --cov-report=term-missing -m "not integration and not performance"

test-int:
	$(UV) run pytest tests/integration/ -v -m integration

test-perf:
	$(UV) run pytest tests/performance/ -v --benchmark-only -m performance

test-all:
	$(UV) run pytest tests/ -v --cov=context_agent --cov-report=term-missing --cov-report=html

build:
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE_NAME) .

clean:
	rm -rf dist/ .coverage htmlcov/ .mypy_cache/ .ruff_cache/ __pycache__/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

run-dev:
	$(UV) run uvicorn context_agent.api.http_handler:app --reload --host 0.0.0.0 --port 8080
