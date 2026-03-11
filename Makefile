.PHONY: lint type-check test test-int test-perf build clean clean-venv install venv venv-install venv-test venv-run

PYTHON3 := python3
VENV_DIR := .venv
VENV_PYTHON := $(VENV_DIR)/bin/python3
VENV_PIP := $(VENV_DIR)/bin/pip
UV := uv
VERSION ?= $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
IMAGE_NAME := context-agent:$(VERSION)

# ── 虚拟环境（不依赖 uv）─────────────────────────────────────────────────────

## 创建 Python 3 虚拟环境（仅首次需要）
venv:
	$(PYTHON3) -m venv $(VENV_DIR)
	$(VENV_PIP) install --upgrade pip setuptools wheel

## 在虚拟环境中安装项目及开发依赖（不需要 uv）
venv-install: venv
	$(VENV_PIP) install -e ".[dev]"

## 在虚拟环境中运行单元测试（不需要 uv）
venv-test:
	$(VENV_PYTHON) -m pytest tests/unit/ -v --cov=context_agent --cov-report=term-missing -m "not integration and not performance"

## 在虚拟环境中启动开发服务（不需要 uv）
venv-run:
	$(VENV_PYTHON) -m uvicorn context_agent.api.http_handler:app --reload --host 0.0.0.0 --port 8080

# ── uv（推荐，自动管理 .venv）────────────────────────────────────────────────

## 使用 uv 安装所有依赖（自动创建 .venv）
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

clean-venv: clean
	rm -rf $(VENV_DIR)

run-dev:
	$(UV) run uvicorn context_agent.api.http_handler:app --reload --host 0.0.0.0 --port 8080
