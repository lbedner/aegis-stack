"""What every service reaches for: who is calling and whether they may
(``deps``: the caller's user, admin and owner), the query clauses that
scope rows to an owner or a time window (``queries``), and the API's
response envelopes (``models``).
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
