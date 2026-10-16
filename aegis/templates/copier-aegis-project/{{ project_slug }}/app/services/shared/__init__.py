"""
Shared domain models and utilities.

Common types and models used across multiple domains.
"""

from .models import (
    BaseResponse,
    ErrorResponse,
)

# Shared code, not a service (``ownership``).
PART_OF = "shared"


__all__ = [
    "BaseResponse",
    "ErrorResponse",
]
