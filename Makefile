.PHONY: lint type-check test test-int test-perf build clean clean-venv install venv venv-install venv-freeze venv-test venv-run run-dev format quickstart upgrade setup-openclaw uninstall-openclaw

PYTHON3 := python3
VENV_DIR := .venv
VENV_PYTHON := $(VENV_DIR)/bin/python3
VENV_PIP := $(VENV_DIR)/bin/pip
VERSION ?= $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
IMAGE_NAME := context-agent:$(VERSION)

# ── 虚拟环境（不依赖 uv）─────────────────────────────────────────────────────

## 创建 Python 3 虚拟环境（仅首次需要）
venv:
	$(PYTHON3) -m venv $(VENV_DIR)
	$(VENV_PIP) install --upgrade pip setuptools wheel

## 在虚拟环境中安装项目及开发依赖
venv-install: venv
	$(VENV_PIP) install -e ".[dev,openjiuwen]"

## 更新 requirements.txt 快照（venv-install 完成后运行）
venv-freeze:
	$(VENV_PIP) freeze > requirements.txt

## 在虚拟环境中运行单元测试
venv-test: venv-install
	$(VENV_PYTHON) -m pytest tests/unit/ -v --cov=context_agent --cov-report=term-missing -m "not integration and not performance"

## 在虚拟环境中启动开发服务
venv-run: venv-install
	$(VENV_PYTHON) -m uvicorn context_agent.api.http_handler:app --reload --host 0.0.0.0 --port 8080

## 默认安装命令
install: venv-install

lint: venv-install
	$(VENV_PYTHON) -m ruff check context_agent/ tests/
	$(VENV_PYTHON) -m ruff format --check context_agent/ tests/

format: venv-install
	$(VENV_PYTHON) -m ruff check --fix context_agent/ tests/
	$(VENV_PYTHON) -m ruff format context_agent/ tests/

type-check: venv-install
	$(VENV_PYTHON) -m mypy context_agent/

test: venv-test

test-int: venv-install
	$(VENV_PYTHON) -m pytest tests/integration/ -v -m integration

test-perf: venv-install
	$(VENV_PYTHON) -m pytest tests/performance/ -v --benchmark-only -m performance

test-all: venv-install
	$(VENV_PYTHON) -m pytest tests/ -v --cov=context_agent --cov-report=term-missing --cov-report=html

build:
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE_NAME) .

clean:
	rm -rf dist/ .coverage htmlcov/ .mypy_cache/ .ruff_cache/ __pycache__/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

clean-venv: clean
	rm -rf $(VENV_DIR)

run-dev: venv-run

# ── 一键脚本 ─────────────────────────────────────────────────────────────────

## 一键安装 ContextAgent 并启动服务
quickstart:
	bash scripts/install.sh --start

## 一键升级 ContextAgent（保留历史配置和数据）
upgrade:
	bash scripts/upgrade.sh

## 一键对接 OpenClaw（ContextAgent 服务需已启动）
setup-openclaw:
	bash scripts/setup-openclaw.sh

## 移除 OpenClaw 对接
uninstall-openclaw:
	bash scripts/setup-openclaw.sh --uninstall
