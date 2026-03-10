"""External memory adapter.

Defines ExternalMemoryPort (ABC) for non-openJiuwen memory backends,
plus a no-op stub implementation used in tests and lightweight deployments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from context_agent.models.context import ContextItem
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class ExternalMemoryPort(ABC):
    """Abstract interface for external memory backends (e.g., custom vector DBs)."""

    @abstractmethod
    async def search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        """Search external memory and return ranked ContextItems."""

    @abstractmethod
    async def upsert(
        self,
        scope_id: str,
        items: list[ContextItem],
    ) -> None:
        """Insert or update items in external memory."""

    @abstractmethod
    async def delete(self, scope_id: str, item_ids: list[str]) -> None:
        """Remove items from external memory by ID."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the external memory backend is reachable."""


class StubExternalMemoryAdapter(ExternalMemoryPort):
    """No-op stub — returns empty results. Used in tests and minimal deployments."""

    async def search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        logger.debug("StubExternalMemoryAdapter.search called (returning empty)", scope_id=scope_id)
        return []

    async def upsert(self, scope_id: str, items: list[ContextItem]) -> None:
        logger.debug("StubExternalMemoryAdapter.upsert called (no-op)", scope_id=scope_id, count=len(items))

    async def delete(self, scope_id: str, item_ids: list[str]) -> None:
        logger.debug("StubExternalMemoryAdapter.delete called (no-op)", scope_id=scope_id)

    async def health_check(self) -> bool:
        return True
