"""FastAPI HTTP handler — exposes ContextAgent as an HTTP service."""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from context_agent.api.auth import RequireAuth
from context_agent.api.openclaw_handler import openclaw_router
from context_agent.api.router import ContextAPIRouter
from context_agent.api.schemas import (
    ContextRequest,
    ContextResponse,
    ContextUsedRequest,
    ContextUsedResponse,
    DelegateRequest,
    DelegateResponse,
    HealthResponse,
    ToolResultRequest,
    ToolResultResponse,
    VersionListResponse,
    WriteRequest,
    WriteResponse,
)
from context_agent.config.settings import get_settings
from context_agent.core.monitoring.runtime_health import RuntimeDependencyHealthChecker
from context_agent.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

_START_TIME = time.monotonic()


def _known_attr(obj: object | None, name: str) -> Any:  # noqa: ANN401
    if obj is None:
        return None
    values = getattr(obj, "__dict__", None)
    if not isinstance(values, dict):
        return None
    return values.get(name)


async def _close_resource(resource: object | None) -> None:
    if resource is None:
        return
    for method_name in ("close", "aclose", "dispose"):
        method = getattr(resource, method_name, None)
        if not callable(method):
            continue
        result = method()
        if inspect.isawaitable(result):
            await result
        return


async def _close_router_resources(api_router: ContextAPIRouter | None) -> None:
    aggregator = _known_attr(api_router, "_aggregator")
    seen: set[int] = set()
    for resource in (
        _known_attr(api_router, "_llm_adapter"),
        _known_attr(aggregator, "_ltm"),
    ):
        if resource is None:
            continue
        resource_id = id(resource)
        if resource_id in seen:
            continue
        seen.add(resource_id)
        await _close_resource(resource)


