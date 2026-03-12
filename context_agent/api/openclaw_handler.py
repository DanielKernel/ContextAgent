"""OpenClaw context-engine bridge handler.

Exposes the five ContextEngine lifecycle endpoints that the TypeScript OpenClaw
plugin calls:

    POST /v1/openclaw/bootstrap
    POST /v1/openclaw/ingest
    POST /v1/openclaw/assemble
    POST /v1/openclaw/compact
    POST /v1/openclaw/after-turn

All endpoints are optional from OpenClaw's perspective — the plugin will only
call an endpoint when the Python service actually handles it.  Omitting any
endpoint means the operation silently no-ops on the TypeScript side.
"""

from __future__ import annotations

import time
import uuid
import inspect
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from context_agent.api.openclaw_schemas import (
    AfterTurnRequest,
    AfterTurnResponse,
    AgentMessage,
    AssembleRequest,
    AssembleResponse,
    BootstrapRequest,
    BootstrapResponse,
    CompactRequest,
    CompactResponse,
    IngestRequest,
    IngestResponse,
)
from context_agent.models.context import ContextItem, ContextLevel, MemoryType, OutputType
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

openclaw_router = APIRouter(prefix="/v1/openclaw", tags=["openclaw"])


def _messages_to_query(messages: list[AgentMessage]) -> str:
    """Extract a retrieval query from the most recent user message."""
    for msg in reversed(messages):
        if msg.role == "user" and msg.content.strip():
            return msg.content.strip()
    return ""


def _messages_to_items(messages: list[AgentMessage], scope_id: str, session_id: str) -> list[ContextItem]:
    """Convert AgentMessage list to ContextItem list for ingestion into working memory."""
    items: list[ContextItem] = []
    for msg in messages:
        if not msg.content.strip():
            continue
        item = ContextItem(
            item_id=uuid.uuid4().hex,
            scope_id=scope_id,
            session_id=session_id,
            content=f"[{msg.role}] {msg.content}",
            source_type=msg.role,
            memory_type=MemoryType.VARIABLE,
            level=ContextLevel.DETAIL,
            metadata={**msg.metadata, "role": msg.role},
        )
        items.append(item)
    return items


