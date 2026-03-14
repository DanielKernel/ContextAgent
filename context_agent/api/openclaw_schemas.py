"""Pydantic schemas for the OpenClaw context-engine bridge API (/v1/openclaw/*)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Shared message model ───────────────────────────────────────────────────────


class AgentMessage(BaseModel):
    """A single turn message in an OpenClaw conversation.

    Mirrors `AgentMessage` from ``@mariozechner/pi-agent-core``.
    """

    role: Literal["user", "assistant", "system"]
    content: str
    # Optional metadata (e.g. tool calls, media attachments)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── bootstrap ─────────────────────────────────────────────────────────────────


class BootstrapRequest(BaseModel):
    """Called when an existing OpenClaw session file is loaded.

    Allows ContextAgent to warm its caches / restore prior state.
    """

    model_config = ConfigDict(populate_by_name=True)

    scope_id: str = Field(..., description="Logical scope (e.g. channel or user ID)", alias="scopeId")
    session_id: str = Field(..., description="OpenClaw session identifier", alias="sessionId")
    messages: list[AgentMessage] = Field(
        default_factory=list, description="Full conversation history from the session file"
    )


class BootstrapResponse(BaseModel):
    status: str = "ok"
    items_loaded: int = 0


# ── ingest ────────────────────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    """Ingest one or more new messages into ContextAgent's working memory.

    Corresponds to ``ingest()`` / ``ingestBatch()`` in the ContextEngine interface.
    """

    model_config = ConfigDict(populate_by_name=True)

    scope_id: str = Field(alias="scopeId")
    session_id: str = Field(alias="sessionId")
    messages: list[AgentMessage] = Field(..., min_length=1)


class IngestResponse(BaseModel):
    status: str = "ok"
    ingested_count: int = 0


# ── assemble ──────────────────────────────────────────────────────────────────


class AssembleRequest(BaseModel):
    """Retrieve relevant context to inject before the next LLM call.

    OpenClaw calls ``assemble()`` after the message pipeline (sanitize / validate /
    limit) and before forwarding to the model.  ContextAgent replies with a
    ``systemPromptAddition`` string which OpenClaw prepends to the system prompt.
    """

    model_config = ConfigDict(populate_by_name=True)

    scope_id: str = Field(alias="scopeId")
    session_id: str = Field(alias="sessionId")
    messages: list[AgentMessage] = Field(
        ..., description="Current message list (post-sanitize, pre-LLM)"
    )
    query: str = Field(
        default="",
        description="Optional explicit query; derived from last user message when empty.",
    )
    token_budget: int = Field(default=2048, gt=0, le=32768, alias="tokenBudget")
    top_k: int = Field(default=8, gt=0, le=50, alias="topK")
    mode: Literal["fast", "quality"] = "fast"
    min_score: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score threshold. Context items below this are filtered.",
        alias="minScore",
    )


class AssembleResponse(BaseModel):
    """Response to an assemble() call.

    ``system_prompt_addition`` is prepended to the system prompt by OpenClaw.
    ``messages`` is returned unchanged (ContextAgent does not compact messages;
    it uses Mode B — systemPromptAddition injection).
    ``estimated_tokens`` is the total token count of the assembled context window.
    """

    messages: list[AgentMessage]  # original messages, passed through unchanged
    system_prompt_addition: str = ""
    context_item_ids: list[str] = Field(
        default_factory=list, description="IDs of items injected; used for used() feedback"
    )
    estimated_tokens: int = Field(
        default=0, description="Estimated total tokens in assembled context (messages + addition)"
    )


# ── compact ───────────────────────────────────────────────────────────────────


class CompactRequest(BaseModel):
    """Token-overflow compaction request.

    Called by OpenClaw when the active message list exceeds the model's token
    limit (overflow safety net — always fires regardless of ``ownsCompaction``).
    The TypeScript engine reads the ``sessionFile`` from disk, extracts messages,
    and forwards them here.
    """

    model_config = ConfigDict(populate_by_name=True)

    scope_id: str = Field(alias="scopeId")
    session_id: str = Field(alias="sessionId")
    messages: list[AgentMessage]
    token_limit: int = Field(default=8192, gt=0, alias="tokenLimit")
    force: bool = False
    compaction_target: Literal["budget", "threshold"] | None = Field(
        default=None, alias="compactionTarget"
    )
    custom_instructions: str | None = Field(default=None, alias="customInstructions")


class CompactResponse(BaseModel):
    messages: list[AgentMessage]
    tokens_before: int = 0
    tokens_after: int = 0
    status: str = "ok"
    summary: str | None = None


# ── after-turn ────────────────────────────────────────────────────────────────


class AfterTurnRequest(BaseModel):
    """Post-turn feedback hook.

    Called after each completed turn.  ContextAgent uses this to record which
    context items were consumed (Hotness Score feedback) and persist any
    working-memory updates.
    """

    model_config = ConfigDict(populate_by_name=True)

    scope_id: str = Field(alias="scopeId")
    session_id: str = Field(alias="sessionId")
    assistant_message: AgentMessage = Field(alias="assistantMessage")
    # IDs returned by the preceding assemble() call — used to update active_count
    used_context_item_ids: list[str] = Field(default_factory=list, alias="usedContextItemIds")


class AfterTurnResponse(BaseModel):
    status: str = "ok"
    updated_count: int = 0
