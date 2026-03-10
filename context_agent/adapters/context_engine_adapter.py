"""Context engine adapter.

Defines ContextEnginePort (ABC) and openJiuwen ContextEngine implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from context_agent.utils.errors import AdapterError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class ContextEnginePort(ABC):
    """Abstract interface for context window management operations."""

    @abstractmethod
    async def get_context(
        self,
        scope_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Return the current context messages for this scope/session."""

    @abstractmethod
    async def save_contexts(
        self,
        scope_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Persist updated context messages."""

    @abstractmethod
    async def add_messages(
        self,
        scope_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Append messages to the current context window."""

    @abstractmethod
    async def clear_context(self, scope_id: str, session_id: str) -> None:
        """Clear the context window for this scope/session."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the context engine is reachable."""


class OpenJiuwenContextEngineAdapter(ContextEnginePort):
    """openJiuwen ContextEngine implementation of ContextEnginePort."""

    def __init__(self, context_engine: Any) -> None:
        self._ce = context_engine

    async def get_context(
        self,
        scope_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        try:
            ctx = await self._ce.get_context(user_id=scope_id, session_id=session_id)
            if isinstance(ctx, list):
                return ctx
            # Some versions return a dict with a "messages" key
            return ctx.get("messages", []) if isinstance(ctx, dict) else []
        except Exception as exc:
            logger.warning("context_engine.get_context failed", scope_id=scope_id, error=str(exc))
            raise AdapterError("ContextEngine", str(exc), code=ErrorCode.OPENJIUWEN_UNAVAILABLE) from exc

    async def save_contexts(
        self,
        scope_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        try:
            await self._ce.save_contexts(
                user_id=scope_id,
                session_id=session_id,
                messages=messages,
            )
        except Exception as exc:
            raise AdapterError("ContextEngine", str(exc)) from exc

    async def add_messages(
        self,
        scope_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        try:
            await self._ce.add_messages(
                user_id=scope_id,
                session_id=session_id,
                messages=messages,
            )
        except Exception as exc:
            raise AdapterError("ContextEngine", str(exc)) from exc

    async def clear_context(self, scope_id: str, session_id: str) -> None:
        try:
            await self._ce.clear_context(user_id=scope_id, session_id=session_id)
        except Exception as exc:
            raise AdapterError("ContextEngine", str(exc)) from exc

    async def health_check(self) -> bool:
        try:
            await self._ce.get_context(user_id="__health__", session_id="__health__")
            return True
        except Exception:
            return False
