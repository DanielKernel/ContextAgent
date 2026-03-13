"""ContextAgent — unified context management proxy for multi-agent systems.

Public API surface (all stable exports):
    - ContextAPIRouter        : unified facade (UC007)
    - ContextAggregator       : multi-source context aggregation (UC001)
    - HybridStrategyScheduler : strategy selection (UC005)
    - CompressionStrategyRouter : compression routing (UC009)
    - SubAgentContextManager  : multi-agent delegation (UC014)
    - StrategyRegistry        : compression strategy registry
    - Settings / get_settings : application configuration
    - create_app              : FastAPI application factory
"""

from __future__ import annotations

from context_agent.api.router import ContextAPIRouter
from context_agent.config.settings import Settings, get_settings
from context_agent.models.context import (
    ContextItem,
    ContextOutput,
    ContextSnapshot,
    ContextView,
    MemoryType,
    OutputType,
)
from context_agent.models.policy import ExposurePolicy
from context_agent.models.ref import ContextRef, RefType
from context_agent.orchestration.compression_router import CompressionStrategyRouter
from context_agent.orchestration.context_aggregator import (
    AggregationRequest,
    ContextAggregator,
)
from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler,
    StrategySchedule,
    StrategySelectionContext,
)
from context_agent.orchestration.sub_agent_manager import SubAgentContextManager
from context_agent.strategies.registry import (
    StrategyRegistry,
    ensure_default_strategies_registered,
)
from context_agent.utils.logging import configure_logging, get_logger

__version__ = "0.1.0"


def create_app(*args: object, **kwargs: object) -> object:
    from context_agent.api.http_handler import create_app as _create_app

    return _create_app(*args, **kwargs)
__all__ = [
    # API layer
    "create_app",
    "ContextAPIRouter",
    # Orchestration
    "ContextAggregator",
    "AggregationRequest",
    "CompressionStrategyRouter",
    "HybridStrategyScheduler",
    "StrategySchedule",
    "StrategySelectionContext",
    "SubAgentContextManager",
    # Models
    "ContextItem",
    "ContextOutput",
    "ContextSnapshot",
    "ContextView",
    "MemoryType",
    "OutputType",
    "ExposurePolicy",
    "ContextRef",
    "RefType",
    # Infrastructure
    "StrategyRegistry",
    "Settings",
    "get_settings",
    "configure_logging",
    "get_logger",
    # Metadata
    "__version__",
]

# Auto-register built-in strategies on import
ensure_default_strategies_registered()
