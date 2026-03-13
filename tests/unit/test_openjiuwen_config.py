"""Tests for openJiuwen configuration loading and default startup wiring."""

from __future__ import annotations

import importlib

import pytest

from context_agent.api.router import ContextAPIRouter
from context_agent.config.openjiuwen import (
    _bootstrap_long_term_memory,
    _build_db_store,
    _build_model_configs,
    _expand_env_placeholders,
    _instantiate_long_term_memory,
    _instantiate_vector_store,
    _normalize_async_dsn,
    build_default_llm_adapter,
    build_default_api_router,
    load_openjiuwen_config,
    resolve_openjiuwen_config_path,
)
from context_agent.config.settings import Settings
from context_agent.core.monitoring.runtime_health import RuntimeDependencyHealthChecker
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
    assert isinstance(router._runtime_health_checker, RuntimeDependencyHealthChecker)


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
    assert isinstance(router._runtime_health_checker, RuntimeDependencyHealthChecker)


def test_build_default_api_router_wires_llm_adapter(monkeypatch):
    from context_agent.strategies.registry import StrategyRegistry

    StrategyRegistry.reset()

    class FakeLLMAdapter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "context_agent.config.openjiuwen.HttpLLMAdapter",
        FakeLLMAdapter,
    )

    router = build_default_api_router(
        settings=Settings(
            openjiuwen_config_path="",
            llm_base_url="https://llm.example.com",
            llm_model="demo-model",
            llm_api_key="top-secret",
        )
    )

    qa_strategy = router._compression._registry.get("qa")

    assert isinstance(qa_strategy._llm, FakeLLMAdapter)
    assert qa_strategy._llm.kwargs["base_url"] == "https://llm.example.com"
    assert qa_strategy._llm.kwargs["model"] == "demo-model"
    assert qa_strategy._llm.kwargs["api_key"] == "top-secret"

    StrategyRegistry.reset()


def test_build_default_api_router_prefers_openjiuwen_llm_when_settings_are_defaults(monkeypatch, tmp_path):
    from context_agent.strategies.registry import StrategyRegistry

    StrategyRegistry.reset()

    config_path = tmp_path / "openjiuwen.yaml"
    config_path.write_text(
        "\n".join(
            [
                "user_id: context-agent",
                "llm_config:",
                "  provider: openai",
                "  model: actual-model",
                "  api_key: actual-key",
                "  base_url: https://actual-llm.example.com",
            ]
        ),
        encoding="utf-8",
    )

    class FakeLLMAdapter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "context_agent.config.openjiuwen.HttpLLMAdapter",
        FakeLLMAdapter,
    )
    monkeypatch.setattr(
        "context_agent.config.openjiuwen.build_openjiuwen_ltm_adapter",
        lambda _path: object(),
    )

    router = build_default_api_router(settings=Settings(openjiuwen_config_path=str(config_path)))
    qa_strategy = router._compression._registry.get("qa")

    assert isinstance(qa_strategy._llm, FakeLLMAdapter)
    assert qa_strategy._llm.kwargs["base_url"] == "https://actual-llm.example.com"
    assert qa_strategy._llm.kwargs["model"] == "actual-model"
    assert qa_strategy._llm.kwargs["api_key"] == "actual-key"

    StrategyRegistry.reset()


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


def test_build_default_llm_adapter_returns_none_for_blank_endpoint():
    adapter = build_default_llm_adapter(
        Settings(llm_base_url="", llm_model="demo-model")
    )

    assert adapter is None


def test_build_default_llm_adapter_returns_none_when_defaults_should_defer_to_openjiuwen():
    adapter = build_default_llm_adapter(
        Settings(),
        {
            "llm_config": {
                "model": "${CTXLLM_MODEL}",
                "base_url": "${CTXLLM_BASE_URL}",
            }
        },
    )

    assert adapter is None


def test_resolve_openjiuwen_config_path_uses_env(monkeypatch, tmp_path):
    config_path = tmp_path / "openjiuwen.yaml"
    config_path.write_text("user_id: context-agent\n", encoding="utf-8")
    monkeypatch.setenv("CA_OPENJIUWEN_CONFIG_PATH", str(config_path))

    assert resolve_openjiuwen_config_path() == config_path.resolve()


def test_resolve_openjiuwen_config_path_prefers_runtime_default(monkeypatch, tmp_path):
    runtime_config = tmp_path / ".local" / "config" / "openjiuwen.yaml"
    runtime_config.parent.mkdir(parents=True)
    runtime_config.write_text("user_id: runtime\n", encoding="utf-8")
    repo_template = tmp_path / "config" / "openjiuwen.yaml"
    repo_template.parent.mkdir()
    repo_template.write_text("user_id: template\n", encoding="utf-8")

    monkeypatch.delenv("CA_OPENJIUWEN_CONFIG_PATH", raising=False)
    monkeypatch.setattr(
        "context_agent.config.openjiuwen.DEFAULT_OPENJIUWEN_CONFIG_PATH",
        runtime_config,
    )
    monkeypatch.setattr(
        "context_agent.config.openjiuwen.REPOSITORY_OPENJIUWEN_TEMPLATE_PATH",
        repo_template,
    )

    assert resolve_openjiuwen_config_path() == runtime_config.resolve()