def create_app(api_router: ContextAPIRouter | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Pass an initialised ContextAPIRouter to wire up real dependencies;
    omit it during tests to use a minimal stub.
    """
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from context_agent.config.openjiuwen import build_default_api_router_async

        logger.info("ContextAgent HTTP service starting", version="0.1.0")

        if app.state.api_router is None:
            app.state.api_router = await build_default_api_router_async()
            app.state.runtime_health_checker = _known_attr(
                app.state.api_router, "_runtime_health_checker"
            ) or RuntimeDependencyHealthChecker(
                settings=settings,
                llm_adapter=_known_attr(app.state.api_router, "_llm_adapter"),
            )

        router = app.state.api_router
        # Cast to Any to allow calling start/stop methods dynamically
        memory_processor: Any = _known_attr(router, "_memory_processor")

        if memory_processor is not None:
            start_method = getattr(memory_processor, "start", None)
            if inspect.iscoroutinefunction(start_method):
                await start_method()
            elif callable(start_method):
                start_method()
        yield
        if memory_processor is not None:
            stop_method = getattr(memory_processor, "stop", None)
            if inspect.iscoroutinefunction(stop_method):
                await stop_method()
            elif callable(stop_method):
                stop_method()
        await _close_router_resources(router)
        logger.info("ContextAgent HTTP service shutting down")

    app = FastAPI(
        title="ContextAgent",
        version="0.1.0",
        description="Unified context management proxy for multi-agent systems",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store the router instance in app state so routes can access it
    app.state.api_router = api_router
    app.state.runtime_health_checker = _known_attr(
        api_router, "_runtime_health_checker"
    ) or RuntimeDependencyHealthChecker(
        settings=settings,
        llm_adapter=_known_attr(api_router, "_llm_adapter"),
    )

    # Mount the OpenClaw context-engine bridge (unauthenticated sub-router;
    # security is handled at the network/plugin-config level)
    app.include_router(openclaw_router)

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    async def health(request: Request) -> HealthResponse:
        checker: RuntimeDependencyHealthChecker | None = request.app.state.runtime_health_checker
        components: dict[str, dict[str, object]] = {}
        status = "ok"
        if checker is not None:
            report = await checker.check(request.app.state.api_router)
            status = report.status
            components = {
                name: component.to_dict() for name, component in report.components.items()
            }
        return HealthResponse(
            status=status,
            version="0.1.0",
            uptime_s=round(time.monotonic() - _START_TIME, 1),
            components=components,
        )

    @app.post(
        "/context",
        response_model=ContextResponse,
        tags=["context"],
        dependencies=[RequireAuth],
    )
    async def retrieve_context(
        req: ContextRequest,
        request: Request,
    ) -> ContextResponse:
        router: ContextAPIRouter | None = request.app.state.api_router
        if router is None:
            raise HTTPException(status_code=503, detail="Service not initialised")

        t0 = time.monotonic()
        try:
            output, warnings = await router.handle(
                scope_id=req.scope_id,
                session_id=req.session_id,
                query=req.query,
                output_type=req.output_type,
                token_budget=req.token_budget,
                top_k=req.top_k,
                task_type=req.task_type,
                agent_role=req.agent_role,
                refs=req.refs,
                policy=req.policy,
                mode=req.mode,
                category_filter=req.category_filter,
            )
        except Exception as exc:
            logger.exception("context retrieval error", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return ContextResponse(
            request_id=uuid.uuid4().hex,
            scope_id=req.scope_id,
            session_id=req.session_id,
            output=output,
            latency_ms=round((time.monotonic() - t0) * 1000, 2),
            warnings=warnings,
        )

    async def _write_context(req: WriteRequest, request: Request) -> WriteResponse:
        """Persist memory through working memory and openJiuwen-managed long-term memory."""
        router: ContextAPIRouter | None = request.app.state.api_router
        if router is None:
            raise HTTPException(status_code=503, detail="Service not initialised")
        item_id = uuid.uuid4().hex
        persisted = await router.ingest_messages(
            scope_id=req.scope_id,
            session_id=req.session_id,
            messages=[
                {
                    "role": req.source_type,
                    "content": req.content,
                    "metadata": {
                        **req.metadata,
                        "requested_memory_type": req.memory_type,
                        "request_item_id": item_id,
                    },
                }
            ],
        )
        status = "accepted" if persisted else "ignored"
        return WriteResponse(item_id=item_id, status=status)

    @app.post(
        "/context/write",
        response_model=WriteResponse,
        tags=["context"],
        dependencies=[RequireAuth],
    )
    async def write_context(req: WriteRequest, request: Request) -> WriteResponse:
        return await _write_context(req, request)

    @app.post(
        "/v1/context/write",
        response_model=WriteResponse,
        tags=["context"],
        dependencies=[RequireAuth],
        include_in_schema=False,
    )
    async def write_context_v1(req: WriteRequest, request: Request) -> WriteResponse:
        return await _write_context(req, request)

    @app.get(
        "/context/{scope_id}/versions",
        response_model=VersionListResponse,
        tags=["versioning"],
        dependencies=[RequireAuth],
    )
    async def list_versions(
        scope_id: str,
        session_id: str = "",
        request: Request | None = None,
    ) -> VersionListResponse:
        router: ContextAPIRouter | None = request.app.state.api_router if request else None
        if router is None:
            return VersionListResponse(versions=[])
        records = await router._vm.list_versions(scope_id, session_id)
        return VersionListResponse(versions=[r.model_dump(mode="json") for r in records])

    @app.post(
        "/context/delegate",
        response_model=DelegateResponse,
        tags=["multi-agent"],
        dependencies=[RequireAuth],
    )
    async def delegate_context(req: DelegateRequest, request: Request) -> DelegateResponse:
        """Create a child scope for sub-agent delegation."""
        from context_agent.models.context import ContextSnapshot

        router: ContextAPIRouter | None = request.app.state.api_router
        if router is None:
            raise HTTPException(status_code=503, detail="Service not initialised")

        from context_agent.orchestration.sub_agent_manager import SubAgentContextManager

        manager = SubAgentContextManager(
            exposure_controller=router._ec,
            version_manager=router._vm,
        )
        # Build a minimal snapshot to delegate (production would use real aggregation)
        snapshot = ContextSnapshot(
            scope_id=req.scope_id,
            session_id=req.session_id,
            items=[],
            total_tokens=0,
            query=req.task_description,
        )
        view, ticket = await manager.delegate(snapshot, req.task_description, req.policy, req.ttl_s)
        return DelegateResponse(
            ticket_id=ticket.ticket_id,
            child_scope_id=ticket.child_scope_id,
            visible_item_count=len(view.visible_items),
        )

    @app.exception_handler(Exception)
    async def global_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error", path=str(request.url), error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.post(
        "/context/used",
        response_model=ContextUsedResponse,
        tags=["context"],
        dependencies=[RequireAuth],
        summary="Report used context items (Hotness Score feedback)",
    )
    async def report_used_context(req: ContextUsedRequest, request: Request) -> ContextUsedResponse:
        """Inform ContextAgent which context items were injected and confirmed useful.

        Increments ``active_count`` on matching items, boosting their Hotness Score
        and rank in future retrievals.
        """
        router: ContextAPIRouter | None = request.app.state.api_router
        if router is None:
            raise HTTPException(status_code=503, detail="Service not initialised")
        updated = await router.mark_used(
            scope_id=req.scope_id,
            session_id=req.session_id,
            item_ids=req.item_ids,
        )
        return ContextUsedResponse(updated_count=updated)

    @app.post(
        "/tools/result",
        response_model=ToolResultResponse,
        tags=["tools"],
        dependencies=[RequireAuth],
        summary="Record tool call outcome (Tool Performance Memory)",
    )
    async def record_tool_result(req: ToolResultRequest, request: Request) -> ToolResultResponse:
        """Record the outcome of a tool call.

        Stats accumulate in ToolContextGovernor and influence future tool
        selection: unreliable tools rank lower.
        """
        router: ContextAPIRouter | None = request.app.state.api_router
        if router is None:
            raise HTTPException(status_code=503, detail="Service not initialised")
        router.record_tool_result(
            scope_id=req.scope_id,
            tool_id=req.tool_id,
            success=req.success,
            duration_ms=req.duration_ms,
            prompt_tokens=req.prompt_tokens,
            completion_tokens=req.completion_tokens,
        )
        return ToolResultResponse(tool_id=req.tool_id)

    return app


# ---------------------------------------------------------------------------
# Module-level ASGI app used by uvicorn:
#   uvicorn context_agent.api.http_handler:app
#
# Initialises a default ContextAPIRouter (all optional deps are None which
# means in-memory / stub implementations are used).  For production you can
# replace this with `create_app(api_router=your_router)` in an entrypoint.
# ---------------------------------------------------------------------------
app = create_app()
