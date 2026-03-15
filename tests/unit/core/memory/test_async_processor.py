"""Unit tests for AsyncMemoryProcessor (UC008)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from context_agent.core.memory.async_processor import (
    AsyncMemoryProcessor,
    MemoryTask,
    MemoryTaskType,
)
from context_agent.models.context import ContextItem, MemoryType
from context_agent.utils.errors import ContextAgentError, ErrorCode


def _variable_item() -> ContextItem:
    return ContextItem(
        source_type="ltm",
        content="latest variable state",
        memory_type=MemoryType.VARIABLE,
    )


@pytest.mark.asyncio
class TestAsyncMemoryProcessor:
    async def test_add_task_runs_checker_warms_cache_and_notifies(self):
        ltm = AsyncMock()
        ltm.search = AsyncMock(return_value=[_variable_item()])
        tiered_router = AsyncMock()
        checker = AsyncMock()
        checker.check = AsyncMock(
            return_value=SimpleNamespace(
                messages=[{"role": "user", "content": "normalized preference"}]
            )
        )

        events = []
        processor = AsyncMemoryProcessor(
            ltm=ltm,
            tiered_router=tiered_router,
            mem_update_checker=checker,
            worker_count=1,
        )
        processor.subscribe(lambda event: events.append(event))

        await processor.start()
        await processor.enqueue(
            MemoryTask(
                scope_id="scope-1",
                task_type=MemoryTaskType.ADD,
                session_id="session-1",
                messages=[{"role": "user", "content": "raw preference"}],
                user_id="user-1",
            )
        )
        await processor._queue.join()
        await processor.stop()

        checker.check.assert_awaited_once()
        ltm.add_messages.assert_awaited_once_with(
            scope_id="scope-1",
            session_id="session-1",
            messages=[{"role": "user", "content": "normalized preference"}],
            user_id="user-1",
        )
        tiered_router.warm_cache.assert_awaited_once()
        assert len(events) == 1
        assert events[0].success is True

    async def test_add_task_logs_start_and_success(self, caplog):
        ltm = AsyncMock()
        processor = AsyncMemoryProcessor(ltm=ltm, worker_count=1)

        await processor.start()
        with caplog.at_level(logging.INFO):
            await processor.enqueue(
                MemoryTask(
                    scope_id="scope-1",
                    task_type=MemoryTaskType.ADD,
                    session_id="session-1",
                    messages=[{"role": "user", "content": "remember this"}],
                )
            )
            await processor._queue.join()
        await processor.stop()

        assert "ltm task processing started" in caplog.text
        assert "ltm task processing succeeded" in caplog.text

    async def test_checker_failure_does_not_block_add(self):
        ltm = AsyncMock()
        checker = AsyncMock()
        checker.check = AsyncMock(side_effect=RuntimeError("checker down"))
        processor = AsyncMemoryProcessor(
            ltm=ltm,
            mem_update_checker=checker,
            worker_count=1,
        )

        await processor.start()
        await processor.enqueue(
            MemoryTask(
                scope_id="scope-1",
                task_type=MemoryTaskType.ADD,
                session_id="session-1",
                messages=[{"role": "user", "content": "keep this"}],
            )
        )
        await processor._queue.join()
        await processor.stop()

        ltm.add_messages.assert_awaited_once_with(
            scope_id="scope-1",
            session_id="session-1",
            messages=[{"role": "user", "content": "keep this"}],
            user_id="",
        )

    async def test_update_and_delete_tasks_call_ltm_methods(self):
        ltm = AsyncMock()
        processor = AsyncMemoryProcessor(ltm=ltm, worker_count=1)

        await processor.start()
        await processor.enqueue(
            MemoryTask(
                scope_id="scope-1",
                task_type=MemoryTaskType.UPDATE,
                memory_id="mem-1",
                updates={"content": "new value"},
            )
        )
        await processor.enqueue(
            MemoryTask(
                scope_id="scope-1",
                task_type=MemoryTaskType.DELETE,
                memory_id="mem-2",
            )
        )
        await processor._queue.join()
        await processor.stop()

        ltm.update_by_id.assert_awaited_once_with("scope-1", "mem-1", {"content": "new value"})
        ltm.delete_by_id.assert_awaited_once_with("scope-1", "mem-2")

    async def test_enqueue_raises_when_queue_is_full(self):
        ltm = AsyncMock()
        processor = AsyncMemoryProcessor(ltm=ltm, queue_maxsize=1, worker_count=1)

        await processor.enqueue(
            MemoryTask(scope_id="scope-1", task_type=MemoryTaskType.ADD)
        )

        with pytest.raises(ContextAgentError) as exc_info:
            await processor.enqueue(
                MemoryTask(scope_id="scope-1", task_type=MemoryTaskType.ADD)
            )

        assert exc_info.value.code == ErrorCode.MEMORY_WRITE_FAILED

    async def test_worker_logs_session_id_on_failure(self, caplog):
        ltm = AsyncMock()
        ltm.add_messages = AsyncMock(side_effect=RuntimeError("boom"))
        processor = AsyncMemoryProcessor(ltm=ltm, worker_count=1)

        await processor.start()
        with caplog.at_level(logging.ERROR):
            await processor.enqueue(
                MemoryTask(
                    scope_id="scope-1",
                    task_type=MemoryTaskType.ADD,
                    session_id="session-9",
                    messages=[{"role": "user", "content": "fail me"}],
                )
            )
            await processor._queue.join()
        await processor.stop()

        assert "memory task processing failed" in caplog.text
        assert "session-9" in caplog.text
