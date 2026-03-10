"""OpenTelemetry tracing utilities."""

from __future__ import annotations

import functools
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

F = TypeVar("F", bound=Callable[..., Any])

_tracer: trace.Tracer | None = None


def configure_tracing(service_name: str, otlp_endpoint: str = "") -> None:
    """Configure the global TracerProvider. Call once at startup."""
    global _tracer

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)


def get_tracer() -> trace.Tracer:
    """Return the configured tracer (or a no-op tracer if not configured)."""
    if _tracer is not None:
        return _tracer
    return trace.get_tracer("context_agent")


@asynccontextmanager
async def traced_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> AsyncGenerator[trace.Span, None]:
    """Async context manager that creates a named OTel span."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def traced(operation_name: str | None = None) -> Callable[[F], F]:
    """Decorator that wraps an async function in an OTel span."""

    def decorator(func: F) -> F:
        span_name = operation_name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async with traced_span(span_name):
                return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def record_latency(start_time: float) -> float:
    """Return elapsed milliseconds since start_time (from time.monotonic())."""
    return (time.monotonic() - start_time) * 1000.0
