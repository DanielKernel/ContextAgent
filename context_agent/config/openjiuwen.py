"""Helpers for loading openJiuwen configuration and wiring default startup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter
from context_agent.api.router import ContextAPIRouter
from context_agent.config.settings import Settings, get_settings
from context_agent.orchestration.context_aggregator import ContextAggregator
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


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
    return OpenJiuwenLTMAdapter(ltm=LongTermMemory(config=config))


def build_default_api_router(settings: Settings | None = None) -> ContextAPIRouter:
    """Build the default API router, wiring openJiuwen LTM when configured."""
    runtime_settings = settings or get_settings()
    aggregator_kwargs: dict[str, Any] = {}

    if runtime_settings.openjiuwen_config_path:
        aggregator_kwargs["ltm"] = build_openjiuwen_ltm_adapter(
            runtime_settings.openjiuwen_config_path
        )
    else:
        logger.info(
            "starting without openJiuwen long-term memory",
            reason="CA_OPENJIUWEN_CONFIG_PATH is not set",
        )

    return ContextAPIRouter(aggregator=ContextAggregator(**aggregator_kwargs))
