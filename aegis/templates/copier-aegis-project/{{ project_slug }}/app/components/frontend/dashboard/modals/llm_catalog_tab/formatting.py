"""Reading a catalog row: its date, its price, its window."""

import re
from typing import Any

# Pattern to extract YYYYMMDD dates from model IDs
_DATE_PATTERN = re.compile(r"(\d{8})(?:\D|$)")


def _extract_model_date(model: dict[str, Any]) -> int:
    """Extract date for sorting (newer = higher).

    Uses released_on field from API if available, otherwise
    falls back to extracting YYYYMMDD from model_id.
    """
    # First try released_on field (e.g., "2024-08-06")
    released_on = model.get("released_on")
    if released_on:
        try:
            # Convert "2024-08-06" to 20240806
            return int(released_on.replace("-", ""))
        except (ValueError, AttributeError):
            pass

    # Fallback: extract YYYYMMDD from model_id
    model_id = model.get("model_id", "")
    match = _DATE_PATTERN.search(model_id)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return 0


def _is_alias_model(model_id: str) -> bool:
    """Check if model is an alias (ends with -latest or :latest)."""
    return model_id.endswith("-latest") or model_id.endswith(":latest")


def _format_price(price: float | None) -> str:
    """Format price per million tokens."""
    if price is None:
        return "-"
    return f"${price:.2f}"


def _format_context(ctx: int) -> str:
    """Format context window size."""
    if ctx >= 1_000_000:
        return f"{ctx // 1_000_000}M"
    elif ctx >= 1_000:
        return f"{ctx // 1_000}K"
    return str(ctx)
