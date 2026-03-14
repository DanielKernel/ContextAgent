from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from context_agent.api.http_handler import create_app
from context_agent.core.monitoring.runtime_health import (
    ComponentHealthReport,
    RuntimeHealthReport,
)


class _StubHealthChecker:
    async def check(self, _api_router: object) -> RuntimeHealthReport:
        return RuntimeHealthReport(
            status="degraded",
            components={
                "contextagent": ComponentHealthReport(
                    name="contextagent",
                    status="ok",
                    detail="ready",
                    configured=True,
                ),
                "pgvector": ComponentHealthReport(
                    name="pgvector",
                    status="degraded",
                    detail="probe failed",
                    configured=True,
                ),
            },
        )


def test_health_endpoint_returns_component_diagnostics() -> None:
    app = create_app(api_router=SimpleNamespace(_runtime_health_checker=_StubHealthChecker()))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert "components" in data
    assert data["components"]["contextagent"]["status"] == "ok"
    assert data["components"]["pgvector"]["status"] == "degraded"


def test_app_lifespan_closes_router_resources() -> None:
    calls: list[str] = []

    class _Closable:
        def __init__(self, label: str) -> None:
            self._label = label

        async def close(self) -> None:
            calls.append(self._label)

    class _MemoryProcessor:
        async def start(self) -> None:
            calls.append("processor.start")

        async def stop(self) -> None:
            calls.append("processor.stop")

    router = SimpleNamespace(
        _runtime_health_checker=_StubHealthChecker(),
        _memory_processor=_MemoryProcessor(),
        _llm_adapter=_Closable("llm.close"),
        _aggregator=SimpleNamespace(_ltm=_Closable("ltm.close")),
    )

    with TestClient(create_app(api_router=router), raise_server_exceptions=False):
        pass

    assert calls == [
        "processor.start",
        "processor.stop",
        "llm.close",
        "ltm.close",
    ]


def test_v1_context_write_alias_uses_same_handler() -> None:
    class _Router:
        async def ingest_messages(self, **kwargs):
            self.kwargs = kwargs
            return True

    router = _Router()
    app = create_app(api_router=router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/v1/context/write",
        json={
            "scope_id": "scope-1",
            "session_id": "session-1",
            "content": "hello",
            "source_type": "user",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