def _estimate_tokens(messages: list[AgentMessage]) -> int:
    return sum(len(m.content) // 4 for m in messages)


def _supports_ingest(api_router: Any) -> bool:
    ingest_messages = getattr(api_router, "ingest_messages", None)
    return inspect.iscoroutinefunction(ingest_messages)


# ── bootstrap ─────────────────────────────────────────────────────────────────


@openclaw_router.post("/bootstrap", response_model=BootstrapResponse, summary="Bootstrap existing session")
async def bootstrap(req: BootstrapRequest, request: Request) -> BootstrapResponse:
    """Warm ContextAgent caches when an existing OpenClaw session file is loaded."""
    from context_agent.api.router import ContextAPIRouter

    api_router: ContextAPIRouter | None = getattr(request.app.state, "api_router", None)
    if api_router is None:
        logger.warning("openclaw.bootstrap: no api_router, skipping")
        return BootstrapResponse(status="ok", items_loaded=0)

    items = _messages_to_items(req.messages, req.scope_id, req.session_id)
    if items:
        if _supports_ingest(api_router):
            await api_router.ingest_messages(
                scope_id=req.scope_id,
                session_id=req.session_id,
                messages=[
                    {"role": item.metadata.get("role", item.source_type), "content": item.content.split("] ", 1)[-1], "metadata": item.metadata}
                    for item in items
                ],
                persist_long_term=False,
            )
        elif api_router._working_memory is not None:
            for item in items:
                await api_router._working_memory.write(
                    scope_id=req.scope_id,
                    session_id=req.session_id,
                    item=item,
                )

    logger.info(
        "openclaw.bootstrap completed",
        scope_id=req.scope_id,
        session_id=req.session_id,
        items_loaded=len(items),
    )
    return BootstrapResponse(status="ok", items_loaded=len(items))


# ── ingest ────────────────────────────────────────────────────────────────────


@openclaw_router.post("/ingest", response_model=IngestResponse, summary="Ingest new messages")
async def ingest(req: IngestRequest, request: Request) -> IngestResponse:
    """Ingest one or more new conversation messages into ContextAgent working memory."""
    from context_agent.api.router import ContextAPIRouter

    api_router: ContextAPIRouter | None = getattr(request.app.state, "api_router", None)
    if api_router is None:
        return IngestResponse(status="ok", ingested_count=0)

    items = _messages_to_items(req.messages, req.scope_id, req.session_id)
    if _supports_ingest(api_router):
        ingested = await api_router.ingest_messages(
            scope_id=req.scope_id,
            session_id=req.session_id,
            messages=[
                {"role": item.metadata.get("role", item.source_type), "content": item.content.split("] ", 1)[-1], "metadata": item.metadata}
                for item in items
            ],
        )
    elif api_router._working_memory is not None:
        ingested = 0
        for item in items:
            await api_router._working_memory.write(
                scope_id=req.scope_id,
                session_id=req.session_id,
                item=item,
            )
            ingested += 1
    else:
        ingested = len(items)

    logger.info(
        "openclaw.ingest completed",
        scope_id=req.scope_id,
        session_id=req.session_id,
        count=ingested,
    )
    return IngestResponse(status="ok", ingested_count=ingested)


# ── assemble ──────────────────────────────────────────────────────────────────


@openclaw_router.post("/assemble", response_model=AssembleResponse, summary="Assemble context for next turn")
async def assemble(req: AssembleRequest, request: Request) -> AssembleResponse:
    """Retrieve relevant context and return it as a systemPromptAddition.

    ContextAgent uses Mode B (injection): the original messages are returned
    unchanged; retrieved context is passed back via ``system_prompt_addition``
    which OpenClaw prepends to the system prompt.
    """
    from context_agent.api.router import ContextAPIRouter

    api_router: ContextAPIRouter | None = getattr(request.app.state, "api_router", None)
    if api_router is None:
        return AssembleResponse(
            messages=req.messages,
            system_prompt_addition="",
            context_item_ids=[],
            estimated_tokens=_estimate_tokens(req.messages),
        )

    query = req.query or _messages_to_query(req.messages)
    if not query:
        msg_tokens = _estimate_tokens(req.messages)
        return AssembleResponse(
            messages=req.messages,
            system_prompt_addition="",
            context_item_ids=[],
            estimated_tokens=msg_tokens,
        )

    t0 = time.monotonic()
    try:
        output, warnings = await api_router.handle(
            scope_id=req.scope_id,
            session_id=req.session_id,
            query=query,
            output_type=OutputType.COMPRESSED,
            token_budget=req.token_budget,
            top_k=req.top_k,
            mode=req.mode,
        )
    except Exception as exc:
        logger.exception("openclaw.assemble error", error=str(exc))
        msg_tokens = _estimate_tokens(req.messages)
        return AssembleResponse(
            messages=req.messages,
            system_prompt_addition="",
            context_item_ids=[],
            estimated_tokens=msg_tokens,
        )

    latency = (time.monotonic() - t0) * 1000
    logger.info(
        "openclaw.assemble completed",
        scope_id=req.scope_id,
        session_id=req.session_id,
        latency_ms=f"{latency:.1f}",
        token_count=output.token_count,
    )

    # Extract item IDs from metadata for used() feedback round-trip
    item_ids = output.metadata.get("item_ids", []) if output.metadata else []

    addition = ""
    if output.content.strip():
        addition = f"# Relevant Context\n\n{output.content.strip()}"

    # estimated_tokens = messages tokens + injected context tokens
    msg_tokens = _estimate_tokens(req.messages)
    addition_tokens = len(addition) // 4
    return AssembleResponse(
        messages=req.messages,
        system_prompt_addition=addition,
        context_item_ids=item_ids,
        estimated_tokens=msg_tokens + addition_tokens,
    )


# ── compact ───────────────────────────────────────────────────────────────────


@openclaw_router.post("/compact", response_model=CompactResponse, summary="Compact messages on token overflow")
async def compact(req: CompactRequest, request: Request) -> CompactResponse:
    """Token-overflow compaction.

    Called by OpenClaw when message history exceeds the model token limit.
    Applies ContextAgent's compression pipeline and returns a shorter message list.
    """
    from context_agent.api.router import ContextAPIRouter
    from context_agent.orchestration.context_aggregator import AggregationRequest
    from context_agent.models.context import ContextSnapshot

    api_router: ContextAPIRouter | None = getattr(request.app.state, "api_router", None)
    if api_router is None:
        # No compaction possible — return last N messages that fit within budget
        truncated = _truncate_to_budget(req.messages, req.token_limit)
        return CompactResponse(
            messages=truncated,
            tokens_before=_estimate_tokens(req.messages),
            tokens_after=_estimate_tokens(truncated),
        )

    tokens_before = _estimate_tokens(req.messages)
    # Compact by converting messages to ContextItems and running the compression pipeline
    items = _messages_to_items(req.messages, req.scope_id, req.session_id)
    snapshot = ContextSnapshot(
        scope_id=req.scope_id,
        session_id=req.session_id,
        items=items,
        total_tokens=tokens_before,
        token_budget=req.token_limit,
        query="compact",
    )

    from context_agent.orchestration.strategy_scheduler import StrategySelectionContext

    ctx = StrategySelectionContext(
        scope_id=req.scope_id,
        task_type="compaction",
        agent_role="openclaw",
        token_used=tokens_before,
        token_budget=req.token_limit,
    )
    try:
        output = await api_router._compression.route_and_compress(snapshot, ctx)
        # Re-wrap compressed text as a single assistant message preserving history shape
        compacted_messages = [
            AgentMessage(role="assistant", content=output.content)
        ]
        tokens_after = _estimate_tokens(compacted_messages)
        summary = output.content[:200] if output.content else None
    except Exception as exc:
        logger.warning("openclaw.compact error, falling back to truncation", error=str(exc))
        compacted_messages = _truncate_to_budget(req.messages, req.token_limit)
        tokens_after = _estimate_tokens(compacted_messages)
        summary = None

    logger.info(
        "openclaw.compact completed",
        scope_id=req.scope_id,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
    )
    return CompactResponse(
        messages=compacted_messages,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        summary=summary,
    )


def _truncate_to_budget(messages: list[AgentMessage], token_limit: int) -> list[AgentMessage]:
    """Keep the most recent messages that fit within token_limit (tokens ≈ chars / 4)."""
    result: list[AgentMessage] = []
    budget = token_limit
    for msg in reversed(messages):
        est = len(msg.content) // 4 + 4  # 4 token overhead per message
        if budget - est < 0:
            break
        result.insert(0, msg)
        budget -= est
    return result


# ── after-turn ────────────────────────────────────────────────────────────────


@openclaw_router.post("/after-turn", response_model=AfterTurnResponse, summary="Post-turn feedback")
async def after_turn(req: AfterTurnRequest, request: Request) -> AfterTurnResponse:
    """Post-turn hook: record Hotness Score feedback and persist the assistant reply.

    Called by OpenClaw after each completed model turn.
    """
    from context_agent.api.router import ContextAPIRouter

    api_router: ContextAPIRouter | None = getattr(request.app.state, "api_router", None)
    if api_router is None:
        return AfterTurnResponse(status="ok", updated_count=0)

    updated = 0

    # 1. Feed Hotness Score for items that were actually used
    if req.used_context_item_ids:
        updated = await api_router.mark_used(
            scope_id=req.scope_id,
            session_id=req.session_id,
            item_ids=req.used_context_item_ids,
        )

    # 2. Persist the assistant reply as a working memory item
    if req.assistant_message.content.strip():
        if _supports_ingest(api_router):
            await api_router.ingest_messages(
                scope_id=req.scope_id,
                session_id=req.session_id,
                messages=[
                    {
                        "role": "assistant",
                        "content": req.assistant_message.content,
                        "metadata": {"role": "assistant", **req.assistant_message.metadata},
                    }
                ],
            )
        elif api_router._working_memory is not None:
            item = ContextItem(
                item_id=uuid.uuid4().hex,
                scope_id=req.scope_id,
                session_id=req.session_id,
                content=f"[assistant] {req.assistant_message.content}",
                source_type="assistant",
                memory_type=MemoryType.VARIABLE,
                level=ContextLevel.DETAIL,
                metadata={"role": "assistant"},
            )
            await api_router._working_memory.write(
                scope_id=req.scope_id,
                session_id=req.session_id,
                item=item,
            )

    logger.info(
        "openclaw.after_turn completed",
        scope_id=req.scope_id,
        session_id=req.session_id,
        updated_count=updated,
    )
    return AfterTurnResponse(status="ok", updated_count=updated)
