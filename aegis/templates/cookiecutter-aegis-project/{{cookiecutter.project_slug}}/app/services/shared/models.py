"""
Shared domain models.

Common Pydantic models used across multiple domains and services.
"""

from typing import Any

from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """Base API response model."""

    success: bool = Field(..., description="Whether operation was successful")
    message: str = Field(..., description="Response message")
    data: dict[str, Any] | list[Any] | None = Field(None, description="Response data")


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str = Field(..., description="Error message")
    status: str = Field(default="error", description="Status indicator")
    details: dict[str, Any] | None = Field(None, description="Additional error details")
    timestamp: str | None = Field(None, description="ISO timestamp when error occurred")
