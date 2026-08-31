"""
Logging setup.

1. Structured (JSON) logs instead of formatted strings, so you can actually
   query/filter logs later (e.g. "show me every tool call that failed for
   request X") instead of grepping.
2. Two separate log destinations:
   - app.log        -> HTTP/system level events (request in/out, errors)
   - agent_trace.log -> every agent step, tool call, retry, validation
                        failure. This is the one you read when debugging a
                        bad recommendation or a tool error.

Both streams share the same request_id/symbol/agent/task context via
structlog contextvars, so you can correlate them.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import structlog

from app.config import get_settings


def _configure_stdlib_logging(log_dir: Path, log_level: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=5_000_000, backupCount=3
    )
    trace_handler = logging.handlers.RotatingFileHandler(
        log_dir / "agent_trace.log", maxBytes=5_000_000, backupCount=3
    )
    stdout_handler = logging.StreamHandler(sys.stdout)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [app_handler, stdout_handler]

    trace_logger = logging.getLogger("agent_trace")
    trace_logger.setLevel(log_level)
    trace_logger.handlers = [trace_handler, stdout_handler]
    trace_logger.propagate = False


def setup_logging() -> None:
    settings = get_settings()
    _configure_stdlib_logging(Path(settings.log_dir), settings.log_level)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
    for handler in logging.getLogger("agent_trace").handlers:
        handler.setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """App-level logger (requests, startup, top-level errors)."""
    return structlog.get_logger(name)


def get_trace_logger() -> structlog.stdlib.BoundLogger:
    """Agent/tool-level logger -> writes to agent_trace.log."""
    return structlog.get_logger("agent_trace")


def bind_request_context(**kwargs) -> None:
    """Bind fields (request_id, symbol, agent_name, ...) to all subsequent
    log lines on this async task/thread until clear_request_context()."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
