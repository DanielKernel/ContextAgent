"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import os
import sys

import structlog

_QUIET_LOGGERS = (
    "httpx",
    "httpcore",
)


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
    # Pre-emptively suppress library logging to avoid duplicates during startup
    suppress_library_logging()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            }
        ),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # Match the pipe-delimited format: TIME | LOGGER | FILE | LINE | FUNC | TRACE | LEVEL | MSG
        def custom_renderer(_, __, event_dict):
            timestamp = event_dict.pop("timestamp", "")
            level = event_dict.pop("level", "").upper()
            event = event_dict.pop("event", "")
            logger_name = event_dict.pop("logger", "root")
            filename = event_dict.pop("filename", "")
            lineno = event_dict.pop("lineno", "")
            func_name = event_dict.pop("func_name", "")
            
            # Trace ID from context if available
            trace_id = event_dict.pop("trace_id", "default_trace_id")
            
            # Additional context
            context_str = ""
            if event_dict:
                # Format remaining keys as json-like or simple kv
                # But typically we want the message clean. 
                # Let's append remaining keys at the end if any.
                try:
                    import json
                    context_str = " " + json.dumps(event_dict, default=str)
                except:
                    context_str = " " + str(event_dict)

            return (
                f"{timestamp} | {logger_name} | {filename} | {lineno} | {func_name} | "
                f"{trace_id} | {level} | {event}{context_str}"
            )

        renderer = custom_renderer

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

    for logger_name in _QUIET_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog logger bound to the given name."""
    return structlog.get_logger(name)


def bind_context(**kwargs: object) -> None:
    """Bind key-value pairs to the current async context for all log calls."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context vars (call at request end)."""
    structlog.contextvars.clear_contextvars()


def suppress_library_logging() -> int:
    """Remove handlers from openJiuwen loggers to prevent duplicate output.

    The openJiuwen library attaches StreamHandlers to its loggers upon initialization,
    which conflicts with our root logger configuration. This function detects
    these loggers and removes their handlers so logs propagate cleanly to root.
    """
    import logging
    import inspect

    count = 0
    # 1. Check loaded loggers in logging.Logger.manager.loggerDict
    # Explicitly ensure 'common' logger is cleaned if it exists or will exist
    for target in ["common", "openjiuwen", "interface", "memory", "performance"]:
        if target in logging.Logger.manager.loggerDict:
            logger = logging.getLogger(target)
            if logger.handlers:
                for h in list(logger.handlers):
                    logger.removeHandler(h)
                count += 1
            logger.propagate = True

    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and (
            name.startswith("openjiuwen") or name in ("common", "interface", "memory", "performance")
        ):
            if logger.handlers:
                for h in list(logger.handlers):
                    logger.removeHandler(h)
                count += 1
                # Ensure propagation is enabled so root logger gets it
                logger.propagate = True

    # 2. Check LazyLoggers in openjiuwen.core.common.logging if available
    try:
        import openjiuwen.core.common.logging as oj_logging
        
        # Force initialization if needed
        if hasattr(oj_logging, "_ensure_initialized"):
            oj_logging._ensure_initialized()
            
        for name, obj in inspect.getmembers(oj_logging):
            if isinstance(obj, oj_logging.LazyLogger):
                try:
                    # Access handlers to trigger init
                    handlers = getattr(obj, "handlers", [])
                    if handlers:
                        for h in list(handlers):
                            obj.removeHandler(h)
                        count += 1
                except Exception:
                    pass
    except ImportError:
        pass
        
    return count
