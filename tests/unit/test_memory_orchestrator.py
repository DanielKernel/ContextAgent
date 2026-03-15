"""Unit tests for memory orchestration and working-memory persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock
import logging

import pytest

from context_agent.core.memory.orchestrator import MemoryOrchestrator
from context_agent.core.memory.working_memory import WorkingMemoryManager
from context_agent.models.context import ContextItem, MemoryCategory, MemoryType
from context_agent.models.note import NoteType, WorkingNote


@pytest.mark.asyncio
async def test_working_memory_round_trips_context_items():
    manager = WorkingMemoryManager()
    item = ContextItem(
        scope_id="scope-1",
        session_id="session-1",
        source_type="user",
        memory_type=MemoryType.VARIABLE,
        content="[user] hello",
    )

    await manager.write("scope-1", "session-1", item)
    items = await manager.to_context_items("scope-1", "session-1")

    assert len(items) == 1
    assert items[0].item_id == item.item_id
    assert items[0].content == "[user] hello"


@pytest.mark.asyncio
async def test_working_memory_includes_structured_notes_in_context_items():
    manager = WorkingMemoryManager()
    note = WorkingNote(
        scope_id="scope-1",
        session_id="session-1",
        note_type=NoteType.CURRENT_STATUS,
        content={
            "phase": "implementation",
            "progress_summary": "memory integration in progress",
            "pending_actions": ["add tests"],
        },
    )

    await manager.create_note(note)
    items = await manager.to_context_items("scope-1", "session-1")

    assert len(items) == 1
    assert items[0].item_id == note.note_id
    assert items[0].source_type == "working_note"
    assert items[0].memory_type == MemoryType.VARIABLE


@pytest.mark.asyncio
async def test_working_memory_mark_used_updates_context_items():
    manager = WorkingMemoryManager()
    item = ContextItem(
        scope_id="scope-1",
        session_id="session-1",
        source_type="assistant",
        memory_type=MemoryType.VARIABLE,
        content="[assistant] summary",
    )

    await manager.write("scope-1", "session-1", item)
    updated = await manager.mark_used("scope-1", "session-1", [item.item_id])
    items = await manager.list_items("scope-1", "session-1")

    assert updated == 1
    assert items[0].active_count == 1


@pytest.mark.asyncio
async def test_memory_orchestrator_persists_preferences_to_ltm_queue():
    working_memory = WorkingMemoryManager()
    processor = AsyncMock()
    orchestrator = MemoryOrchestrator(working_memory=working_memory, async_processor=processor)

    stored = await orchestrator.ingest_messages(
        scope_id="scope-1",
        session_id="session-1",
        messages=[{"role": "user", "content": "Please always answer in Chinese."}],
    )

    items = await working_memory.list_items("scope-1", "session-1")

    assert stored == 1
    assert items[0].memory_type == MemoryType.PROCEDURAL
    assert items[0].category == MemoryCategory.PREFERENCES
    processor.enqueue.assert_awaited_once()
    task = processor.enqueue.await_args.args[0]
    assert task.session_id == "session-1"
    assert task.messages[0]["metadata"]["memory_type"] == MemoryType.PROCEDURAL.value


@pytest.mark.asyncio
async def test_memory_orchestrator_honors_explicit_memory_type_requests():
    working_memory = WorkingMemoryManager()
    processor = AsyncMock()
    orchestrator = MemoryOrchestrator(working_memory=working_memory, async_processor=processor)

    await orchestrator.ingest_messages(
        scope_id="scope-1",
        session_id="session-1",
        messages=[
            {
                "role": "user",
                "content": "Daniel is the project owner.",
                "metadata": {"requested_memory_type": "semantic"},
            }
        ],
    )

    items = await working_memory.list_items("scope-1", "session-1")

    assert items[0].memory_type == MemoryType.SEMANTIC
    assert items[0].category == MemoryCategory.PROFILE
    task = processor.enqueue.await_args.args[0]
    assert task.session_id == "session-1"


@pytest.mark.asyncio
async def test_memory_orchestrator_logs_when_ltm_enqueue_is_skipped(caplog):
    working_memory = WorkingMemoryManager()
    orchestrator = MemoryOrchestrator(working_memory=working_memory, async_processor=AsyncMock())

    with caplog.at_level(logging.INFO):
        stored = await orchestrator.ingest_messages(
            scope_id="scope-1",
            session_id="session-1",
            messages=[{"role": "user", "content": "hello there"}],
        )

    assert stored == 1
    assert "ltm enqueue skipped" in caplog.text


@pytest.mark.asyncio
async def test_memory_orchestrator_logs_when_ltm_task_is_enqueued(caplog):
    working_memory = WorkingMemoryManager()
    processor = AsyncMock()
    orchestrator = MemoryOrchestrator(working_memory=working_memory, async_processor=processor)

    with caplog.at_level(logging.INFO):
        await orchestrator.ingest_messages(
            scope_id="scope-1",
            session_id="session-1",
            messages=[{"role": "user", "content": "Please always answer in Chinese."}],
        )

    assert "ltm enqueue planned" in caplog.text
    assert "ltm task enqueued" in caplog.text
