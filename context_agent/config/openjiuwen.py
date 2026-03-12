"""Helpers for loading openJiuwen configuration and wiring default startup."""

from __future__ import annotations

import json
import inspect
import os
from pathlib import Path
from typing import Any

import yaml

from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter
from context_agent.api.router import ContextAPIRouter
from context_agent.config.settings import Settings, get_settings
from context_agent.core.memory.async_processor import AsyncMemoryProcessor
from context_agent.core.memory.orchestrator import MemoryOrchestrator
from context_agent.core.memory.working_memory import WorkingMemoryManager
from context_agent.orchestration.context_aggregator import ContextAggregator
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENJIUWEN_CONFIG_PATH = PROJECT_ROOT / "config" / "openjiuwen.yaml"


def _instantiate_long_term_memory(long_term_memory_cls: type, config: dict[str, Any]) -> Any:
    """Instantiate openJiuwen LongTermMemory across constructor variants."""
    init_fn = long_term_memory_cls.__init__
    try:
        init_signature = inspect.signature(init_fn)
    except (TypeError, ValueError):
        init_signature = None

    parameter_names = (
        [name for name in init_signature.parameters if name != "self"]
        if init_signature is not None
        else []
    )

    attempts: list[tuple[str, Any]] = []
    supported_kwargs = {
        key: value for key, value in config.items() if key in parameter_names
    }

    if "config" in parameter_names:
        attempts.append(("LongTermMemory(config=config)", lambda: long_term_memory_cls(config=config)))

    if "cfg" in parameter_names:
        attempts.append(("LongTermMemory(cfg=config)", lambda: long_term_memory_cls(cfg=config)))

    if supported_kwargs:
        attempts.append(("LongTermMemory(**config)", lambda: long_term_memory_cls(**supported_kwargs)))

    attempts.append(("LongTermMemory(config)", lambda: long_term_memory_cls(config)))

    for factory_name in ("from_config", "create", "build"):
        factory = getattr(long_term_memory_cls, factory_name, None)
        if callable(factory):
            attempts.append((f"LongTermMemory.{factory_name}(config)", lambda factory=factory: factory(config)))
            if supported_kwargs:
                attempts.append(
                    (f"LongTermMemory.{factory_name}(**config)", lambda factory=factory: factory(**supported_kwargs))
                )

    errors: list[str] = []
    for label, attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            errors.append(f"{label}: {exc}")
            continue

    raise ContextAgentError(
        "Unsupported openJiuwen LongTermMemory constructor signature. "
        "Please align ContextAgent with the installed openJiuwen version.",
        code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
        details={
            "constructor_parameters": parameter_names,
            "attempts": errors,
        },
    )


def load_openjiuwen_config(config_path: str | Path) -> dict[str, Any]:
    """Load openJiuwen config from a YAML or JSON file."""
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise ContextAgentError(
            f"openJiuwen config file not found: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
        )

    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        elif suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise ContextAgentError(
                f"Unsupported openJiuwen config format: {path.name}",
                code=ErrorCode.CONFIGURATION_ERROR,
            )
    except json.JSONDecodeError as exc:
        raise ContextAgentError(
            f"Invalid JSON in openJiuwen config: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
            details={"path": str(path)},
        ) from exc
    except yaml.YAMLError as exc:
        raise ContextAgentError(
            f"Invalid YAML in openJiuwen config: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
            details={"path": str(path)},
        ) from exc

    if not isinstance(data, dict):
        raise ContextAgentError(
            f"openJiuwen config must be a mapping: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
        )
    return data


def resolve_openjiuwen_config_path(explicit_path: str | Path | None = None) -> Path | None:
    """Resolve the openJiuwen config path from explicit value, env, or repo default."""
    candidate_path = explicit_path or os.getenv("CA_OPENJIUWEN_CONFIG_PATH")
    if candidate_path:
        candidate = Path(candidate_path).expanduser()
        return candidate if candidate.is_absolute() else (Path.cwd() / candidate).resolve()

    if DEFAULT_OPENJIUWEN_CONFIG_PATH.is_file():
        return DEFAULT_OPENJIUWEN_CONFIG_PATH.resolve()
    return None


def build_openjiuwen_ltm_adapter(config_path: str | Path) -> OpenJiuwenLTMAdapter:
    """Build an OpenJiuwenLTMAdapter from an openJiuwen config file."""
    config = load_openjiuwen_config(config_path)
    try:
        from openjiuwen.core.memory.long_term_memory import LongTermMemory
    except ImportError as exc:
        raise ContextAgentError(
            "openJiuwen is required when CA_OPENJIUWEN_CONFIG_PATH is set. "
            "Install the project with the openjiuwen extra or add openjiuwen to the environment.",
            code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
        ) from exc

    vector_store = config.get("vector_store", {})
    vector_backend = (
        vector_store.get("backend", "unknown")
        if isinstance(vector_store, dict)
        else "unknown"
    )
    logger.info(
        "loading openJiuwen long-term memory",
        config_path=str(Path(config_path).expanduser().resolve()),
        vector_backend=vector_backend,
    )
    try:
        ltm = _instantiate_long_term_memory(LongTermMemory, config)
    except TypeError as exc:
        raise ContextAgentError(
            "Failed to initialize openJiuwen LongTermMemory with the installed "
            "constructor signature.",
            code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
            details={"reason": str(exc)},
        ) from exc
    return OpenJiuwenLTMAdapter(ltm=ltm)


def build_default_api_router(settings: Settings | None = None) -> ContextAPIRouter:
    """Build the default API router, wiring openJiuwen LTM when configured."""
    runtime_settings = settings or get_settings()
    aggregator_kwargs: dict[str, Any] = {}
    router_kwargs: dict[str, Any] = {}
    working_memory = WorkingMemoryManager()
    aggregator_kwargs["working_memory"] = working_memory
    router_kwargs["working_memory"] = working_memory

    resolved_openjiuwen_config = resolve_openjiuwen_config_path(
        runtime_settings.openjiuwen_config_path
    )

    if resolved_openjiuwen_config is not None:
        try:
            ltm_adapter = build_openjiuwen_ltm_adapter(
                resolved_openjiuwen_config
            )
        except ContextAgentError as exc:
            if exc.code != ErrorCode.OPENJIUWEN_UNAVAILABLE:
                raise
            logger.warning(
                "openJiuwen long-term memory unavailable, starting with working memory only",
                config_path=str(resolved_openjiuwen_config),
                error=str(exc),
                details=exc.details,
            )
        else:
            memory_processor = AsyncMemoryProcessor(ltm=ltm_adapter)
            router_kwargs["memory_processor"] = memory_processor
            router_kwargs["memory_orchestrator"] = MemoryOrchestrator(
                working_memory=working_memory,
                async_processor=memory_processor,
            )
            aggregator_kwargs["ltm"] = ltm_adapter
    else:
        logger.info(
            "starting without openJiuwen long-term memory",
            reason="No openJiuwen config file was found",
        )

    return ContextAPIRouter(
        aggregator=ContextAggregator(**aggregator_kwargs),
        **router_kwargs,
    )
