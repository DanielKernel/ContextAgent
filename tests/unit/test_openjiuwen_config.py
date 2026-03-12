"""Tests for openJiuwen configuration loading and default startup wiring."""

from __future__ import annotations

import pytest

from context_agent.api.router import ContextAPIRouter
from context_agent.config.openjiuwen import (
    build_default_api_router,
    load_openjiuwen_config,
)
from context_agent.config.settings import Settings
from context_agent.utils.errors import ContextAgentError, ErrorCode


def test_load_openjiuwen_yaml_config(tmp_path):
    config_path = tmp_path / "openjiuwen.yaml"
    config_path.write_text(
        """
user_id: context-agent
vector_store:
  backend: pgvector
  dsn: postgresql://localhost/context_agent
""".strip(),
        encoding="utf-8",
    )

    config = load_openjiuwen_config(config_path)

    assert config["user_id"] == "context-agent"
    assert config["vector_store"]["backend"] == "pgvector"


def test_load_openjiuwen_config_rejects_unsupported_format(tmp_path):
    config_path = tmp_path / "openjiuwen.toml"
    config_path.write_text("user_id = 'context-agent'", encoding="utf-8")

    with pytest.raises(ContextAgentError) as exc:
        load_openjiuwen_config(config_path)

    assert exc.value.code == ErrorCode.CONFIGURATION_ERROR


def test_build_default_api_router_without_openjiuwen_config():
    router = build_default_api_router(settings=Settings(openjiuwen_config_path=""))

    assert isinstance(router, ContextAPIRouter)
    assert router._aggregator._ltm is None


def test_build_default_api_router_uses_openjiuwen_adapter(monkeypatch, tmp_path):
    config_path = tmp_path / "openjiuwen.yaml"
    config_path.write_text("user_id: context-agent\n", encoding="utf-8")
    sentinel_adapter = object()

    monkeypatch.setattr(
        "context_agent.config.openjiuwen.build_openjiuwen_ltm_adapter",
        lambda path: sentinel_adapter,
    )

    router = build_default_api_router(
        settings=Settings(openjiuwen_config_path=str(config_path))
    )

    assert router._aggregator._ltm is sentinel_adapter
