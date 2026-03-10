"""Monitoring collector (UC016).

Collects MetricRecords from across the system via an asyncio queue,
batches them, and emits to OpenTelemetry / Prometheus.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from context_agent.models.metrics import MetricRecord
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

# Prometheus optional import
try:
    from prometheus_client import Counter, Histogram

    LATENCY_HISTOGRAM = Histogram(
        "context_agent_latency_seconds",
        "End-to-end context retrieval latency",
        ["operation", "scope_id"],
        buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0),
    )
    REQUEST_COUNTER = Counter(
        "context_agent_requests_total",
        "Total context retrieval requests",
        ["operation", "status"],
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


class MonitoringCollector:
    """Asynchronous metrics collector.

    Usage:
        collector = MonitoringCollector()
        await collector.start()
        await collector.emit(record)
        ...
        await collector.stop()
    """

    def __init__(self, batch_size: int = 50, flush_interval_s: float = 5.0) -> None:
        self._queue: asyncio.Queue[MetricRecord | None] = asyncio.Queue()
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._worker_task: asyncio.Task | None = None
        self._subscribers: list[Callable[[list[MetricRecord]], None]] = []

    def subscribe(self, callback: Callable[[list[MetricRecord]], None]) -> None:
        """Register an external callback to receive metric batches."""
        self._subscribers.append(callback)

    async def start(self) -> None:
        """Start the background flush worker."""
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        """Gracefully stop the worker, flushing remaining records."""
        await self._queue.put(None)
        if self._worker_task:
            await self._worker_task

    async def emit(self, record: MetricRecord) -> None:
        """Enqueue a metric record for async processing."""
        await self._queue.put(record)

    def emit_sync(self, record: MetricRecord) -> None:
        """Non-blocking emit (drops if queue full)."""
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            logger.warning("metric queue full, dropping record", operation=record.operation)

    # ── Worker ────────────────────────────────────────────────────────────────

    async def _worker(self) -> None:
        batch: list[MetricRecord] = []
        last_flush = time.monotonic()

        while True:
            try:
                # Wait up to flush_interval for next item
                remaining = self._flush_interval_s - (time.monotonic() - last_flush)
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=max(0.1, remaining)
                )
                if item is None:  # shutdown sentinel
                    if batch:
                        await self._flush(batch)
                    return
                batch.append(item)
            except asyncio.TimeoutError:
                pass

            if len(batch) >= self._batch_size or (
                time.monotonic() - last_flush >= self._flush_interval_s and batch
            ):
                await self._flush(batch)
                batch = []
                last_flush = time.monotonic()

    async def _flush(self, batch: list[MetricRecord]) -> None:
        """Emit a batch of records to all configured backends."""
        for record in batch:
            self._emit_otel(record)
            self._emit_prometheus(record)

        # Notify subscribers
        for callback in self._subscribers:
            try:
                callback(batch)
            except Exception as exc:
                logger.warning("subscriber callback failed", error=str(exc))

        logger.debug("metrics flushed", count=len(batch))

    @staticmethod
    def _emit_otel(record: MetricRecord) -> None:
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            if span.is_recording():
                span.set_attribute("context_agent.operation", record.operation)
                span.set_attribute("context_agent.latency_ms", record.latency_ms)
                span.set_attribute("context_agent.status", record.status)
        except Exception:
            pass

    @staticmethod
    def _emit_prometheus(record: MetricRecord) -> None:
        if not _PROMETHEUS_AVAILABLE:
            return
        try:
            LATENCY_HISTOGRAM.labels(
                operation=record.operation,
                scope_id=record.scope_id,
            ).observe(record.latency_ms / 1000.0)
            REQUEST_COUNTER.labels(
                operation=record.operation,
                status=record.status,
            ).inc()
        except Exception:
            pass
