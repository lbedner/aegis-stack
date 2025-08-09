# app/core/log.py
"""
Core logging configuration for the application.

This module sets up structlog to provide structured, context-aware logging.
It supports both human-readable console output for development and JSON
output for production environments.
"""

import logging
import sys

import structlog
from structlog.types import Processor

from app.core.config import settings

# A global logger instance for easy access throughout the application
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


def setup_logging() -> None:
    """
    Configures logging for the entire application.

    This function sets up structlog with processors for structured logging.
    It routes all standard library logging through structlog to ensure
    consistent log formats. The output format is determined by the APP_ENV
    setting (dev-friendly console format or production-ready JSON format).
    """
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
            processor=structlog.dev.ConsoleRenderer(colors=True),
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            # The final processor formats the log entry as JSON.
            processor=structlog.processors.JSONRenderer(),
            # Remove metadata added by ProcessorFormatter
            foreign_pre_chain=shared_processors,
        )

    # Configure the root logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.LOG_LEVEL.upper())

    # Adjust log levels for noisy third-party libraries
    logging.getLogger("flet_core").setLevel(logging.INFO)
    logging.getLogger("flet_runtime").setLevel(logging.INFO)
    logging.getLogger("flet_fastapi").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    log_format = "DEV" if settings.APP_ENV == "dev" else "JSON"
    logger.info(
        "Logging setup complete",
        level=settings.LOG_LEVEL,
        log_format=log_format,
    )
