# app/core/log.py
"""
Core logging configuration for the application.

This module sets up structlog to provide structured, context-aware logging.
It supports both human-readable console output for development and JSON
output for production environments.
"""

import logging
import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import TextIO

import structlog
from app.core.config import settings
from structlog.types import Processor

# A global logger instance for easy access throughout the application
logger: structlog.stdlib.BoundLogger = structlog.get_logger()

# Guard to prevent duplicate handler registration
_logging_configured = False


def setup_logging(stream: TextIO = sys.stdout) -> None:
    """
    Configures logging for the entire application.

    This function is idempotent - safe to call multiple times.
    Only the first call has any effect. It sets up structlog with processors
    for structured logging and routes all standard library logging through
    structlog to ensure consistent log formats.
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True
    # Type hint for the list of processors
    shared_processors: list[Processor] = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            # Prepare event dict for `ProcessorFormatter`.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Define the formatter based on the environment
    if settings.APP_ENV == "dev":
        formatter = structlog.stdlib.ProcessorFormatter(
            # The final processor formats the log entry for console output.
            # No locals: structlog's default renders every frame's
            # variables, and a pydantic-ai agent is thousands of lines,
            # formatted while the request waits.
            processor=structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.RichTracebackFormatter(
                    show_locals=False
                ),
            ),
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            # The final processor formats the log entry as JSON.
            processor=structlog.processors.JSONRenderer(),
            # Remove metadata added by ProcessorFormatter
            foreign_pre_chain=shared_processors,
        )

    # Configure the root logger
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()

    # Clear existing handlers to prevent duplicates (e.g., Alembic reconfigures)
    root_logger.handlers.clear()

    # CRITICAL: Set log level BEFORE adding handler
    # This ensures all loggers (including import-time loggers) respect the level
    log_level = settings.LOG_LEVEL.upper()
    root_logger.setLevel(getattr(logging, log_level))

    # Add handler after level is set
    root_logger.addHandler(handler)

    # Adjust log levels for noisy third-party libraries
    logging.getLogger("flet_core").setLevel(logging.INFO)
    logging.getLogger("flet_runtime").setLevel(logging.INFO)
    logging.getLogger("flet_fastapi").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(
        logging.WARNING
    )  # Suppress HTTP request logs from health checks

    # Stripe SDK logs every API call at INFO ("Request to Stripe api" /
    # "Stripe API response"). The 60s health-probe cache keeps real
    # call rate to ~1/min/process, but each call is two lines and dev
    # restarts wipe the cache, so the log is still chatty. Errors
    # still surface at WARNING+.
    logging.getLogger("stripe").setLevel(logging.WARNING)

    # Suppress RAG service logs (CLI uses progress bar instead)
    logging.getLogger("app.services.rag").setLevel(logging.WARNING)

    # Suppress ChromaDB telemetry errors (posthog.py line 61)
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

    log_format = "DEV" if settings.APP_ENV == "dev" else "JSON"
    logger.debug(
        "Logging setup complete",
        level=log_level,
        log_format=log_format,
        root_level=root_logger.level,
        effective_level=root_logger.getEffectiveLevel(),
    )


@contextmanager
def suppress_logs(level: int = logging.ERROR) -> Generator[None]:
    """
    Temporarily suppress logs during CLI operations.

    Sets the root logger to the specified level to hide lower-priority logs
    while preserving higher-priority logs for critical issues.

    Args:
        level: Minimum log level to show (default: ERROR)

    Yields:
        None
    """
    root_logger = logging.getLogger()
    original_level = root_logger.level
    try:
        root_logger.setLevel(level)
        yield
    finally:
        root_logger.setLevel(original_level)
