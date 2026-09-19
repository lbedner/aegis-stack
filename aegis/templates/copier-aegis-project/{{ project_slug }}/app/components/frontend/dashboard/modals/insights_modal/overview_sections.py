"""The overview tab's two big sections, and the sums behind them.

Pure builders: they take the bulk payload and hand back a control.
The tab wires them into its column.
"""

from __future__ import annotations  # noqa: I001

from typing import Any

from datetime import datetime

import flet as ft


from app.components.frontend.controls import (
    BodyText,
    DisplayText,
    ErrorText,
    H3Text,
    LabelText,
    SecondaryText,
    SuccessText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import OverviewHero


def _format_hero_number(n: float) -> str:
    """One decimal when fractional, no trailing '.0' on whole numbers."""
    if n is None:
        return "—"
    if float(n).is_integer():
        return str(int(n))
    return f"{n:.1f}"


def _build_overview_hero(hero: OverviewHero) -> ft.Container:
    """Editorial 'king metric' card: avg daily unique cloners.

    Mirrors the aegis-pulse Summary hero block — big number on the left,
    prior-period delta on the right, footer with totals. Renders only the
    delta block when ``change_pct`` is present (no prior data → no arrow).
    Uses Aegis text controls so the typography stays consistent with the
    rest of the dashboard.
    """
    # Subtitle: "people / day, last N days" or "all time" for huge ranges.
    if hero.range_days >= 9000:
        subtitle = "people / day, all time"
    else:
        subtitle = f"people / day, last {hero.range_days} days"

    # Hero number is intentionally larger than DisplayText (32) — it has
    # to dominate the card visually. Hand-set size; weight comes from the
    # control's defaults so we keep the family/selectable behavior.
    big_number = DisplayText(
        _format_hero_number(hero.avg_daily_unique_cloners),
        size=64,
        weight=Theme.Typography.WEIGHT_SEMIBOLD,
    )

    # Footer mixes emphasized numbers with muted descriptors. BodyText
    # for the numbers (default weight regular) bumped to medium for
    # readability; SecondaryText carries the muted units.
    footer_pieces: list[ft.Control] = [
        BodyText(
            f"{hero.total_unique_cloners:,}",
            size=Theme.Typography.BODY_SMALL,
            weight=Theme.Typography.WEIGHT_MEDIUM,
        ),
        SecondaryText(" total uniques", size=Theme.Typography.BODY_SMALL),
        SecondaryText(" · ", size=Theme.Typography.BODY_SMALL),
        BodyText(
            f"{hero.total_clones:,}",
            size=Theme.Typography.BODY_SMALL,
            weight=Theme.Typography.WEIGHT_MEDIUM,
        ),
        SecondaryText(" clones", size=Theme.Typography.BODY_SMALL),
        SecondaryText(" · ", size=Theme.Typography.BODY_SMALL),
        BodyText(
            f"{hero.avg_daily_clones:.1f}",
            size=Theme.Typography.BODY_SMALL,
            weight=Theme.Typography.WEIGHT_MEDIUM,
        ),
        SecondaryText(" clones / day avg", size=Theme.Typography.BODY_SMALL),
    ]

    left_block = ft.Column(
        [
            LabelText(
                "AVG DAILY UNIQUE CLONERS",
                color=Theme.Colors.PRIMARY,
            ),
            ft.Row(
                [
                    big_number,
                    SecondaryText(subtitle),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.END,
                wrap=True,
            ),
            ft.Row(footer_pieces, spacing=0, wrap=True),
        ],
        spacing=8,
        expand=True,
    )

    row_children: list[ft.Control] = [left_block]

    # Right-side prior-period delta — only shown when we have a comparison.
    if hero.change_pct is not None:
        is_down = hero.change_pct < 0
        # SuccessText / ErrorText carry the right semantic color; size
        # bumped to H2 so the delta reads at a glance from across the card.
        delta_arrow = "▼" if is_down else "▲"
        delta_text = f"{delta_arrow} {abs(hero.change_pct)}%"
        delta_control: ft.Control = (
            ErrorText(
                delta_text,
                size=Theme.Typography.H2,
                weight=Theme.Typography.WEIGHT_SEMIBOLD,
            )
            if is_down
            else SuccessText(
                delta_text,
                size=Theme.Typography.H2,
                weight=Theme.Typography.WEIGHT_SEMIBOLD,
            )
        )
        right_block = ft.Column(
            [
                LabelText("VS PRIOR PERIOD"),
                delta_control,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.END,
            spacing=4,
        )
        row_children.append(right_block)

    # Match MetricCard: same bgcolor, border weight/color, and corner
    # radius so the hero reads as part of the same visual family rather
    # than a foreign panel above it.
    return ft.Container(
        content=ft.Row(
            row_children,
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=Theme.Spacing.LG,
        ),
        padding=Theme.Spacing.LG,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.border.all(0.5, ft.Colors.OUTLINE),
        border_radius=Theme.Components.CARD_RADIUS,
        margin=ft.margin.only(bottom=Theme.Spacing.MD),
    )


def _build_overview_goals(bulk: BulkInsightsResponse | None) -> ft.Column:
    """Stubbed Goals section.

    Goals are auth-gated in the templates (the real `Goal` model carries a
    `user_id` FK), so projects generated without auth don't have
    persistent goals yet. Until the auth/no-auth/org endpoint design is
    settled, this builds four placeholder goals from the live current
    values in ``bulk`` and synthetic targets — the UI shape is real, the
    targets aren't. Replace the body with real `Goal` rows when the
    Goal API endpoint is wired through.
    """
    header = H3Text("Goals")
    divider = ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT)

    if bulk is None:
        return ft.Column(
            [header, divider, SecondaryText("No data yet.")],
            spacing=6,
        )

    # Pull real current values from bulk so the cards aren't lying about
    # where the project actually stands — only the targets are synthetic.
    star_count = len(bulk.events.get("new_star", []))
    pypi_total_row = bulk.latest.get("downloads_total")
    pypi_total = int(pypi_total_row.value) if pypi_total_row else 0
    clones_total = sum(int(r.value) for r in bulk.daily.get("clones", []))
    unique_cloners_total = sum(
        int(r.value) for r in bulk.daily.get("unique_cloners", [])
    )

    # Two cards above current (in-progress feel), two below (achieved
    # / over-target feel) so the visual mix shows both states.
    fake_goals: list[tuple[str, int, int]] = [
        ("Pypi — Downloads", pypi_total, max(35_000, pypi_total * 2)),
        ("Github — Stars", star_count, max(150, int(star_count * 1.5))),
        ("Github — Clones", clones_total, max(2_500, int(clones_total * 0.85))),
        (
            "Github — Unique Cloners",
            unique_cloners_total,
            max(500, int(unique_cloners_total * 0.75)),
        ),
    ]

    rows: list[ft.Control] = []
    for label, current, target in fake_goals:
        pct_raw = (current / target * 100) if target > 0 else 0
        achieved = pct_raw >= 100
        pct = int(pct_raw)

        top_row = ft.Row(
            [
                BodyText(label, weight=Theme.Typography.WEIGHT_MEDIUM),
                ft.Row(
                    [
                        BodyText(
                            f"{current:,}",
                            size=Theme.Typography.BODY_SMALL,
                            weight=Theme.Typography.WEIGHT_MEDIUM,
                        ),
                        SecondaryText(
                            f" / {target:,}", size=Theme.Typography.BODY_SMALL
                        ),
                    ],
                    spacing=0,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        bar = ft.ProgressBar(
            # `value` clamped to 1.0 — flet renders >1 as overflow.
            value=min(pct_raw / 100, 1.0),
            color=Theme.Colors.SUCCESS if achieved else Theme.Colors.PRIMARY,
            bgcolor=Theme.Colors.SURFACE_2,
            height=6,
            border_radius=3,
        )

        bottom = SecondaryText(f"{pct}%", size=Theme.Typography.BODY_SMALL)

        rows.append(ft.Column([top_row, bar, bottom], spacing=4))

    # Match MetricCard styling so this reads as the same family of
    # surfaces as the metric row above.
    card = ft.Container(
        content=ft.Column(rows, spacing=Theme.Spacing.SM),
        padding=Theme.Spacing.MD,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.border.all(0.5, ft.Colors.OUTLINE),
        border_radius=Theme.Components.CARD_RADIUS,
    )

    return ft.Column([header, divider, card], spacing=6)


def sum_in_range(bulk: Any, key: str, start: datetime, end: datetime) -> int:
    """Total one bulk metric over a half-open window.

    ``start`` is included and ``end` is not, so two adjacent windows can
    be compared without double-counting the day they meet - which is the
    whole point when the answer is a period-over-period arrow.

    A missing metric totals zero rather than raising: a project with no
    PyPI history still has an overview.
    """
    rows = bulk.daily.get(key, []) if bulk else []
    return sum(int(r.value) for r in rows if start <= r.date < end)