def test_resolve_openjiuwen_config_path_falls_back_to_repo_template(monkeypatch, tmp_path):
    runtime_config = tmp_path / ".local" / "config" / "openjiuwen.yaml"
    repo_template = tmp_path / "config" / "openjiuwen.yaml"
    repo_template.parent.mkdir()
    repo_template.write_text("user_id: template\n", encoding="utf-8")

    monkeypatch.delenv("CA_OPENJIUWEN_CONFIG_PATH", raising=False)
    monkeypatch.setattr(
        "context_agent.config.openjiuwen.DEFAULT_OPENJIUWEN_CONFIG_PATH",
        runtime_config,
    )
    monkeypatch.setattr(
        "context_agent.config.openjiuwen.REPOSITORY_OPENJIUWEN_TEMPLATE_PATH",
        repo_template,
    )

    assert resolve_openjiuwen_config_path() == repo_template.resolve()


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


def test_instantiate_long_term_memory_with_no_arg_constructor():
    class FakeLongTermMemory:
        def __init__(self):
            self.ready = True

    instance = _instantiate_long_term_memory(FakeLongTermMemory, {"user_id": "u1"})
    assert instance.ready is True


def test_expand_env_placeholders_recursively(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    config = {
        "llm_config": {"api_key": "${OPENAI_API_KEY}"},
        "nested": ["${OPENAI_API_KEY}"],
    }

    expanded = _expand_env_placeholders(config)

    assert expanded["llm_config"]["api_key"] == "secret"
    assert expanded["nested"] == ["secret"]


def test_normalize_async_dsn_for_postgres():
    dsn = "postgresql://postgres@127.0.0.1:55432/context_agent?sslmode=disable"

    normalized = _normalize_async_dsn(dsn)

    assert normalized == "postgresql+asyncpg://postgres@127.0.0.1:55432/context_agent?ssl=false"


def test_normalize_async_dsn_maps_required_ssl_modes():
    dsn = "postgresql://postgres@127.0.0.1:55432/context_agent?sslmode=require"

    normalized = _normalize_async_dsn(dsn)

    assert normalized == "postgresql+asyncpg://postgres@127.0.0.1:55432/context_agent?ssl=true"


def test_build_db_store_reports_missing_asyncpg(monkeypatch):
    def _raise_missing_asyncpg(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'asyncpg'", name="asyncpg")

    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.create_async_engine",
        _raise_missing_asyncpg,
    )
    monkeypatch.setattr(
        "context_agent.config.openjiuwen._import_openjiuwen_symbol",
        lambda module_name, symbol_name: object,
    )

    with pytest.raises(ContextAgentError) as exc:
        _build_db_store({"dsn": "postgresql://localhost/context_agent"})

    assert exc.value.code == ErrorCode.OPENJIUWEN_UNAVAILABLE
    assert exc.value.details["missing_dependency"] == "asyncpg"


def test_build_kv_store_patches_openjiuwen_sqlite_insert_for_postgres(monkeypatch):
    from context_agent.config.openjiuwen import _build_kv_store
    from context_agent.adapters.openjiuwen_db_kv_store import OpenJiuwenDbBasedKVStoreCompat

    fake_engine = type("Engine", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

    store = _build_kv_store(fake_engine)

    assert isinstance(store, OpenJiuwenDbBasedKVStoreCompat)


def test_build_model_configs_supplies_default_ssl_cert(monkeypatch, tmp_path):
    cert_path = tmp_path / "ca.pem"
    cert_path.write_text("dummy cert", encoding="utf-8")

    class FakeModelRequestConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeModelClientConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def _fake_import(module_name, symbol_name):
        if symbol_name == "ModelRequestConfig":
            return FakeModelRequestConfig
        if symbol_name == "ModelClientConfig":
            return FakeModelClientConfig
        raise AssertionError((module_name, symbol_name))

    monkeypatch.setattr(
        "context_agent.config.openjiuwen._import_openjiuwen_symbol",
        _fake_import,
    )
    monkeypatch.setattr(
        "certifi.where",
        lambda: str(cert_path),
    )
    monkeypatch.setattr(
        "context_agent.config.openjiuwen.ssl.get_default_verify_paths",
        lambda: type("Paths", (), {"cafile": str(cert_path)})(),
    )

    request_config, client_config = _build_model_configs(
        {
            "llm_config": {
                "provider": "openai",
                "model": "demo-model",
                "api_key": "secret",
                "base_url": "https://llm.example.com",
            }
        }
    )

    assert request_config.kwargs["model"] == "demo-model"
    assert client_config.kwargs["verify_ssl"] is True
    assert client_config.kwargs["ssl_cert"] == str(cert_path)


def test_build_model_configs_preserves_explicit_ssl_settings(monkeypatch):
    class FakeModelRequestConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeModelClientConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def _fake_import(module_name, symbol_name):
        if symbol_name == "ModelRequestConfig":
            return FakeModelRequestConfig
        if symbol_name == "ModelClientConfig":
            return FakeModelClientConfig
        raise AssertionError((module_name, symbol_name))

    monkeypatch.setattr(
        "context_agent.config.openjiuwen._import_openjiuwen_symbol",
        _fake_import,
    )

    _, client_config = _build_model_configs(
        {
            "llm_config": {
                "provider": "openai",
                "model": "demo-model",
                "api_key": "secret",
                "base_url": "https://llm.example.com",
                "verify_ssl": False,
            }
        }
    )

    assert client_config.kwargs["verify_ssl"] is False
    assert client_config.kwargs["ssl_cert"] is None


@pytest.mark.asyncio
async def test_bootstrap_long_term_memory_does_not_require_dsn_for_non_pgvector(monkeypatch):
    class FakeLongTermMemory:
        async def register_store(self, **kwargs):
            self.kwargs = kwargs

        def set_config(self, config):
            self.config = config

        async def set_scope_config(self, user_id, config):
            self.user_id = user_id
            self.scope_config = config

    monkeypatch.setattr(
        "context_agent.config.openjiuwen._import_openjiuwen_symbol",
        lambda module_name, symbol_name: (
            type("InMemoryKVStore", (), {})
            if module_name == "openjiuwen.core.foundation.store.kv.in_memory_kv_store"
            else object
        ),
    )

    def _raise_backend_unavailable(_backend, _vector_store_config):
        raise ContextAgentError(
            "backend unavailable",
            code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
        )

    monkeypatch.setattr(
        "context_agent.config.openjiuwen._instantiate_vector_store",
        _raise_backend_unavailable,
    )

    with pytest.raises(ContextAgentError) as exc:
        await _bootstrap_long_term_memory(
            FakeLongTermMemory(),
            {
                "user_id": "context-agent",
                "vector_store": {"backend": "qdrant"},
            },
        )

    assert exc.value.code == ErrorCode.OPENJIUWEN_UNAVAILABLE


def test_instantiate_vector_store_reports_missing_pgvector_dependency(monkeypatch):
    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: type("StoreModule", (), {"create_vector_store": lambda *_args, **_kwargs: None})()
        if name == "openjiuwen.core.foundation.store"
        else __import__(name),
    )

    def _raise_missing_pgvector(module_name, symbol_name):
        if module_name == "openjiuwen.core.retrieval.vector_store.pg_store":
            raise ModuleNotFoundError("No module named 'pgvector'", name="pgvector")
        raise ModuleNotFoundError(module_name, name=module_name)

    monkeypatch.setattr(
        "context_agent.config.openjiuwen._import_openjiuwen_symbol",
        _raise_missing_pgvector,
    )

    with pytest.raises(ContextAgentError) as exc:
        _instantiate_vector_store(
            "pgvector",
            {
                "dsn": "postgresql://localhost/context_agent",
                "table_name": "ltm_memory",
                "schema": "public",
                "embedding_dimension": 3072,
            },
        )

    assert exc.value.code == ErrorCode.OPENJIUWEN_UNAVAILABLE
    assert exc.value.details["missing_dependency"] == "pgvector"


def test_instantiate_vector_store_uses_pgvector_bridge(monkeypatch):
    class FakeBridge:
        def __init__(self, config):
            self.config = config

    original_import_module = importlib.import_module
    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: type("StoreModule", (), {"create_vector_store": lambda *_args, **_kwargs: None})()
        if name == "openjiuwen.core.foundation.store"
        else original_import_module(name),
    )
    monkeypatch.setattr(
        "context_agent.adapters.openjiuwen_pgvector_store.OpenJiuwenPGVectorStoreBridge",
        FakeBridge,
    )

    def _fake_import(module_name, symbol_name):
        if module_name == "openjiuwen.core.retrieval.vector_store.pg_store":
            return object
        raise ModuleNotFoundError(module_name, name=module_name)

    monkeypatch.setattr(
        "context_agent.config.openjiuwen._import_openjiuwen_symbol",
        _fake_import,
    )

    store = _instantiate_vector_store(
        "pgvector",
        {
            "dsn": "postgresql://postgres@127.0.0.1:55432/context_agent?sslmode=disable",
            "table_name": "ltm_memory",
            "distance": "cosine",
        },
    )

    assert isinstance(store, FakeBridge)
    assert store.config["dsn"] == "postgresql+asyncpg://postgres@127.0.0.1:55432/context_agent?ssl=false"
