"""Tests for openJiuwen configuration loading and default startup wiring."""

from __future__ import annotations

import pytest

from context_agent.api.router import ContextAPIRouter
from context_agent.config.openjiuwen import (
    _instantiate_long_term_memory,
    build_default_api_router,
    load_openjiuwen_config,
    resolve_openjiuwen_config_path,
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
    assert router._working_memory is not None
    assert router._memory_orchestrator is None


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
    assert router._working_memory is not None
    assert router._memory_orchestrator is not None
    assert router._memory_processor is not None


def test_build_default_api_router_falls_back_when_openjiuwen_unavailable(monkeypatch, tmp_path):
    config_path = tmp_path / "openjiuwen.yaml"
    config_path.write_text("user_id: context-agent\n", encoding="utf-8")

    def _raise(_path):
        raise ContextAgentError(
            "unsupported constructor",
            code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
        )

    monkeypatch.setattr(
        "context_agent.config.openjiuwen.build_openjiuwen_ltm_adapter",
        _raise,
    )

    router = build_default_api_router(
        settings=Settings(openjiuwen_config_path=str(config_path))
    )

    assert isinstance(router, ContextAPIRouter)
    assert router._aggregator._ltm is None
    assert router._working_memory is not None
    assert router._memory_orchestrator is None
    assert router._memory_processor is None


def test_build_default_api_router_uses_default_openjiuwen_path(monkeypatch, tmp_path):
    config_path = tmp_path / "openjiuwen.yaml"
    config_path.write_text("user_id: context-agent\n", encoding="utf-8")
    sentinel_adapter = object()

    monkeypatch.setattr(
        "context_agent.config.openjiuwen.DEFAULT_OPENJIUWEN_CONFIG_PATH",
        config_path,
    )
    monkeypatch.setattr(
        "context_agent.config.openjiuwen.build_openjiuwen_ltm_adapter",
        lambda path: sentinel_adapter,
    )

    router = build_default_api_router(settings=Settings(openjiuwen_config_path=""))

    assert router._aggregator._ltm is sentinel_adapter


def test_resolve_openjiuwen_config_path_uses_env(monkeypatch, tmp_path):
    config_path = tmp_path / "openjiuwen.yaml"
    config_path.write_text("user_id: context-agent\n", encoding="utf-8")
    monkeypatch.setenv("CA_OPENJIUWEN_CONFIG_PATH", str(config_path))

    assert resolve_openjiuwen_config_path() == config_path.resolve()


def test_instantiate_long_term_memory_with_config_keyword():
    class FakeLongTermMemory:
        def __init__(self, config):
            self.config = config

    instance = _instantiate_long_term_memory(FakeLongTermMemory, {"user_id": "u1"})
    assert instance.config == {"user_id": "u1"}


def test_instantiate_long_term_memory_with_positional_config():
    class FakeLongTermMemory:
        def __init__(self, settings):
            self.settings = settings

    instance = _instantiate_long_term_memory(FakeLongTermMemory, {"user_id": "u1"})
    assert instance.settings == {"user_id": "u1"}


def test_instantiate_long_term_memory_with_factory_method():
    class FakeLongTermMemory:
        def __init__(self):
            self.config = None

        @classmethod
        def from_config(cls, config):
            inst = cls()
            inst.config = config
            return inst

    instance = _instantiate_long_term_memory(FakeLongTermMemory, {"user_id": "u1"})
    assert instance.config == {"user_id": "u1"}


def test_instantiate_long_term_memory_with_expanded_kwargs():
    class FakeLongTermMemory:
        def __init__(self, user_id, vector_store, llm_config):
            self.user_id = user_id
            self.vector_store = vector_store
            self.llm_config = llm_config

    config = {
        "user_id": "u1",
        "vector_store": {"backend": "pgvector"},
        "llm_config": {"provider": "openai"},
    }
    instance = _instantiate_long_term_memory(FakeLongTermMemory, config)

    assert instance.user_id == "u1"
    assert instance.vector_store == {"backend": "pgvector"}
    assert instance.llm_config == {"provider": "openai"}
