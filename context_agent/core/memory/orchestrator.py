"""High-level memory orchestration on top of working memory and openJiuwen LTM."""

from __future__ import annotations

from typing import Any

from context_agent.core.memory.async_processor import (
    AsyncMemoryProcessor,
    MemoryTask,
    MemoryTaskType,
)
from context_agent.core.memory.working_memory import WorkingMemoryManager
from context_agent.models.context import ContextItem, MemoryCategory, MemoryType
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class MemoryOrchestrator:
    """Coordinates short-term and long-term memory persistence."""

    def __init__(
        self,
        working_memory: WorkingMemoryManager,
        async_processor: AsyncMemoryProcessor | None = None,
    ) -> None:
        self._working_memory = working_memory
        self._async_processor = async_processor

    async def ingest_messages(
        self,
        scope_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        user_id: str = "",
        persist_long_term: bool = True,
    ) -> int:
        """Persist messages into working memory and optionally openJiuwen LTM."""
        stored = 0
        ltm_messages: list[dict[str, Any]] = []

        for message in messages:
            content = str(message.get("content", "")).strip()
            role = str(message.get("role", "")).strip() or "user"
            if not content:
                continue

            memory_signal = self._classify_message(role=role, content=content)
            requested_memory_type = message.get("metadata", {}).get("requested_memory_type")
            if requested_memory_type:
                try:
                    requested_type = MemoryType(str(requested_memory_type))
                    memory_signal = {
                        "should_persist": persist_long_term,
                        "memory_type": requested_type,
                        "category": self._default_category_for_type(requested_type),
                        "reason": "explicit_request",
                    }
                except ValueError:
                    logger.warning("invalid requested memory type", value=requested_memory_type)
            item = ContextItem(
                scope_id=scope_id,
                session_id=session_id,
                source_type=role,
                memory_type=memory_signal["memory_type"],
                category=memory_signal["category"],
                content=f"[{role}] {content}",
                metadata={
                    **message.get("metadata", {}),
                    "role": role,
                    "memory_reason": memory_signal["reason"],
                    "persist_long_term": persist_long_term,
                },
            )
            await self._working_memory.write(scope_id=scope_id, session_id=session_id, item=item)
            stored += 1

            if persist_long_term and memory_signal["should_persist"]:
                ltm_messages.append(
                    {
                        "role": role,
                        "content": content,
                        "metadata": {
                            **message.get("metadata", {}),
                            "scope_id": scope_id,
                            "session_id": session_id,
                            "memory_type": memory_signal["memory_type"].value,
                            "category": memory_signal["category"].value,
                            "memory_reason": memory_signal["reason"],
                        },
                    }
                )

        if ltm_messages and self._async_processor is not None:
            await self._async_processor.enqueue(
                MemoryTask(
                    scope_id=scope_id,
                    task_type=MemoryTaskType.ADD,
                    session_id=session_id,
                    user_id=user_id or scope_id,
                    messages=ltm_messages,
                )
            )
        return stored

    @staticmethod
    def _classify_message(role: str, content: str) -> dict[str, Any]:
        """Classify a message into memory type/category using lightweight heuristics."""
        text = content.lower()

        preference_markers = [
            "prefer",
            "always",
            "remember that i like",
            "请用",
            "以后请",
            "偏好",
            "记住我喜欢",
            "请始终",
        ]
        profile_markers = [
            "my name is",
            "i am ",
            "i work at",
            "我是",
            "我叫",
            "我的名字",
            "我在",
        ]
        conclusion_markers = [
            "we decided",
            "decision:",
            "final decision",
            "resolved",
            "completed",
            "done",
            "决定",
            "结论",
            "已完成",
            "完成了",
            "最终方案",
        ]

        if any(marker in text for marker in preference_markers):
            return {
                "should_persist": True,
                "memory_type": MemoryType.PROCEDURAL,
                "category": MemoryCategory.PREFERENCES,
                "reason": "preference",
            }

        if role == "user" and any(marker in text for marker in profile_markers):
            return {
                "should_persist": True,
                "memory_type": MemoryType.SEMANTIC,
                "category": MemoryCategory.PROFILE,
                "reason": "profile",
            }

        if any(marker in text for marker in conclusion_markers):
            return {
                "should_persist": True,
                "memory_type": MemoryType.EPISODIC,
                "category": MemoryCategory.EVENTS,
                "reason": "episodic_conclusion",
            }

        return {
            "should_persist": False,
            "memory_type": MemoryType.VARIABLE,
            "category": MemoryCategory.EVENTS,
            "reason": "working_memory_only",
        }

    @staticmethod
    def _default_category_for_type(memory_type: MemoryType) -> MemoryCategory:
        mapping = {
            MemoryType.PROCEDURAL: MemoryCategory.PREFERENCES,
            MemoryType.SEMANTIC: MemoryCategory.PROFILE,
            MemoryType.EPISODIC: MemoryCategory.EVENTS,
            MemoryType.VARIABLE: MemoryCategory.EVENTS,
        }
        return mapping[memory_type]
