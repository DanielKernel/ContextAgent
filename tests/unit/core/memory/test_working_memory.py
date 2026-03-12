"""Unit tests for WorkingMemoryManager error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_agent.core.memory.working_memory import WorkingMemoryManager
from context_agent.models.context import ContextItem, MemoryType
from context_agent.models.note import NoteType, WorkingNote
from context_agent.utils.errors import ContextAgentError, ErrorCode


@pytest.mark.asyncio
class TestWorkingMemoryManagerErrors:
    async def test_create_note_raises_memory_write_failed_on_storage_error(self):
        redis_client = AsyncMock()
        redis_client.hgetall = AsyncMock(return_value={})
        redis_client.hset = AsyncMock(side_effect=RuntimeError("redis down"))
        manager = WorkingMemoryManager(redis_client=redis_client)
        note = WorkingNote(
            scope_id="scope-1",
            session_id="session-1",
            note_type=NoteType.TASK_PLAN,
            content={"steps": ["a"]},
        )

        with pytest.raises(ContextAgentError) as exc_info:
            await manager.create_note(note)

        assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED

    async def test_get_note_raises_memory_read_failed_on_storage_error(self):
        redis_client = AsyncMock()
        redis_client.hget = AsyncMock(side_effect=RuntimeError("redis down"))
        manager = WorkingMemoryManager(redis_client=redis_client)

        with pytest.raises(ContextAgentError) as exc_info:
            await manager.get_note("scope-1", "session-1", "note-1")

        assert exc_info.value.code == ErrorCode.MEMORY_READ_FAILED

    async def test_write_raises_memory_write_failed_on_storage_error(self):
        redis_client = AsyncMock()
        redis_client.hset = AsyncMock(side_effect=RuntimeError("redis down"))
        manager = WorkingMemoryManager(redis_client=redis_client)
        item = ContextItem(
            source_type="assistant",
            memory_type=MemoryType.VARIABLE,
            content="state",
        )

        with pytest.raises(ContextAgentError) as exc_info:
            await manager.write("scope-1", "session-1", item)

        assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED
