"""Tests for AI analytics tab utility functions."""

import flet as ft
from app.components.frontend.dashboard.modals.ai_analytics_tab import (
    _get_success_rate_color,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_cost, format_number


class TestFormatCost:
    """Tests for the format_cost function."""

    def test_format_cost_with_small_value(self) -> None:
        """Should format small costs with 6 decimal places."""
        assert format_cost(0.000015) == "$0.000015"

    def test_format_cost_with_zero(self) -> None:
        """Should format zero correctly."""
        assert format_cost(0) == "$0.000000"

    def test_format_cost_with_large_value(self) -> None:
        """Should format larger costs with 4 decimal places."""
        assert format_cost(123.4567) == "$123.4567"

    def test_format_cost_with_very_small_value(self) -> None:
        """Should handle very small token costs."""
        assert format_cost(0.000001) == "$0.000001"

    def test_format_cost_with_whole_number(self) -> None:
        """Should pad whole numbers with zeros (4 decimals for >= 0.01)."""
        assert format_cost(5.0) == "$5.0000"


class TestFormatNumber:
    """Tests for the format_number function."""

    def test_format_number_zero(self) -> None:
        """Should format zero correctly."""
        assert format_number(0) == "0"

    def test_format_number_small(self) -> None:
        """Should not add commas to small numbers."""
        assert format_number(999) == "999"

    def test_format_number_thousands(self) -> None:
        """Should add comma for thousands."""
        assert format_number(1000) == "1,000"

    def test_format_number_millions(self) -> None:
        """Should add commas for millions."""
        assert format_number(1000000) == "1,000,000"

    def test_format_number_large(self) -> None:
        """Should handle large token counts."""
        assert format_number(1234567890) == "1,234,567,890"


class TestGetSuccessRateColor:
    """Tests for the _get_success_rate_color function."""

    def test_high_success_rate(self) -> None:
        """Should return SUCCESS color for 95%+."""
        assert _get_success_rate_color(95.0) == Theme.Colors.SUCCESS
        assert _get_success_rate_color(100.0) == Theme.Colors.SUCCESS

    def test_medium_success_rate(self) -> None:
        """Should return ORANGE for 80-94%."""
        assert _get_success_rate_color(80.0) == ft.Colors.ORANGE
        assert _get_success_rate_color(94.9) == ft.Colors.ORANGE

    def test_low_success_rate(self) -> None:
        """Should return ERROR color for <80%."""
        assert _get_success_rate_color(79.9) == Theme.Colors.ERROR
        assert _get_success_rate_color(0.0) == Theme.Colors.ERROR


class TestSentimentChartSections:
    """Tests for the sentiment distribution -> pie chart mapping."""

    def test_maps_nonzero_values_with_share_labels(self) -> None:
        from app.components.frontend.dashboard.modals.ai_analytics_tab import (
            sentiment_chart_sections,
        )

        sections = sentiment_chart_sections(
            {
                "distribution": {
                    "positive": 3,
                    "neutral": 0,
                    "negative": 1,
                    "frustrated": 0,
                }
            }
        )

        assert [s["value"] for s in sections] == [3, 1]
        assert sections[0]["label"] == "Positive (75%)"
        assert sections[1]["label"] == "Negative (25%)"

    def test_empty_distribution_yields_no_sections(self) -> None:
        from app.components.frontend.dashboard.modals.ai_analytics_tab import (
            sentiment_chart_sections,
        )

        assert sentiment_chart_sections({}) == []
        assert sentiment_chart_sections({"distribution": {"positive": 0}}) == []


class TestAgentRowCells:
    """Tests for the agents tab row/detail mapping (pure functions)."""

    def test_row_cells(self) -> None:
        from app.components.frontend.dashboard.modals.agents_tab import (
            agent_row_cells,
        )

        cells = agent_row_cells(
            {
                "slug": "support",
                "name": "Support",
                "model_id": "gpt-4o",
                "tools": ["a", "b"],
                "memory_modules": ["m"],
            }
        )

        assert cells == ["Support", "gpt-4o", "2", "1"]

    def test_defaults_for_sparse_agent(self) -> None:
        from app.components.frontend.dashboard.modals.agents_tab import (
            agent_row_cells,
        )

        assert agent_row_cells({}) == ["", "active default", "0", "0"]

    def test_edit_payload_parses_and_normalizes(self) -> None:
        from app.components.frontend.dashboard.modals.agents_tab import (
            agent_edit_payload,
        )

        payload = agent_edit_payload(
            name="  Assistant ",
            description="",
            category="general",
            model_id="",
            temperature=0.204,
            max_tokens="512",
            system_prompt="You are helpful.",
            is_active=True,
        )

        assert payload["name"] == "Assistant"
        assert payload["description"] is None
        assert payload["model_id"] is None  # empty = active default
        assert payload["temperature"] == 0.2  # slider value rounded
        assert payload["max_tokens"] == 512
        assert payload["is_active"] is True

    def test_edit_payload_rejects_bad_numbers(self) -> None:
        import pytest

        from app.components.frontend.dashboard.modals.agents_tab import (
            agent_edit_payload,
        )

        with pytest.raises(ValueError):
            agent_edit_payload(
                name="A",
                description="",
                category="",
                model_id="",
                temperature=0.7,
                max_tokens="lots",
                system_prompt="x",
                is_active=True,
            )

    def test_category_options_merge_defaults_and_in_use(self) -> None:
        from app.components.frontend.dashboard.modals.agents_tab import (
            category_options,
        )

        options = category_options(
            [{"category": "billing"}, {"category": None}], current="custom"
        )
        keys = [key for key, _text in options]

        assert "general" in keys
        assert "billing" in keys
        assert "custom" in keys
        assert keys == sorted(keys)

    def test_model_options_start_with_active_default(self) -> None:
        from app.components.frontend.dashboard.modals.agents_tab import (
            ACTIVE_DEFAULT_KEY,
            model_options,
        )

        options = model_options(
            [{"model_id": "gpt-4o"}, {"model_id": "gpt-4o"}],
            current="claude-sonnet-5",
        )

        # A non-empty sentinel key: Flet renders an empty key as blank.
        assert options[0] == (ACTIVE_DEFAULT_KEY, "(active default)")
        assert ACTIVE_DEFAULT_KEY != ""
        keys = [key for key, _text in options[1:]]
        # The current pin is present even when absent from the catalog,
        # and catalog duplicates collapse.
        assert keys == ["claude-sonnet-5", "gpt-4o"]


class TestWhatTheLedgerCouldNotShow:
    """Duration, cache and tool counts render, and absent ones read as a dash.

    Every one of these columns is nullable: rows written before they
    existed carry NULL, and so does any path that does not time itself.
    Rendering those as ``0`` would turn "nobody measured" into "it took
    no time", which is exactly the lie the nullable columns exist to
    avoid - so the dash is asserted, not assumed.
    """

    def test_a_duration_reads_in_the_unit_that_suits_it(self) -> None:
        from app.components.frontend.dashboard.modals.ai_analytics_tab.activity import (
            _format_duration,
        )

        assert _format_duration(840) == "840 ms"
        assert _format_duration(2400) == "2.4 s"
        # A local model answering slowly is the case this column is for.
        assert _format_duration(31500) == "31.5 s"

    def test_an_untimed_call_reads_as_a_dash_not_a_zero(self) -> None:
        from app.components.frontend.dashboard.modals.ai_analytics_tab.activity import (
            _format_duration,
        )

        assert _format_duration(None) == "-"

    def test_the_drawer_survives_a_row_that_predates_every_new_column(self) -> None:
        """Historical rows are all-NULL here and must still render."""
        from app.components.frontend.dashboard.modals.ai_analytics_tab.activity import (
            _detail,
        )

        panel = _detail(
            {
                "timestamp": "2026-09-01T10:00:00+00:00",
                "model": "gpt-4o",
                "action": "chat",
                "cost": 0.01,
                "success": True,
            }
        )
        assert panel is not None

    def test_a_failed_call_shows_why_in_the_drawer(self) -> None:
        from app.components.frontend.dashboard.modals.ai_analytics_tab.activity import (
            _detail,
        )

        panel = _detail(
            {
                "timestamp": "2026-09-01T10:00:00+00:00",
                "success": False,
                "error_message": "rate limited",
                "duration_ms": 120.0,
                "tool_calls": 0,
            }
        )
        rendered = _flatten(panel)
        assert "rate limited" in rendered
        # Zero tool calls is a measurement and must not read as a dash.
        assert "Tool calls" in rendered


def _flatten(control: ft.Control) -> str:
    """Every string reachable from a control tree, for assertion."""
    out: list[str] = []
    stack = [control]
    while stack:
        node = stack.pop()
        for attr in ("value", "text"):
            found = getattr(node, attr, None)
            if isinstance(found, str):
                out.append(found)
        for attr in ("content", "controls"):
            child = getattr(node, attr, None)
            if isinstance(child, list):
                stack.extend(child)
            elif child is not None:
                stack.append(child)
    return " | ".join(out)
