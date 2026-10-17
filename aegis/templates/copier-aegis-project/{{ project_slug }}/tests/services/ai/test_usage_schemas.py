"""What the AI service says it spent: figures that are only what they say."""

from pydantic import ValidationError
import pytest

from app.services.ai.schemas import UsageTotals


def test_a_usage_figure_is_only_what_it_says() -> None:
    """Agents answer from these figures: a field that is not one, or a
    figure changed after it was read, is refused."""
    totals = UsageTotals(
        total_tokens=3,
        input_tokens=2,
        output_tokens=1,
        total_cost=0.5,
        total_requests=1,
        success_rate=100.0,
    )

    with pytest.raises(ValidationError):
        UsageTotals(**totals.model_dump(), stray=1)
    with pytest.raises(ValidationError):
        totals.total_cost = 0.0  # type: ignore[misc]
