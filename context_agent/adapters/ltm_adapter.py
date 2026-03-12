"""Long-term memory adapter.

Defines LongTermMemoryPort (ABC) and its openJiuwen implementation.
All core/orchestration code depends only on LongTermMemoryPort.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import inspect
from typing import Any

from context_agent.models.context import ContextItem, MemoryType
from context_agent.utils.errors import AdapterError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


def _method_accepts_name(method: Any, name: str) -> bool:
    try:
        return name in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False


async def _call_ltm_method(method: Any, /, *args: Any, **kwargs: Any) -> Any:
    filtered_kwargs = kwargs
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        signature = None

    if signature is not None and not any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        filtered_kwargs = {
            key: value for key, value in kwargs.items() if key in signature.parameters
        }
    return await method(*args, **filtered_kwargs)


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

    def __init__(self, ltm: Any, memory_config: dict[str, Any] | None = None) -> None:
        # ltm: openjiuwen LongTermMemory instance (injected at startup)
        self._ltm = ltm
        self._memory_config = memory_config or {}

    async def search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
        memory_types: list[MemoryType] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        try:
            memory_config = getattr(self, "_memory_config", {"top_k": top_k, "score_threshold": 0.3})
            results = await _call_ltm_method(
                self._ltm.search_user_mem,
                query=query,
                num=top_k,
                limit=top_k,
                user_id=scope_id,
                scope_id=scope_id,
                threshold=memory_config.get("score_threshold", 0.3),
                filters=dict(filters or {}),
            )
            items = []
            for r in results:
                mem_info = getattr(r, "mem_info", None)
                memory_type = getattr(mem_info, "type", getattr(r, "memory_type", None))
                if memory_type is not None:
                    try:
                        memory_type = MemoryType(str(memory_type))
                    except ValueError:
                        memory_type = None
                items.append(
                    ContextItem(
                        source_type="ltm",
                        tier="warm",
                        memory_type=memory_type,
                        score=getattr(r, "score", 1.0),
                        content=getattr(mem_info, "content", getattr(r, "memory", getattr(r, "content", str(r)))),
                        metadata={
                            "memory_id": getattr(mem_info, "mem_id", getattr(r, "id", "")),
                            "scope_id": scope_id,
                        },
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
            messages_payload = messages
            agent_config = None
            if _method_accepts_name(self._ltm.add_messages, "agent_config"):
                from openjiuwen.core.foundation.llm import AssistantMessage, UserMessage
                from openjiuwen.core.memory.config.config import AgentMemoryConfig

                role_map = {
                    "assistant": AssistantMessage,
                    "user": UserMessage,
                }
                messages_payload = [
                    role_map.get(message.get("role", "user"), UserMessage)(content=message.get("content", ""))
                    for message in messages
                ]
                agent_config = AgentMemoryConfig(
                    enable_long_term_mem=True,
                    enable_user_profile=True,
                    enable_semantic_memory=True,
                    enable_episodic_memory=True,
                    enable_summary_memory=True,
                )
            await _call_ltm_method(
                self._ltm.add_messages,
                messages=messages_payload,
                agent_config=agent_config,
                user_id=user_id or scope_id,
                scope_id=scope_id,
                session_id=scope_id,
            )
        except Exception as exc:
            raise AdapterError("LTM", str(exc), code=ErrorCode.MEMORY_WRITE_FAILED) from exc

    async def delete_by_id(self, scope_id: str, memory_id: str) -> None:
        try:
            await _call_ltm_method(
                self._ltm.delete_mem_by_id,
                mem_id=memory_id,
                memory_id=memory_id,
                user_id=scope_id,
                scope_id=scope_id,
            )
        except Exception as exc:
            raise AdapterError("LTM", str(exc)) from exc

    async def update_by_id(
        self,
        scope_id: str,
        memory_id: str,
        updates: dict[str, Any],
    ) -> None:
        try:
            memory = updates.get("content", updates.get("memory", ""))
            await _call_ltm_method(
                self._ltm.update_mem_by_id,
                mem_id=memory_id,
                memory_id=memory_id,
                memory=memory,
                user_id=scope_id,
                scope_id=scope_id,
                updates=updates,
            )
        except Exception as exc:
            raise AdapterError("LTM", str(exc)) from exc

    async def health_check(self) -> bool:
        try:
            await _call_ltm_method(
                self._ltm.search_user_mem,
                query="health",
                num=1,
                limit=1,
                user_id="__health__",
                scope_id="__health__",
                threshold=0.0,
            )
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
