"""The settings tab: sources and collection."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft


from app.components.frontend.controls import (
    BodyText,
    H3Text,
    LabelText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import (
    MetricCard,
)


# Event type → chip border/highlight color

# Shared date range options for all tabs

# Milestone category config (for Overview trophy cards)

# Event type to status mapping (for activity feed dot colors)


class SettingsTab(ft.Container):
    """Settings: data sources, collection status, metric counts."""

    def __init__(self, metadata: dict[str, Any], db: dict[str, Any]) -> None:
        super().__init__()

        total_metrics = metadata.get("total_metrics", 0)
        enabled_sources = metadata.get("enabled_sources", 0)
        stale_sources = metadata.get("stale_sources", [])
        sources_meta = metadata.get("sources", {})

        content: list[ft.Control] = [
            ft.Row(
                [
                    MetricCard(
                        "Total Metrics", f"{total_metrics:,}", Theme.Colors.PRIMARY
                    ),
                    MetricCard(
                        "Active Sources", str(enabled_sources), Theme.Colors.SUCCESS
                    ),
                ],
                spacing=Theme.Spacing.MD,
            ),
            ft.Container(height=8),
            H3Text("Data Sources"),
            ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
        ]

        for src in db["sources"]:
            is_stale = src["key"] in stale_sources
            if src["enabled"]:
                status_text = "Stale" if is_stale else "Active"
                status_color = "#F59E0B" if is_stale else "#22C55E"
            else:
                status_text = "Disabled"
                status_color = ft.Colors.ON_SURFACE_VARIANT

            # Last collected time from health metadata
            src_meta = sources_meta.get(src["key"], {})
            last_collected = src_meta.get("last_collected", "")
            if last_collected:
                last_collected = last_collected[:16].replace("T", " ")

            content.append(
                ft.Row(
                    [
                        ft.Container(
                            content=BodyText(
                                src["display_name"], size=Theme.Typography.BODY_SMALL
                            ),
                            width=140,
                        ),
                        ft.Container(
                            content=LabelText(
                                status_text, color=Theme.Colors.BADGE_TEXT
                            ),
                            bgcolor=status_color,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=4,
                        ),
                        SecondaryText(
                            f"Last: {last_collected}" if last_collected else "",
                            size=Theme.Typography.BODY_SMALL,
                        ),
                    ],
                    spacing=8,
                )
            )

        self.content = ft.Column(
            content,
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = Theme.Spacing.MD
        self.expand = True
