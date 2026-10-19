"""Error tracking settings shared by all stacks (Redis remains optional)."""

from pydantic import Field
from pydantic_settings import BaseSettings


class ErrorTrackingSettings(BaseSettings):
    ERROR_TRACKING_ENABLED: bool = True
    ERROR_TRACKING_RETENTION_SECONDS: int = Field(default=7 * 86400, ge=1)
    ERROR_TRACKING_MAX_OCCURRENCES: int = Field(default=10_000, ge=1, le=10_000)
    # What the retained errors may take in Redis, so a storm of large
    # tracebacks stays well inside the Redis memory cap.
    ERROR_TRACKING_MAX_BYTES: int = Field(default=16 * 1024 * 1024, ge=65536)
    ERROR_TRACKING_MAX_SOURCES: int = Field(default=64, ge=1, le=256)
