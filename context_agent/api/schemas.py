"""API request/response schemas (Pydantic v2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from context_agent.models.context import ContextOutput, MemoryCategory, OutputType
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
    # Dual-path retrieval mode: "fast" (default) or "quality" (LLM-driven agentic retrieval)
    mode: Literal["fast", "quality"] = "fast"
    # Semantic category filter — None means return all categories
    category_filter: list[MemoryCategory] | None = None


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
    components: dict[str, dict[str, Any]] = Field(default_factory=dict)


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


class ContextUsedRequest(BaseModel):
    """Report which context items were actually used in a model call.

    The ContextAgent increments active_count on matching items, which feeds
    the Hotness Score and improves future retrieval rankings.
    """

    scope_id: str
    session_id: str = ""
    item_ids: list[str] = Field(
        ..., description="IDs of ContextItems that were injected and used.", min_length=1
    )


class ContextUsedResponse(BaseModel):
    updated_count: int
    status: str = "ok"


class ToolResultRequest(BaseModel):
    """Record the outcome of a tool call to build performance memory."""

    scope_id: str
    tool_id: str
    success: bool
    duration_ms: float = Field(ge=0.0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class ToolResultResponse(BaseModel):
    tool_id: str
    status: str = "recorded"
