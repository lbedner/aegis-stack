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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
