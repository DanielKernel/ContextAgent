"""Long-term memory adapter.

Defines LongTermMemoryPort (ABC) and its openJiuwen implementation.
All core/orchestration code depends only on LongTermMemoryPort.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from context_agent.models.context import ContextItem, MemoryType
from context_agent.utils.errors import AdapterError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class LongTermMemoryPort(ABC):
    """Abstract interface for long-term memory operations."""

    @abstractmethod
    async def search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
        memory_types: list[MemoryType] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        """Search memory and return ranked ContextItems."""

    async def agentic_search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[ContextItem]:
        """LLM-driven agentic search for complex queries (quality path).

        Default implementation falls back to standard search.
        Override in concrete adapters that support AgenticRetriever.
        """
        return await self.search(scope_id, query, top_k)

    @abstractmethod
    async def add_messages(
        self,
        scope_id: str,
        messages: list[dict[str, Any]],
        user_id: str = "",
    ) -> None:
        """Write messages into long-term memory (fire-and-forget safe)."""

    @abstractmethod
    async def delete_by_id(self, scope_id: str, memory_id: str) -> None:
        """Delete a specific memory entry."""

    @abstractmethod
    async def update_by_id(
        self,
        scope_id: str,
        memory_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update a specific memory entry."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the memory backend is reachable."""


class OpenJiuwenLTMAdapter(LongTermMemoryPort):
    """openJiuwen LongTermMemory implementation of LongTermMemoryPort."""

    def __init__(self, ltm: Any) -> None:
        # ltm: openjiuwen LongTermMemory instance (injected at startup)
        self._ltm = ltm

    async def search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
        memory_types: list[MemoryType] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        try:
            results = await self._ltm.search_user_mem(
                query=query,
                user_id=scope_id,
                limit=top_k,
                filters=filters or {},
            )
            items = []
            for r in results:
                memory_type = None
                if hasattr(r, "memory_type"):
                    try:
                        memory_type = MemoryType(r.memory_type)
                    except ValueError:
                        pass
                items.append(
                    ContextItem(
                        source_type="ltm",
                        tier="warm",
                        memory_type=memory_type,
                        score=getattr(r, "score", 1.0),
                        content=getattr(r, "memory", getattr(r, "content", str(r))),
                        metadata={"memory_id": getattr(r, "id", ""), "scope_id": scope_id},
                    )
                )
            return items
        except Exception as exc:
            logger.warning("ltm.search failed", scope_id=scope_id, error=str(exc))
            raise AdapterError("LTM", str(exc), code=ErrorCode.OPENJIUWEN_UNAVAILABLE) from exc

    async def add_messages(
        self,
        scope_id: str,
        messages: list[dict[str, Any]],
        user_id: str = "",
    ) -> None:
        try:
            await self._ltm.add_messages(
                messages=messages,
                user_id=user_id or scope_id,
            )
        except Exception as exc:
            raise AdapterError("LTM", str(exc), code=ErrorCode.MEMORY_WRITE_FAILED) from exc

    async def delete_by_id(self, scope_id: str, memory_id: str) -> None:
        try:
            await self._ltm.delete_mem_by_id(memory_id=memory_id, user_id=scope_id)
        except Exception as exc:
            raise AdapterError("LTM", str(exc)) from exc

    async def update_by_id(
        self,
        scope_id: str,
        memory_id: str,
        updates: dict[str, Any],
    ) -> None:
        try:
            await self._ltm.update_mem_by_id(
                memory_id=memory_id,
                user_id=scope_id,
                updates=updates,
            )
        except Exception as exc:
            raise AdapterError("LTM", str(exc)) from exc

    async def health_check(self) -> bool:
        try:
            await self._ltm.search_user_mem(query="health", user_id="__health__", limit=1)
            return True
        except Exception:
            return False

    async def agentic_search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[ContextItem]:
        """Quality-path search using openJiuwen AgenticRetriever (if available).

        The LTM object may optionally expose an agentic_retrieve method that
        wraps AgenticRetriever internally.  Falls back to standard search.
        """
        if hasattr(self._ltm, "agentic_retrieve"):
            try:
                results = await self._ltm.agentic_retrieve(  # type: ignore[attr-defined]
                    query=query, user_id=scope_id, top_k=top_k
                )
                items = []
                for r in results:
                    items.append(
                        ContextItem(
                            source_type="ltm_agentic",
                            tier="warm",
                            score=getattr(r, "score", 1.0),
                            content=getattr(r, "memory", getattr(r, "content", str(r))),
                            metadata={
                                "memory_id": getattr(r, "id", ""),
                                "scope_id": scope_id,
                                "retrieval_mode": "agentic",
                            },
                        )
                    )
                return items
            except Exception as exc:
                logger.warning(
                    "agentic_retrieve failed, falling back to standard search",
                    scope_id=scope_id,
                    error=str(exc),
                )
        return await self.search(scope_id, query, top_k)
