"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import os
import sys

import structlog


def _should_use_colors(stream: object | None = None) -> bool:
    """Return True only for interactive terminals unless env overrides it."""
    force_color = os.getenv("FORCE_COLOR")
    if force_color and force_color != "0":
        return True

    if os.getenv("NO_COLOR") is not None:
        return False

    output_stream = stream or sys.stdout
    is_tty = getattr(output_stream, "isatty", None)
    if callable(is_tty):
        return bool(is_tty())
    return False


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog with shared processors and output format."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=_should_use_colors(sys.stdout))

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level.upper())


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog logger bound to the given name."""
    return structlog.get_logger(name)


def bind_context(**kwargs: object) -> None:
    """Bind key-value pairs to the current async context for all log calls."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context vars (call at request end)."""
    structlog.contextvars.clear_contextvars()
