# app/core/config.py
"""
Application configuration management using Pydantic's BaseSettings.

This module centralizes application settings, allowing them to be loaded
from environment variables for easy configuration in different environments.
"""

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Defines application settings.
    `model_config` is used to specify that settings should be loaded from a .env file.
    """

    # Application environment: "dev" or "prod"
    APP_ENV: str = "dev"

    # Log level for the application
    LOG_LEVEL: str = "INFO"

    # Port for the web server
    PORT: int = 8000

    # Development settings
    AUTO_RELOAD: bool = False

    # Docker settings (used by docker-compose)
    AEGIS_STACK_TAG: str = "aegis-stack:latest"
    AEGIS_STACK_VERSION: str = "dev"

    # Health monitoring and alerting
    HEALTH_CHECK_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL_MINUTES: int = 5

    # Health check performance settings
    HEALTH_CHECK_TIMEOUT_SECONDS: float = 2.0
    SYSTEM_METRICS_CACHE_SECONDS: int = 5

    # Basic alerting configuration
    ALERTING_ENABLED: bool = False
    ALERT_COOLDOWN_MINUTES: int = 60  # Minutes between repeated alerts for same issue

    # Health check thresholds
    MEMORY_THRESHOLD_PERCENT: float = 90.0
    DISK_THRESHOLD_PERCENT: float = 85.0
    CPU_THRESHOLD_PERCENT: float = 95.0

    # Redis settings for arq background tasks
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_DB: int = 0

    # arq worker settings
    WORKER_CONCURRENCY: int = 10
    WORKER_TIMEOUT_SECONDS: int = 300
    WORKER_KEEP_RESULT_SECONDS: int = 3600  # Keep job results for 1 hour
    WORKER_MAX_TRIES: int = 3

    # Worker queue configuration - functional domains
    WORKER_QUEUES: dict[str, dict[str, Any]] = {
        "media": {
            "queue_name": "arq:queue:media",
            "description": "Image and file processing",
            "max_jobs": 10,          # I/O-bound file operations, increased concurrency
            "timeout_seconds": 600,  # File processing can take time
        },
        "system": {
            "queue_name": "arq:queue:system", 
            "description": "System maintenance and monitoring tasks",
            "max_jobs": 20,          # I/O-bound tasks (load tests, health checks), high concurrency
            "timeout_seconds": 600,  # Increased for load test orchestrators
        }
    }

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


# Queue helper functions
def get_queue_names() -> list[str]:
    """Get all configured queue names."""
    return list(settings.WORKER_QUEUES.keys())


def get_default_queue() -> str:
    """Get the default queue name for load testing."""
    # Prefer load_test queue if it exists, otherwise use first available
    if "load_test" in settings.WORKER_QUEUES:
        return "load_test"
    queues = get_queue_names()
    return queues[0] if queues else "system"


def get_load_test_queue() -> str:
    """Get the queue name for load testing."""
    return "load_test" if "load_test" in settings.WORKER_QUEUES else get_default_queue()


def validate_queue_name(queue_name: str) -> bool:
    """Check if a queue name is valid."""
    return queue_name in settings.WORKER_QUEUES


def get_queue_pattern() -> str:
    """Get regex pattern for valid queue names."""
    queue_names = get_queue_names()
    if not queue_names:
        return "^(system)$"  # Fallback
    return f"^({'|'.join(queue_names)})$"
