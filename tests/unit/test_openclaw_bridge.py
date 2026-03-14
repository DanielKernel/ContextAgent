"""Unit tests for the OpenClaw bridge (Python side).

Covers:
  - OpenClaw Pydantic schemas (openclaw_schemas.py)
  - All 5 bridge endpoints via FastAPI TestClient
  - Edge cases: empty messages, missing api_router, error recovery
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from context_agent.api.http_handler import create_app
from context_agent.api.openclaw_schemas import (
    AfterTurnRequest,
    AgentMessage,
    AssembleRequest,
    BootstrapRequest,
    CompactRequest,
    IngestRequest,
)
from context_agent.models.context import ContextOutput, OutputType


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_messages(n: int = 3) -> list[dict]:
    result = []
    for i in range(n):
        if i % 2 == 0:
            result.append({"role": "user", "content": f"User turn {i}"})
        else:
            result.append({"role": "assistant", "content": f"Assistant reply {i}"})
    return result


def _make_mock_router(items_updated: int = 2):
    """Build a mock ContextAPIRouter with the minimum attributes the bridge uses."""
    mock = MagicMock()
    # handle() returns (ContextOutput, warnings)
    mock.handle = AsyncMock(
        return_value=(
            ContextOutput(
                scope_id="test",
                session_id="s1",
                output_type=OutputType.COMPRESSED,
                content="Relevant context: previous discussion about Python.",
                token_count=50,
                metadata={"item_ids": ["item-001", "item-002"]},
            ),
            [],
        )
    )
    mock.mark_used = AsyncMock(return_value=items_updated)
    mock._working_memory = MagicMock()
    mock._working_memory.write = AsyncMock()
    mock._compression = MagicMock()
    mock._compression.route_and_compress = AsyncMock(
        return_value=ContextOutput(
            scope_id="test",
            session_id="s1",
            output_type=OutputType.COMPRESSED,
            content="[compacted summary]",
            token_count=10,
        )
    )
    return mock


def _make_client(with_router: bool = True) -> TestClient:
    app = create_app(api_router=_make_mock_router() if with_router else None)
    return TestClient(app, raise_server_exceptions=False)


# ── Schema tests ───────────────────────────────────────────────────────────────


class TestOpenClawSchemas:
    def test_agent_message_roles(self):
        for role in ("user", "assistant", "system"):
            msg = AgentMessage(role=role, content="hello")
            assert msg.role == role

    def test_bootstrap_request_defaults(self):
        req = BootstrapRequest(scope_id="s", session_id="sid")
        assert req.messages == []

    def test_ingest_requires_messages(self):
        with pytest.raises(Exception):
            IngestRequest(scope_id="s", session_id="sid", messages=[])

    def test_assemble_query_optional(self):
        req = AssembleRequest(
            scope_id="s",
            session_id="sid",
            messages=[AgentMessage(role="user", content="hi")],
        )
        assert req.query == ""
        assert req.token_budget == 2048

    def test_compact_defaults(self):
        req = CompactRequest(
            scope_id="s",
            session_id="sid",
            messages=[AgentMessage(role="user", content="hello")],
        )
        assert req.token_limit == 8192
        assert req.force is False

    def test_after_turn_defaults(self):
        from context_agent.api.openclaw_schemas import AfterTurnRequest

        req = AfterTurnRequest(
            scope_id="s",
            session_id="sid",
            assistant_message=AgentMessage(role="assistant", content="reply"),
        )
        assert req.used_context_item_ids == []


# ── bootstrap endpoint ─────────────────────────────────────────────────────────


class TestBootstrapEndpoint:
    def test_bootstrap_ok(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/bootstrap",
            json={"scope_id": "s1", "session_id": "sid1", "messages": _make_messages(4)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["items_loaded"] >= 0

    def test_bootstrap_no_router_graceful(self):
        client = _make_client(with_router=False)
        resp = client.post(
            "/v1/openclaw/bootstrap",
            json={"scope_id": "s1", "session_id": "sid1", "messages": []},
        )
        assert resp.status_code == 200
        assert resp.json()["items_loaded"] == 0

    def test_bootstrap_empty_messages(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/bootstrap",
            json={"scope_id": "s1", "session_id": "sid1", "messages": []},
        )
        assert resp.status_code == 200


# ── ingest endpoint ────────────────────────────────────────────────────────────


class TestIngestEndpoint:
    def test_ingest_ok(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/ingest",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": [{"role": "user", "content": "Hello world"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ingest_no_router(self):
        client = _make_client(with_router=False)
        resp = client.post(
            "/v1/openclaw/ingest",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": [{"role": "user", "content": "test"}],
            },
        )
        assert resp.status_code == 200

    def test_ingest_empty_messages_rejected(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/ingest",
            json={"scope_id": "s1", "session_id": "sid1", "messages": []},
        )
        assert resp.status_code == 422  # Pydantic min_length validation


# ── assemble endpoint ──────────────────────────────────────────────────────────


class TestAssembleEndpoint:
    def test_assemble_returns_addition(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/assemble",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": [{"role": "user", "content": "What is Python?"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert "system_prompt_addition" in data
        assert "context_item_ids" in data
        # Should inject retrieved context
        assert "Relevant Context" in data["system_prompt_addition"]

    def test_assemble_passes_messages_unchanged(self):
        client = _make_client(with_router=True)
        messages = [{"role": "user", "content": "Explain asyncio"}]
        resp = client.post(
            "/v1/openclaw/assemble",
            json={"scope_id": "s1", "session_id": "sid1", "messages": messages},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == len(messages)

    def test_assemble_empty_messages_returns_no_addition(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/assemble",
            json={"scope_id": "s1", "session_id": "sid1", "messages": []},
        )
        assert resp.status_code == 200
        assert resp.json()["system_prompt_addition"] == ""

    def test_assemble_explicit_query(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/assemble",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": [{"role": "user", "content": "hi"}],
                "query": "Tell me about FastAPI",
                "mode": "quality",
            },
        )
        assert resp.status_code == 200

    def test_assemble_accepts_camel_case_fields(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/assemble",
            json={
                "scopeId": "s1",
                "sessionId": "sid1",
                "messages": [{"role": "user", "content": "hi"}],
                "tokenBudget": 1024,
                "topK": 5,
                "minScore": 0.2,
            },
        )
        assert resp.status_code == 200

    def test_assemble_no_router_graceful(self):
        client = _make_client(with_router=False)
        resp = client.post(
            "/v1/openclaw/assemble",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": [{"role": "user", "content": "test"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["system_prompt_addition"] == ""


# ── compact endpoint ───────────────────────────────────────────────────────────


class TestCompactEndpoint:
    def test_compact_returns_messages(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/compact",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": _make_messages(10),
                "token_limit": 512,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert "tokens_before" in data
        assert "tokens_after" in data
        assert data["tokens_after"] <= data["tokens_before"] or data["status"] == "ok"

    def test_compact_no_router_truncates(self):
        client = _make_client(with_router=False)
        long_messages = [{"role": "user", "content": "x" * 200}] * 20
        resp = client.post(
            "/v1/openclaw/compact",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": long_messages,
                "token_limit": 128,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Truncated result must fit within token budget
        assert data["tokens_after"] <= 128 + 10  # allow small overhead
        assert data["status"] == "degraded"

    def test_compact_with_legacy_params(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/compact",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": _make_messages(5),
                "token_limit": 1024,
                "legacy_params": {"tokenLimit": 1024, "model": "claude-3-haiku"},
            },
        )
        assert resp.status_code == 200

    def test_compact_accepts_camel_case_fields(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/compact",
            json={
                "scopeId": "s1",
                "sessionId": "sid1",
                "messages": _make_messages(5),
                "tokenLimit": 1024,
                "compactionTarget": "budget",
                "customInstructions": "keep latest facts",
            },
        )
        assert resp.status_code == 200

    def test_bootstrap_accepts_camel_case_scope_fields(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/bootstrap",
            json={
                "scopeId": "s1",
                "sessionId": "sid1",
                "messages": _make_messages(2),
            },
        )
        assert resp.status_code == 200

    def test_compact_marks_degraded_when_compression_output_is_degraded(self):
        router = _make_mock_router()
        router._compression.route_and_compress = AsyncMock(
            return_value=ContextOutput(
                scope_id="test",
                session_id="s1",
                output_type=OutputType.COMPRESSED,
                content="[fallback compacted summary]",
                token_count=10,
                degraded=True,
                error="compression_fallback_raw",
            )
        )
        client = TestClient(create_app(api_router=router), raise_server_exceptions=False)

        resp = client.post(
            "/v1/openclaw/compact",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "messages": _make_messages(5),
                "token_limit": 1024,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"


# ── after-turn endpoint ────────────────────────────────────────────────────────


class TestAfterTurnEndpoint:
    def test_after_turn_with_used_ids(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/after-turn",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "assistant_message": {"role": "assistant", "content": "Here is my reply."},
                "used_context_item_ids": ["item-001", "item-002"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["updated_count"] == 2  # mocked to return 2

    def test_after_turn_no_used_ids(self):
        client = _make_client(with_router=True)
        resp = client.post(
            "/v1/openclaw/after-turn",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "assistant_message": {"role": "assistant", "content": "Done."},
                "used_context_item_ids": [],
            },
        )
        assert resp.status_code == 200

    def test_after_turn_no_router(self):
        client = _make_client(with_router=False)
        resp = client.post(
            "/v1/openclaw/after-turn",
            json={
                "scope_id": "s1",
                "session_id": "sid1",
                "assistant_message": {"role": "assistant", "content": "ok"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["updated_count"] == 0


# ── helper function tests ──────────────────────────────────────────────────────


class TestHelpers:
    def test_messages_to_query_last_user(self):
        from context_agent.api.openclaw_handler import _messages_to_query

        msgs = [
            AgentMessage(role="user", content="first"),
            AgentMessage(role="assistant", content="reply"),
            AgentMessage(role="user", content="what is Python?"),
        ]
        assert _messages_to_query(msgs) == "what is Python?"

    def test_messages_to_query_no_user(self):
        from context_agent.api.openclaw_handler import _messages_to_query

        msgs = [AgentMessage(role="assistant", content="hello")]
        assert _messages_to_query(msgs) == ""

    def test_truncate_to_budget(self):
        from context_agent.api.openclaw_handler import _truncate_to_budget

        msgs = [AgentMessage(role="user", content="x" * 100)] * 20
        result = _truncate_to_budget(msgs, token_limit=50)
        # Each message ≈ 25 tokens (100 chars / 4) + 4 overhead
        # Budget 50 allows ~1-2 messages
        total_tokens = sum(len(m.content) // 4 for m in result)
        assert total_tokens <= 50

    def test_estimate_tokens(self):
        from context_agent.api.openclaw_handler import _estimate_tokens

        msgs = [AgentMessage(role="user", content="a" * 400)]
        assert _estimate_tokens(msgs) == 100
