"""What Illiana knows of her own spend, and over what window."""

import pytest

from app.services.ai.domains.chat.usage_context import UsageContext


@pytest.mark.parametrize("compact", [False, True])
def test_spend_carries_its_window(compact: bool) -> None:
    """Asked for the past 7 days she gave the all-time total as if it were
    (2026-10-16): each figure says the window it covers."""
    told = UsageContext(
        total_requests=543, total_cost=21.31, week_requests=12, week_cost=0.83
    ).format_for_prompt(compact=compact)

    assert "all time" in told
    assert "last 7 days" in told and "$0.83" in told
