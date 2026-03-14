"""Runtime dependency health checks for the HTTP /health endpoint."""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from context_agent.adapters.llm_adapter import HttpLLMAdapter
from context_agent.config.settings import Settings, get_settings
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)
_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class AsyncHealthClient(Protocol):
    async def health_check(self) -> bool: ...


class AsyncClosable(Protocol):
    async def close(self) -> None: ...


def _known_attr(obj: object | None, name: str) -> object | None:
    if obj is None:
        return None
    values = getattr(obj, "__dict__", None)
    if not isinstance(values, dict):
        return None
    return values.get(name)


def _is_unresolved_placeholder(value: object) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER_PATTERN.search(value))


def _extract_placeholders(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(dict.fromkeys(_PLACEHOLDER_PATTERN.findall(value)))


def _collect_placeholder_refs(
    value: object,
    *,
    path: str,
) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            refs.extend(_collect_placeholder_refs(item, path=f"{path}.{key}"))
        return refs
    if isinstance(value, list):
        for index, item in enumerate(value):
            refs.extend(_collect_placeholder_refs(item, path=f"{path}[{index}]"))
        return refs
    for var_name in _extract_placeholders(value):
        refs.append((path, var_name))
    return refs


@dataclass
class ComponentHealthReport:
    name: str
    status: str
    detail: str
    configured: bool
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeHealthReport:
    status: str
    components: dict[str, ComponentHealthReport]


class RuntimeDependencyHealthChecker:
    """Checks the runtime health of ContextAgent and external dependencies."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        openjiuwen_config_path: str | Path | None = None,
        openjiuwen_config: dict[str, Any] | None = None,
        llm_adapter: object | None = None,
        component_timeout_s: float = 5.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._openjiuwen_config_path = (
            Path(openjiuwen_config_path).expanduser().resolve() if openjiuwen_config_path else None
        )
        self._raw_openjiuwen_config = openjiuwen_config
        self._openjiuwen_config: dict[str, Any] | None = None
        self._openjiuwen_config_error: str | None = None
        self._llm_adapter = llm_adapter
        self._component_timeout_s = component_timeout_s

    async def check(self, api_router: object | None) -> RuntimeHealthReport:
        tasks = {
            "contextagent": self._run_component(
                "contextagent",
                self._check_contextagent(api_router),
            ),
            "environment": self._run_component(
                "environment",
                self._check_environment(),
            ),
            "pgvector": self._run_component(
                "pgvector",
                self._check_pgvector(api_router),
            ),
            "llm": self._run_component(
                "llm",
                self._check_llm(api_router),
            ),
            "embedding": self._run_component(
                "embedding",
                self._check_embedding(),
            ),
        }
        results = await asyncio.gather(*tasks.values())
        components = dict(zip(tasks.keys(), results, strict=True))
        overall_status = (
            "degraded"
            if any(report.status == "degraded" for report in components.values())
            else "ok"
        )
        return RuntimeHealthReport(status=overall_status, components=components)

    async def _run_component(
        self,
        name: str,
        checker: Awaitable[ComponentHealthReport],
    ) -> ComponentHealthReport:
        started = time.monotonic()
        try:
            async with asyncio.timeout(self._component_timeout_s):
                report = await checker
        except TimeoutError:
            report = ComponentHealthReport(
                name=name,
                status="degraded",
                detail=f"health check timed out after {self._component_timeout_s:.1f}s",
                configured=True,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("runtime health check failed", component=name, error=str(exc))
            report = ComponentHealthReport(
                name=name,
                status="degraded",
                detail=f"health check failed: {exc}",
                configured=True,
            )
        report.latency_ms = round((time.monotonic() - started) * 1000, 2)
        return report

    async def _check_contextagent(self, api_router: object | None) -> ComponentHealthReport:
        if api_router is None:
            return ComponentHealthReport(
                name="contextagent",
                status="degraded",
                detail="ContextAPIRouter is not initialised",
                configured=True,
            )

        aggregator = _known_attr(api_router, "_aggregator")
        working_memory = _known_attr(api_router, "_working_memory")
        memory_processor = _known_attr(api_router, "_memory_processor")

        issues: list[str] = []
        if aggregator is None:
            issues.append("aggregator missing")
        if working_memory is None:
            issues.append("working memory missing")
        if memory_processor is not None and not bool(_known_attr(memory_processor, "_running")):
            issues.append("async memory processor not running")

        metadata = {
            "working_memory_enabled": working_memory is not None,
            "long_term_memory_enabled": _known_attr(aggregator, "_ltm") is not None
            if aggregator is not None
            else False,
            "async_memory_enabled": memory_processor is not None,
        }
        if issues:
            return ComponentHealthReport(
                name="contextagent",
                status="degraded",
                detail=", ".join(issues),
                configured=True,
                metadata=metadata,
            )
        return ComponentHealthReport(
            name="contextagent",
            status="ok",
            detail="router, aggregator, and working memory are ready",
            configured=True,
            metadata=metadata,
        )

    async def _check_environment(self) -> ComponentHealthReport:
        settings_refs = _collect_placeholder_refs(
            self._settings.model_dump(mode="python"),
            path="context_agent",
        )
        openjiuwen_raw = self._get_raw_openjiuwen_config()
        if openjiuwen_raw is None and self._openjiuwen_config_error is not None:
            return ComponentHealthReport(
                name="environment",
                status="degraded",
                detail=f"failed to load openJiuwen config: {self._openjiuwen_config_error}",
                configured=True,
            )

        openjiuwen_refs = (
            _collect_placeholder_refs(openjiuwen_raw, path="openjiuwen")
            if openjiuwen_raw is not None
            else []
        )
        unresolved_refs = settings_refs
        if openjiuwen_raw is not None:
            unresolved_refs = [
                *settings_refs,
                *_collect_placeholder_refs(self._get_openjiuwen_config(), path="openjiuwen"),
            ]

        total_refs = [*settings_refs, *openjiuwen_refs]
        if not total_refs:
            return ComponentHealthReport(
                name="environment",
                status="ok",
                detail=(
                    "no placeholder-based environment variables detected in active configuration"
                ),
                configured=False,
            )

        unresolved_vars = sorted({var_name for _, var_name in unresolved_refs})
        all_vars = sorted({var_name for _, var_name in total_refs})
        if unresolved_vars:
            unresolved_locations = ", ".join(
                f"{path} -> {var_name}" for path, var_name in unresolved_refs
            )
            return ComponentHealthReport(
                name="environment",
                status="degraded",
                detail=(
                    "unresolved environment variables in the running service process: "
                    + ", ".join(unresolved_vars)
                ),
                configured=True,
                metadata={
                    "missing_vars": ",".join(unresolved_vars),
                    "locations": unresolved_locations,
                },
            )

        return ComponentHealthReport(
            name="environment",
            status="ok",
            detail=(
                f"resolved {len(all_vars)} placeholder-based environment variables in the "
                "running service process"
            ),
            configured=True,
            metadata={"vars": ",".join(all_vars)},
        )

    async def _check_pgvector(self, api_router: object | None) -> ComponentHealthReport:
        config = self._get_openjiuwen_config()
        if config is None:
            if self._openjiuwen_config_error is not None:
                return ComponentHealthReport(
                    name="pgvector",
                    status="degraded",
                    detail=f"failed to load openJiuwen config: {self._openjiuwen_config_error}",
                    configured=True,
                )
            return ComponentHealthReport(
                name="pgvector",
                status="skipped",
                detail="openJiuwen config is not configured",
                configured=False,
            )

        vector_store = config.get("vector_store", {})
        if not isinstance(vector_store, dict):
            return ComponentHealthReport(
                name="pgvector",
                status="degraded",
                detail="openJiuwen vector_store config is invalid",
                configured=True,
            )

        backend = str(vector_store.get("backend", "pgvector")).strip().lower()
        if backend != "pgvector":
            return ComponentHealthReport(
                name="pgvector",
                status="skipped",
                detail=f"vector backend is '{backend}', not pgvector",
                configured=False,
                metadata={"backend": backend},
            )

        ltm = _known_attr(_known_attr(api_router, "_aggregator"), "_ltm")
        if ltm is None:
            return ComponentHealthReport(
                name="pgvector",
                status="degraded",
                detail="pgvector is configured but openJiuwen long-term memory is unavailable",
                configured=True,
                metadata={
                    "schema": vector_store.get("schema", "public"),
                    "table_name": vector_store.get("table_name", "ltm_memory"),
                },
            )

        ok = await ltm.health_check()
        return ComponentHealthReport(
            name="pgvector",
            status="ok" if ok else "degraded",
            detail="pgvector long-term memory probe succeeded"
            if ok
            else "pgvector long-term memory probe failed",
            configured=True,
            metadata={
                "schema": vector_store.get("schema", "public"),
                "table_name": vector_store.get("table_name", "ltm_memory"),
            },
        )

    async def _check_llm(self, api_router: object | None) -> ComponentHealthReport:
        if _is_unresolved_placeholder(self._settings.llm_base_url) or _is_unresolved_placeholder(
            self._settings.llm_model
        ):
            return ComponentHealthReport(
                name="llm",
                status="skipped",
                detail=(
                    "default LLM config still contains unresolved environment placeholders "
                    "in the running service process"
                ),
                configured=False,
            )

        adapter, owns_adapter = self._resolve_llm_adapter(api_router)
        if adapter is None:
            return ComponentHealthReport(
                name="llm",
                status="skipped",
                detail="default LLM is not configured",
                configured=False,
            )

        try:
            ok = await adapter.health_check()
        finally:
            if owns_adapter and hasattr(adapter, "close"):
                await cast(AsyncClosable, adapter).close()

        model = getattr(adapter, "_model", self._settings.llm_model)
        return ComponentHealthReport(
            name="llm",
            status="ok" if ok else "degraded",
            detail=f"LLM model '{model}' responded to the health probe"
            if ok
            else f"LLM model '{model}' did not respond to the health probe",
            configured=True,
            metadata={"model": model},
        )

    async def _check_embedding(self) -> ComponentHealthReport:
        config = self._get_openjiuwen_config()
        if config is None:
            if self._openjiuwen_config_error is not None:
                return ComponentHealthReport(
                    name="embedding",
                    status="degraded",
                    detail=f"failed to load openJiuwen config: {self._openjiuwen_config_error}",
                    configured=True,
                )
            return ComponentHealthReport(
                name="embedding",
                status="skipped",
                detail="openJiuwen config is not configured",
                configured=False,
            )

        embedding_config = config.get("embedding_config", {})
        if not isinstance(embedding_config, dict) or not embedding_config:
            return ComponentHealthReport(
                name="embedding",
                status="skipped",
                detail="embedding model is not configured",
                configured=False,
            )
        if _is_unresolved_placeholder(
            embedding_config.get("base_url")
        ) or _is_unresolved_placeholder(embedding_config.get("model")):
            return ComponentHealthReport(
                name="embedding",
                status="skipped",
                detail=(
                    "embedding config still contains unresolved environment placeholders "
                    "in the running service process"
                ),
                configured=False,
            )

        from context_agent.config.openjiuwen import _build_embedding_model

        embedding_model = _build_embedding_model(config)
        if embedding_model is None:
            return ComponentHealthReport(
                name="embedding",
                status="degraded",
                detail="failed to build embedding probe client",
                configured=True,
            )

        vector = await self._probe_embedding_model(embedding_model)
        if not isinstance(vector, list) or not vector:
            return ComponentHealthReport(
                name="embedding",
                status="degraded",
                detail="embedding probe returned an empty vector",
                configured=True,
                metadata={"model": embedding_config.get("model", "")},
            )

        return ComponentHealthReport(
            name="embedding",
            status="ok",
            detail=f"embedding model '{embedding_config.get('model', '')}' produced a vector",
            configured=True,
            metadata={
                "model": embedding_config.get("model", ""),
                "dimension": len(vector),
            },
        )

    def _get_openjiuwen_config(self) -> dict[str, Any] | None:
        if self._openjiuwen_config is not None:
            return self._openjiuwen_config
        if self._openjiuwen_config_error is not None:
            return None

        from context_agent.config.openjiuwen import _expand_env_placeholders

        try:
            raw_config = self._get_raw_openjiuwen_config()
            if raw_config is None:
                return None
            self._openjiuwen_config = _expand_env_placeholders(raw_config)
        except Exception as exc:
            self._openjiuwen_config_error = str(exc)
            logger.warning(
                "failed to load openJiuwen config for health checks",
                path=str(self._openjiuwen_config_path),
                error=str(exc),
            )
            return None
        return self._openjiuwen_config

    def _get_raw_openjiuwen_config(self) -> dict[str, Any] | None:
        if self._raw_openjiuwen_config is not None:
            return self._raw_openjiuwen_config
        if self._openjiuwen_config_error is not None:
            return None

        from context_agent.config.openjiuwen import (
            load_openjiuwen_config,
            resolve_openjiuwen_config_path,
        )

        resolved_path = resolve_openjiuwen_config_path(
            self._openjiuwen_config_path or self._settings.openjiuwen_config_path
        )
        if resolved_path is None:
            return None

        self._openjiuwen_config_path = Path(resolved_path).expanduser().resolve()
        try:
            self._raw_openjiuwen_config = load_openjiuwen_config(self._openjiuwen_config_path)
        except Exception as exc:
            self._openjiuwen_config_error = str(exc)
            logger.warning(
                "failed to load openJiuwen config for health checks",
                path=str(self._openjiuwen_config_path),
                error=str(exc),
            )
            return None
        return self._raw_openjiuwen_config

    def _resolve_llm_adapter(
        self, api_router: object | None
    ) -> tuple[AsyncHealthClient | None, bool]:
        router_adapter = _known_attr(api_router, "_llm_adapter")
        if router_adapter is not None and hasattr(router_adapter, "health_check"):
            return cast(AsyncHealthClient, router_adapter), False
        if self._llm_adapter is not None and hasattr(self._llm_adapter, "health_check"):
            return cast(AsyncHealthClient, self._llm_adapter), False
        from context_agent.config.openjiuwen import _resolve_effective_llm_config

        effective_llm_config = _resolve_effective_llm_config(
            self._settings,
            self._get_openjiuwen_config(),
        )
        if effective_llm_config is None:
            return None, False
        return (
            HttpLLMAdapter(
                base_url=effective_llm_config["base_url"],
                model=effective_llm_config["model"],
                timeout_s=min(float(effective_llm_config["timeout"]), self._component_timeout_s),
                max_retries=int(effective_llm_config["max_retries"]),
                api_key=str(effective_llm_config["api_key"]),
            ),
            True,
        )

    async def _probe_embedding_model(self, embedding_model: object) -> list[float]:
        if hasattr(embedding_model, "embed_query"):
            result = embedding_model.embed_query("context-agent health probe")
            if inspect.isawaitable(result):
                vector = await result
            else:
                vector = result
        elif hasattr(embedding_model, "embed_query_sync"):
            vector = await asyncio.to_thread(
                embedding_model.embed_query_sync,
                "context-agent health probe",
            )
        else:
            raise RuntimeError("embedding probe client does not expose embed_query")
        if not isinstance(vector, list):
            raise RuntimeError("embedding probe returned an invalid vector")
        return vector
