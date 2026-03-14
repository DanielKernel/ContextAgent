from __future__ import annotations

from types import SimpleNamespace

import pytest
from _pytest.monkeypatch import MonkeyPatch

from context_agent.config.settings import Settings
from context_agent.core.monitoring.runtime_health import RuntimeDependencyHealthChecker


class _HealthyLTM:
    async def health_check(self) -> bool:
        return True


class _HealthyLLM:
    _model = "demo-llm"

    async def health_check(self) -> bool:
        return True


class _HealthyEmbedding:
    async def embed_query(self, _text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _FailingLLM:
    _model = "actual-model"

    async def health_check(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_runtime_health_checker_reports_all_components_healthy(
    monkeypatch: MonkeyPatch,
) -> None:
    router = SimpleNamespace(
        _aggregator=SimpleNamespace(_ltm=_HealthyLTM()),
        _working_memory=object(),
        _memory_processor=SimpleNamespace(_running=True),
        _llm_adapter=_HealthyLLM(),
    )
    checker = RuntimeDependencyHealthChecker(
        settings=Settings(llm_base_url="https://llm.example.com", llm_model="demo-llm"),
        openjiuwen_config={
            "vector_store": {
                "backend": "pgvector",
                "schema": "public",
                "table_name": "ltm_memory",
            },
            "embedding_config": {
                "model": "demo-embedding",
                "base_url": "https://embed.example.com/v1/embeddings",
            },
        },
        llm_adapter=router._llm_adapter,
    )
    monkeypatch.setattr(
        "context_agent.config.openjiuwen._build_embedding_model",
        lambda _config: _HealthyEmbedding(),
    )

    report = await checker.check(router)

    assert report.status == "ok"
    assert report.components["contextagent"].status == "ok"
    assert report.components["environment"].status == "ok"
    assert report.components["pgvector"].status == "ok"
    assert report.components["llm"].status == "ok"
    assert report.components["embedding"].status == "ok"
    assert report.components["embedding"].metadata["dimension"] == 3


@pytest.mark.asyncio
async def test_runtime_health_checker_flags_pgvector_when_configured_but_missing_adapter() -> None:
    router = SimpleNamespace(
        _aggregator=SimpleNamespace(_ltm=None),
        _working_memory=object(),
        _memory_processor=None,
    )
    checker = RuntimeDependencyHealthChecker(
        settings=Settings(),
        openjiuwen_config={
            "vector_store": {
                "backend": "pgvector",
                "schema": "public",
                "table_name": "ltm_memory",
            }
        },
    )

    report = await checker.check(router)

    assert report.status == "degraded"
    assert report.components["pgvector"].status == "degraded"
    assert "unavailable" in report.components["pgvector"].detail


@pytest.mark.asyncio
async def test_runtime_health_checker_skips_unconfigured_embedding() -> None:
    checker = RuntimeDependencyHealthChecker(
        settings=Settings(openjiuwen_config_path=""),
        openjiuwen_config={"vector_store": {"backend": "pgvector"}},
    )

    report = await checker.check(
        SimpleNamespace(
            _aggregator=SimpleNamespace(_ltm=_HealthyLTM()),
            _working_memory=object(),
            _memory_processor=None,
        )
    )

    assert report.components["embedding"].status == "skipped"
    assert report.components["embedding"].configured is False


@pytest.mark.asyncio
async def test_runtime_health_checker_skips_unresolved_embedding_placeholders() -> None:
    checker = RuntimeDependencyHealthChecker(
        settings=Settings(openjiuwen_config_path=""),
        openjiuwen_config={
            "vector_store": {"backend": "pgvector"},
            "embedding_config": {
                "model": "${EMBED_MODEL}",
                "base_url": "${EMBED_BASE_URL}",
            },
        },
    )

    report = await checker.check(
        SimpleNamespace(
            _aggregator=SimpleNamespace(_ltm=_HealthyLTM()),
            _working_memory=object(),
            _memory_processor=None,
        )
    )

    assert report.components["embedding"].status == "skipped"
    assert "unresolved environment placeholders" in report.components["embedding"].detail


@pytest.mark.asyncio
async def test_runtime_health_checker_uses_openjiuwen_llm_config_when_settings_are_defaults() -> (
    None
):
    checker = RuntimeDependencyHealthChecker(
        settings=Settings(),
        openjiuwen_config={
            "vector_store": {"backend": "pgvector"},
            "llm_config": {
                "provider": "openai",
                "model": "actual-model",
                "base_url": "https://actual-llm.example.com",
                "api_key": "secret",
            },
        },
        llm_adapter=_FailingLLM(),
    )

    report = await checker.check(
        SimpleNamespace(
            _aggregator=SimpleNamespace(_ltm=_HealthyLTM()),
            _working_memory=object(),
            _memory_processor=None,
            _llm_adapter=_FailingLLM(),
        )
    )

    assert report.components["llm"].metadata["model"] == "actual-model"


@pytest.mark.asyncio
async def test_runtime_health_checker_flags_unresolved_environment_placeholders(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("CTXLLM_MODEL", raising=False)
    monkeypatch.delenv("CTXLLM_BASE_URL", raising=False)
    monkeypatch.delenv("CTXLLM_API_KEY", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_BASE_URL", raising=False)

    checker = RuntimeDependencyHealthChecker(
        settings=Settings(),
        openjiuwen_config={
            "llm_config": {
                "model": "${CTXLLM_MODEL}",
                "base_url": "${CTXLLM_BASE_URL}",
                "api_key": "${CTXLLM_API_KEY}",
            },
            "embedding_config": {
                "model": "${EMBED_MODEL}",
                "base_url": "${EMBED_BASE_URL}",
            },
            "vector_store": {"backend": "pgvector"},
        },
    )

    report = await checker.check(
        SimpleNamespace(
            _aggregator=SimpleNamespace(_ltm=_HealthyLTM()),
            _working_memory=object(),
            _memory_processor=None,
        )
    )

    assert report.status == "degraded"
    assert report.components["environment"].status == "degraded"
    assert report.components["environment"].metadata["missing_vars"] == (
        "CTXLLM_API_KEY,CTXLLM_BASE_URL,CTXLLM_MODEL,EMBED_BASE_URL,EMBED_MODEL"
    )


@pytest.mark.asyncio
async def test_runtime_health_checker_accepts_resolved_environment_placeholders(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CTXLLM_MODEL", "demo-llm")
    monkeypatch.setenv("CTXLLM_BASE_URL", "https://llm.example.com")
    monkeypatch.setenv("CTXLLM_API_KEY", "secret")
    monkeypatch.setenv("EMBED_MODEL", "demo-embedding")
    monkeypatch.setenv("EMBED_BASE_URL", "https://embed.example.com")

    checker = RuntimeDependencyHealthChecker(
        settings=Settings(),
        openjiuwen_config={
            "llm_config": {
                "model": "${CTXLLM_MODEL}",
                "base_url": "${CTXLLM_BASE_URL}",
                "api_key": "${CTXLLM_API_KEY}",
            },
            "embedding_config": {
                "model": "${EMBED_MODEL}",
                "base_url": "${EMBED_BASE_URL}",
            },
            "vector_store": {"backend": "pgvector"},
        },
    )

    report = await checker.check(
        SimpleNamespace(
            _aggregator=SimpleNamespace(_ltm=_HealthyLTM()),
            _working_memory=object(),
            _memory_processor=None,
        )
    )

    assert report.components["environment"].status == "ok"
    assert report.components["environment"].metadata["vars"] == (
        "CTXLLM_API_KEY,CTXLLM_BASE_URL,CTXLLM_MODEL,EMBED_BASE_URL,EMBED_MODEL"
    )
