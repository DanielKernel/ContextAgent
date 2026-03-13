"""Working memory manager (UC010).

Manages structured notes (scratchpad) stored outside the context window.
Notes live for the duration of a session and are injected on demand.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis

from context_agent.config.settings import get_settings
from context_agent.models.context import ContextItem, MemoryType
from context_agent.models.note import NOTE_CONTENT_SCHEMAS, NoteType, WorkingNote
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class WorkingMemoryManager:
    """CRUD operations for structured working memory notes.

    Storage: Redis hash (key=ca:wm:{scope_id}:{session_id}, field=note_id)
    Fallback: in-process dict when Redis is unavailable.
    """

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._settings = get_settings()
        self._redis = redis_client
        self._local: dict[str, dict[str, str]] = {}  # {hash_key: {note_id: json}}
        self._local_items: dict[str, dict[str, str]] = {}  # {items_key: {item_id: json}}

    def _hash_key(self, scope_id: str, session_id: str) -> str:
        return f"ca:wm:{scope_id}:{session_id}"

    def _items_key(self, scope_id: str, session_id: str) -> str:
        return f"ca:wm-items:{scope_id}:{session_id}"

    async def create_note(self, note: WorkingNote) -> WorkingNote:
        """Persist a new working note. Validates content against schema."""
        await self._validate_content(note.note_type, note.content)

        existing = await self.list_notes(note.scope_id, note.session_id)
        if len(existing) >= self._settings.max_notes_per_session:
            raise ContextAgentError(
                f"Session note limit ({self._settings.max_notes_per_session}) reached",
                code=ErrorCode.INTERNAL_ERROR,
            )

        key = self._hash_key(note.scope_id, note.session_id)
        serialized = note.model_dump_json()
        try:
            if self._redis is not None:
                await self._redis.hset(key, note.note_id, serialized)
                if note.expires_at:
                    ttl = int((note.expires_at - datetime.utcnow()).total_seconds())
                    if ttl > 0:
                        await self._redis.expire(key, ttl)
            else:
                self._local.setdefault(key, {})[note.note_id] = serialized
        except Exception as exc:
            logger.warning("working memory write failed", error=str(exc))
            raise ContextAgentError(
                f"Failed to create note '{note.note_id}'",
                code=ErrorCode.MEMORY_WRITE_FAILED,
                details={"note_id": note.note_id, "cause": str(exc)},
            ) from exc
        return note

    async def get_note(self, scope_id: str, session_id: str, note_id: str) -> WorkingNote:
        """Retrieve a single note by ID."""
        key = self._hash_key(scope_id, session_id)
        try:
            if self._redis is not None:
                raw = await self._redis.hget(key, note_id)
            else:
                raw = self._local.get(key, {}).get(note_id)
            if raw:
                return WorkingNote.model_validate_json(raw)
        except Exception as exc:
            logger.warning("working memory read failed", note_id=note_id, error=str(exc))
            raise ContextAgentError(
                f"Failed to read note '{note_id}'",
                code=ErrorCode.MEMORY_READ_FAILED,
                details={"note_id": note_id, "cause": str(exc)},
            ) from exc
        raise ContextAgentError(
            f"Note '{note_id}' not found",
            code=ErrorCode.NOTE_NOT_FOUND,
        )

    async def list_notes(
        self,
        scope_id: str,
        session_id: str,
        note_type: NoteType | None = None,
    ) -> list[WorkingNote]:
        """List all notes for a session, optionally filtered by type."""
        key = self._hash_key(scope_id, session_id)
        try:
            if self._redis is not None:
                raw_map: dict[Any, Any] = await self._redis.hgetall(key)
            else:
                raw_map = self._local.get(key, {})

            notes = []
            now = datetime.utcnow()
            for raw in raw_map.values():
                note = WorkingNote.model_validate_json(raw)
                if note.expires_at and note.expires_at < now:
                    continue  # skip expired
                if note_type and note.note_type != note_type:
                    continue
                notes.append(note)
            return sorted(notes, key=lambda n: n.created_at)
        except Exception as exc:
            logger.warning("list_notes failed", scope_id=scope_id, error=str(exc))
            raise ContextAgentError(
                f"Failed to list notes for session '{session_id}'",
                code=ErrorCode.MEMORY_READ_FAILED,
                details={"scope_id": scope_id, "session_id": session_id, "cause": str(exc)},
            ) from exc

    async def update_note(
        self,
        scope_id: str,
        session_id: str,
        note_id: str,
        content_updates: dict[str, Any],
    ) -> WorkingNote:
        """Partially update note content."""
        note = await self.get_note(scope_id, session_id, note_id)
        note.content.update(content_updates)
        note.updated_at = datetime.utcnow()
        await self._validate_content(note.note_type, note.content)
        key = self._hash_key(scope_id, session_id)
        try:
            if self._redis is not None:
                await self._redis.hset(key, note.note_id, note.model_dump_json())
            else:
                self._local.setdefault(key, {})[note.note_id] = note.model_dump_json()
        except Exception as exc:
            logger.warning("note update failed", note_id=note_id, error=str(exc))
            raise ContextAgentError(
                f"Failed to update note '{note_id}'",
                code=ErrorCode.MEMORY_WRITE_FAILED,
                details={"note_id": note_id, "cause": str(exc)},
            ) from exc
        return note

    async def delete_note(self, scope_id: str, session_id: str, note_id: str) -> None:
        """Delete a note by ID."""
        key = self._hash_key(scope_id, session_id)
        try:
            if self._redis is not None:
                await self._redis.hdel(key, note_id)
            else:
                self._local.get(key, {}).pop(note_id, None)
        except Exception as exc:
            logger.warning("note delete failed", note_id=note_id, error=str(exc))
            raise ContextAgentError(
                f"Failed to delete note '{note_id}'",
                code=ErrorCode.MEMORY_WRITE_FAILED,
                details={"note_id": note_id, "cause": str(exc)},
            ) from exc

    async def clear_session(self, scope_id: str, session_id: str) -> None:
        """Remove all notes for a session (called on session end)."""
        key = self._hash_key(scope_id, session_id)
        items_key = self._items_key(scope_id, session_id)
        try:
            if self._redis is not None:
                await self._redis.delete(key)
                await self._redis.delete(items_key)
            else:
                self._local.pop(key, None)
                self._local_items.pop(items_key, None)
        except Exception as exc:
            logger.warning("clear_session failed", scope_id=scope_id, error=str(exc))
            raise ContextAgentError(
                f"Failed to clear session '{session_id}'",
                code=ErrorCode.MEMORY_WRITE_FAILED,
                details={"scope_id": scope_id, "session_id": session_id, "cause": str(exc)},
            ) from exc

    async def write(self, scope_id: str, session_id: str, item: ContextItem) -> ContextItem:
        """Persist a working-memory ContextItem for the current session."""
        key = self._items_key(scope_id, session_id)
        serialized = item.model_dump_json()
        try:
            if self._redis is not None:
                await self._redis.hset(key, item.item_id, serialized)
            else:
                self._local_items.setdefault(key, {})[item.item_id] = serialized
        except Exception as exc:
            logger.warning("working memory item write failed", error=str(exc), item_id=item.item_id)
            raise ContextAgentError(
                f"Failed to write working-memory item '{item.item_id}'",
                code=ErrorCode.MEMORY_WRITE_FAILED,
                details={"item_id": item.item_id, "cause": str(exc)},
            ) from exc
        return item

    async def list_items(self, scope_id: str, session_id: str) -> list[ContextItem]:
        """List session-scoped working-memory ContextItems."""
        key = self._items_key(scope_id, session_id)
        try:
            if self._redis is not None:
                raw_map: dict[Any, Any] = await self._redis.hgetall(key)
            else:
                raw_map = self._local_items.get(key, {})
            return [
                ContextItem.model_validate_json(raw)
                for raw in raw_map.values()
            ]
        except Exception as exc:
            logger.warning("list_items failed", scope_id=scope_id, error=str(exc))
            raise ContextAgentError(
                f"Failed to list working-memory items for session '{session_id}'",
                code=ErrorCode.MEMORY_READ_FAILED,
                details={"scope_id": scope_id, "session_id": session_id, "cause": str(exc)},
            ) from exc

    async def to_context_items(
        self, scope_id: str, session_id: str
    ) -> list[ContextItem]:
        """Return working-memory items and notes as injectable ContextItems."""
        items = await self.list_items(scope_id, session_id)
        notes = await self.list_notes(scope_id, session_id)
        for note in notes:
            items.append({
                "item_id": note.note_id,
                "scope_id": scope_id,
                "session_id": session_id,
                "source_type": "working_note",
                "tier": "hot",
                "memory_type": MemoryType.VARIABLE,
                "content": f"[{note.note_type.value.upper()}]\n{json.dumps(note.content, ensure_ascii=False)}",
                "metadata": {"note_type": note.note_type.value, "tags": note.tags},
                "updated_at": note.updated_at,
            })
        return [
            item if isinstance(item, ContextItem) else ContextItem(**item)
            for item in items
        ]
 
    async def mark_used(
        self, scope_id: str, session_id: str, item_ids: list[str]
    ) -> int:
        """Increment active_count on working-memory items matching item_ids.

        This feeds the Hotness Score: items confirmed as useful by callers rank
        higher in future retrievals.

        Returns the number of records actually updated.
        """
        if not item_ids:
            return 0
        id_set = set(item_ids)
        updated = 0

        items = await self.list_items(scope_id, session_id)
        for item in items:
            if item.item_id in id_set:
                item.active_count += 1
                item.updated_at = datetime.utcnow()
                await self.write(scope_id, session_id, item)
                updated += 1

        notes = await self.list_notes(scope_id, session_id)
        for note in notes:
            if note.note_id in id_set:
                active = note.content.get("_active_count", 0) + 1
                await self.update_note(
                    scope_id, note.session_id, note.note_id, {"_active_count": active}
                )
                updated += 1
        return updated

    @staticmethod
    async def _validate_content(note_type: NoteType, content: dict[str, Any]) -> None:
        schema = NOTE_CONTENT_SCHEMAS.get(note_type)
        if schema is None:
            return
        missing = [k for k in schema if k not in content]
        if missing:
            logger.debug("note content missing optional fields", missing=missing, note_type=note_type)
