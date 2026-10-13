"""
Shared domain models and utilities.

Common types and models used across multiple domains.
"""

from .models import (
    BaseResponse,
    ErrorResponse,
)

# The stack's own code, not a service (``ownership``).
PART_OF = "stack"


__all__ = [
    "BaseResponse",
    "ErrorResponse",
]
