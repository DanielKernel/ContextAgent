"""API request/response schemas (Pydantic v2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from context_agent.models.context import ContextOutput, OutputType
from context_agent.models.policy import ExposurePolicy
from context_agent.models.ref import ContextRef


class ContextRequest(BaseModel):
    """Unified context retrieval request."""

    scope_id: str
    session_id: str = ""
    query: str
    output_type: OutputType = OutputType.COMPRESSED
    token_budget: int = Field(default=4096, gt=0, le=128000)
    top_k: int = Field(default=10, gt=0, le=100)
    task_type: str = ""
    agent_role: str = ""
    refs: list[ContextRef] = Field(default_factory=list)
    policy: ExposurePolicy | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextResponse(BaseModel):
    """Unified context retrieval response."""

    request_id: str
    scope_id: str
    session_id: str
    output: ContextOutput
    latency_ms: float
    warnings: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    uptime_s: float = 0.0


class WriteRequest(BaseModel):
    """Write or update a context item."""

    scope_id: str
    session_id: str
    content: str
    source_type: str = "user"
    memory_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WriteResponse(BaseModel):
    item_id: str
    status: str = "accepted"


class VersionListResponse(BaseModel):
    versions: list[dict[str, Any]]


class DelegateRequest(BaseModel):
    scope_id: str
    session_id: str
    task_description: str
    policy: ExposurePolicy | None = None
    ttl_s: float = Field(default=300.0, gt=0)


class DelegateResponse(BaseModel):
    ticket_id: str
    child_scope_id: str
    visible_item_count: int
