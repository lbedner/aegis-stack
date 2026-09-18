"""The two read-only panels: what the index holds, and how it is wired.

Both are a handful of stat rows off the status payload, and neither is
big enough to be worth its own module alone.
"""

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import MetricCard


def _format_timestamp(timestamp: str | None) -> str:
    """Format ISO timestamp for display."""
    if not timestamp:
        return "No activity"
    # Show date and time portion
    if "T" in timestamp:
        date_part, time_part = timestamp.split("T")
        time_part = time_part.split(".")[0]  # Remove microseconds
        return f"{date_part} {time_part}"
    return timestamp


class RAGStatsSection(ft.Container):
    """Stats section showing RAG chunking and search parameters as metric cards."""

    def __init__(self, data: dict[str, Any]) -> None:
        """
        Initialize stats section.

        Args:
            data: RAG health data from API
        """
        super().__init__()

        chunk_size = data.get("chunk_size", 0)
        chunk_overlap = data.get("chunk_overlap", 0)
        default_top_k = data.get("default_top_k", 0)

        self.content = ft.Row(
            [
                MetricCard("Chunk Size", str(chunk_size), Theme.Colors.PRIMARY),
                MetricCard("Chunk Overlap", str(chunk_overlap), Theme.Colors.INFO),
                MetricCard("Default Top K", str(default_top_k), Theme.Colors.SUCCESS),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.MD


class RAGConfigSection(ft.Container):
    """Configuration section showing RAG service settings."""

    def __init__(self, data: dict[str, Any]) -> None:
        """
        Initialize configuration section.

        Args:
            data: RAG health data from API
        """
        super().__init__()

        embedding_provider = data.get("embedding_provider", "Unknown")
        embedding_model = data.get("embedding_model", "Unknown")
        vectorstore_uri = data.get("persist_directory", "Unknown")
        last_activity = data.get("last_activity")

        def config_row(label: str, value: str) -> ft.Row:
            """Create a configuration row with label and value."""
            return ft.Row(
                [
                    SecondaryText(
                        f"{label}:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=150,
                    ),
                    BodyText(value),
                ],
                spacing=Theme.Spacing.MD,
            )

        rows = [
            config_row("Provider", embedding_provider),
            config_row("Embedding Model", embedding_model),
            config_row("Vectorstore URI", str(vectorstore_uri)),
        ]

        if last_activity:
            rows.append(config_row("Last Activity", _format_timestamp(last_activity)))

        self.content = ft.Column(rows, spacing=Theme.Spacing.XS)
        self.padding = Theme.Spacing.MD
