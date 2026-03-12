"""Async memory processor (UC008).

Processes long-term memory updates asynchronously, decoupled from the main request path.
Uses asyncio.Queue (single-process) or Pulsar (distributed deployment).

After processing:
- Publishes MEMORY_UPDATED internal event
- Triggers hot-tier cache refresh via TieredMemoryRouter.warm_cache()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from context_agent.adapters.ltm_adapter import LongTermMemoryPort
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger

if TYPE_CHECKING:
    from context_agent.core.memory.tiered_router import TieredMemoryRouter

logger = get_logger(__name__)


class MemoryTaskType(str, Enum):
    ADD = "add"
    DELETE = "delete"
    UPDATE = "update"
    CHECK_CONFLICTS = "check_conflicts"


@dataclass
class MemoryTask:
    scope_id: str
    task_type: MemoryTaskType
    user_id: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    memory_id: str = ""
    updates: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    callback_event: str = "MEMORY_UPDATED"


class MemoryUpdatedEvent:
    """Internal event emitted after successful memory processing."""

    def __init__(self, scope_id: str, task_type: MemoryTaskType, success: bool) -> None:
        self.scope_id = scope_id
        self.task_type = task_type
        self.success = success
        self.timestamp = datetime.utcnow()


class AsyncMemoryProcessor:
    """Asynchronous memory processing queue (ADR-005).

    Enqueue memory tasks from the write path; workers consume and process
    them without blocking the caller. Subscribers can register to receive
    MEMORY_UPDATED events.
    """

    def __init__(
        self,
        ltm: LongTermMemoryPort,
        tiered_router: TieredMemoryRouter | None = None,
        mem_update_checker: Any | None = None,  # openjiuwen MemUpdateChecker
        queue_maxsize: int = 1000,
        worker_count: int = 2,
    ) -> None:
        self._ltm = ltm
        self._tiered_router = tiered_router
        self._checker = mem_update_checker  # openjiuwen.core.memory.manage.update.mem_update_checker
        self._queue: asyncio.Queue[MemoryTask] = asyncio.Queue(maxsize=queue_maxsize)
        self._worker_count = worker_count
        self._workers: list[asyncio.Task[None]] = []
        self._subscribers: list[Any] = []  # callables that accept MemoryUpdatedEvent
        self._running = False

    async def start(self) -> None:
        """Start background worker tasks."""
        if self._running:
            return
        self._running = True
        for _ in range(self._worker_count):
            task = asyncio.create_task(self._worker_loop())
            self._workers.append(task)
        logger.info("AsyncMemoryProcessor started", workers=self._worker_count)

    async def stop(self) -> None:
        """Drain the queue and stop workers."""
        self._running = False
        for _ in self._workers:
            await self._queue.put(None)  # type: ignore[arg-type]  # sentinel
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("AsyncMemoryProcessor stopped")

    async def enqueue(self, task: MemoryTask) -> None:
        """Enqueue a memory task (non-blocking; raises if queue is full)."""
        try:
            self._queue.put_nowait(task)
        except asyncio.QueueFull:
            logger.warning("memory queue full, dropping task", scope_id=task.scope_id)
            raise ContextAgentError(
                "Async memory queue is full",
                code=ErrorCode.MEMORY_WRITE_FAILED,
                details={"scope_id": task.scope_id, "task_type": task.task_type.value},
            )

    def subscribe(self, handler: Any) -> None:
        """Register a coroutine function to receive MEMORY_UPDATED events."""
        self._subscribers.append(handler)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        while True:
            task = await self._queue.get()
            if task is None:  # sentinel
                self._queue.task_done()
                break
            try:
                await self._process(task)
            except Exception as exc:
                logger.error(
                    "memory task processing failed",
                    scope_id=task.scope_id,
                    task_type=task.task_type,
                    error=str(exc),
                )
            finally:
                self._queue.task_done()

    async def _process(self, task: MemoryTask) -> None:
        success = False
        try:
            if task.task_type == MemoryTaskType.ADD:
                # Run conflict/duplicate check if checker is available
                if self._checker is not None:
                    try:
                        check_result = await self._checker.check(
                            messages=task.messages,
                            user_id=task.user_id or task.scope_id,
                        )
                        # checker may return deduplicated/updated messages
                        if check_result and hasattr(check_result, "messages"):
                            task.messages = check_result.messages
                    except Exception as exc:
                        logger.warning(
                            "MemUpdateChecker failed, skipping",
                            scope_id=task.scope_id,
                            task_type=task.task_type,
                            error=str(exc),
                        )

                await self._ltm.add_messages(
                    scope_id=task.scope_id,
                    messages=task.messages,
                    user_id=task.user_id,
                )

            elif task.task_type == MemoryTaskType.DELETE:
                await self._ltm.delete_by_id(task.scope_id, task.memory_id)

            elif task.task_type == MemoryTaskType.UPDATE:
                await self._ltm.update_by_id(task.scope_id, task.memory_id, task.updates)

            success = True

            # Refresh hot-tier cache after successful write
            if self._tiered_router is not None and task.task_type == MemoryTaskType.ADD:
                try:
                    items = await self._ltm.search(
                        scope_id=task.scope_id, query="", top_k=20
                    )
                    await self._tiered_router.warm_cache(task.scope_id, items)
                except Exception as exc:
                    logger.warning(
                        "hot tier warm after write failed",
                        scope_id=task.scope_id,
                        task_type=task.task_type,
                        error=str(exc),
                    )

        finally:
            event = MemoryUpdatedEvent(task.scope_id, task.task_type, success)
            await self._notify(event)

    async def _notify(self, event: MemoryUpdatedEvent) -> None:
        for handler in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as exc:
                logger.warning(
                    "memory event subscriber failed",
                    scope_id=event.scope_id,
                    task_type=event.task_type,
                    error=str(exc),
                )
