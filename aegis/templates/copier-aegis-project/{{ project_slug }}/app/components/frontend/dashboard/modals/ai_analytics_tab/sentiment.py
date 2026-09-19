"""How conversations felt, as a chart and a legend."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    H3Text,
    Tag,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import PieChartCard
from .shaping import _format_relative_time

SENTIMENT_COLORS: dict[str, str] = {
    "positive": Theme.Colors.SUCCESS,
    "neutral": ft.Colors.BLUE_GREY_300,
    "negative": Theme.Colors.WARNING,
    "frustrated": Theme.Colors.ERROR,
}


def sentiment_chart_sections(sentiment: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a sentiment distribution to pie chart sections (non-zero only)."""
    distribution = sentiment.get("distribution", {}) or {}
    total = sum(distribution.values()) or 1
    return [
        {
            "value": count,
            "color": SENTIMENT_COLORS.get(value, ft.Colors.BLUE_GREY_300),
            "label": f"{value.title()} ({count / total * 100:.0f}%)",
        }
        for value, count in distribution.items()
        if count
    ]


class SentimentSection(ft.Container):
    """Conversation sentiment: distribution chart + recent negatives."""

    def __init__(self, sentiment: dict[str, Any]) -> None:
        super().__init__()

        chart = PieChartCard(
            title="Conversation Sentiment",
            sections=sentiment_chart_sections(sentiment),
        )

        columns = [
            DataTableColumn("Sentiment", width=110, style=None),
            DataTableColumn("Summary", width=420, style="secondary"),
            DataTableColumn("When", width=120, style="secondary"),
        ]
        rows: list[list[Any]] = []
        for row in sentiment.get("recent_negatives", []):
            value = row.get("overall_sentiment", "")
            rows.append(
                [
                    Tag(
                        text=value.title(),
                        color=SENTIMENT_COLORS.get(value, Theme.Colors.WARNING),
                    ),
                    row.get("summary") or row.get("conversation_id", ""),
                    _format_relative_time(row.get("created_at", "")),
                ]
            )

        controls: list[ft.Control] = [chart]
        if rows:
            controls.extend(
                [
                    ft.Container(height=Theme.Spacing.SM),
                    H3Text("Recent Negative Conversations"),
                    ft.Container(height=Theme.Spacing.SM),
                    DataTable(
                        columns=columns,
                        rows=rows,
                        empty_message="No negative conversations",
                    ),
                ]
            )

        self.content = ft.Column(controls, spacing=0)
        self.padding = Theme.Spacing.MD
