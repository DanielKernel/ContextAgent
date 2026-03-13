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
