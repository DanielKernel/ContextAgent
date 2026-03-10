"""Working memory manager (UC010).

Manages structured notes (scratchpad) stored outside the context window.
Notes live for the duration of a session and are injected on demand.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis

from context_agent.config.defaults import MAX_NOTES_PER_SESSION
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
        self._redis = redis_client
        self._local: dict[str, dict[str, str]] = {}  # {hash_key: {note_id: json}}

    def _hash_key(self, scope_id: str, session_id: str) -> str:
        return f"ca:wm:{scope_id}:{session_id}"

    async def create_note(self, note: WorkingNote) -> WorkingNote:
        """Persist a new working note. Validates content against schema."""
        await self._validate_content(note.note_type, note.content)

        existing = await self.list_notes(note.scope_id, note.session_id)
        if len(existing) >= MAX_NOTES_PER_SESSION:
            raise ContextAgentError(
                f"Session note limit ({MAX_NOTES_PER_SESSION}) reached",
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
            return []

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

    async def clear_session(self, scope_id: str, session_id: str) -> None:
        """Remove all notes for a session (called on session end)."""
        key = self._hash_key(scope_id, session_id)
        try:
            if self._redis is not None:
                await self._redis.delete(key)
            else:
                self._local.pop(key, None)
        except Exception as exc:
            logger.warning("clear_session failed", scope_id=scope_id, error=str(exc))

    async def to_context_items(
        self, scope_id: str, session_id: str
    ) -> list[dict[str, Any]]:
        """Serialize notes as injectable message dicts for context injection."""
        notes = await self.list_notes(scope_id, session_id)
        items = []
        for note in notes:
            items.append({
                "role": "system",
                "content": f"[{note.note_type.value.upper()}]\n{json.dumps(note.content, ensure_ascii=False)}",
            })
        return items

    @staticmethod
    async def _validate_content(note_type: NoteType, content: dict[str, Any]) -> None:
        schema = NOTE_CONTENT_SCHEMAS.get(note_type)
        if schema is None:
            return
        missing = [k for k in schema if k not in content]
        if missing:
            logger.debug("note content missing optional fields", missing=missing, note_type=note_type)
