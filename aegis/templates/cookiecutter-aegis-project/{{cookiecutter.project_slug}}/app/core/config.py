# app/core/config.py
"""
Application configuration management using Pydantic's BaseSettings.

This module centralizes application settings, allowing them to be loaded
from environment variables for easy configuration in different environments.
"""

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
