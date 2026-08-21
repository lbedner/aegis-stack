"""
Insights Service Detail Modal

Tabbed modal showing adoption metrics across all data sources.
All tabs pull real data from the database via _load_db().
"""

from __future__ import annotations  # noqa: I001

from typing import Any

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
from app.components.frontend.controls.data_table import (
    DataTable,
    DataTableColumn,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.constants import COUNTRY_NAMES
from app.services.insights.models import EVENT_TYPE_LABELS
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.view_schemas import OverviewHero
from app.services.insights.view_service import InsightViewService
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import (
    ChartColors,
    ChartPoint,
    DateRangeChips,
    LineChartCard,
    LineSeries,
    MetricCard,
    PieChartCard,
    chart_tooltip_kwargs,
)

# Event type → chip border/highlight color
EVENT_TYPE_COLORS: dict[str, str] = {
    "release": "#22C55E",
    "fork": "#A855F7",
    "star": "#F59E0B",
    "reddit_post": "#FF5722",
    "localization": "#3B82F6",
    "feature": "#06B6D4",
    "milestone_github": "#EC4899",
    "milestone_pypi": "#EC4899",
    "anomaly_github": "#EF4444",
    "external": "#9CA3AF",
}

# Shared date range options for all tabs
RANGE_OPTIONS = [
    ("7d", 7),
    ("14d", 14),
    ("1m", 30),
    ("3m", 90),
    ("6m", 180),
    ("1y", 365),
    ("All", 9999),
]

# Event types relevant to each tab
GITHUB_EVENT_TYPES = {
    "release",
    "fork",
    "star",
    "feature",
    "milestone_github",
    "anomaly_github",
    "localization",
    "external",
}
PYPI_EVENT_TYPES = {
    "release",
    "reddit_post",
    "star",
    "feature",
    "milestone_pypi",
    "localization",
    "external",
}
DOCS_EVENT_TYPES = {
    "release",
    "reddit_post",
    "star",
    "feature",
    "localization",
    "external",
}

# Milestone category config (for Overview trophy cards)
CATEGORY_CONFIG: dict[str, dict[str, str]] = {
    "daily_clones": {"label": "GitHub 1-Day Clones", "color": "#2563eb"},
    "daily_unique": {"label": "GitHub 1-Day Unique", "color": "#A855F7"},
    "daily_views": {"label": "GitHub 1-Day Views", "color": "#22C55E"},
    "daily_visitors": {"label": "GitHub 1-Day Visitors", "color": "#F59E0B"},
    "14d_clones": {"label": "GitHub 14-Day Clones", "color": "#06B6D4"},
    "14d_unique": {"label": "GitHub 14-Day Unique", "color": "#EC4899"},
    "14d_visitors": {"label": "GitHub 14-Day Visitors", "color": "#F97316"},
    "pypi_daily": {"label": "PyPI Best Single Day", "color": "#EF4444"},
    "plausible_daily_visitors": {"label": "Docs 1-Day Visitors", "color": "#6366F1"},
    "plausible_daily_pageviews": {"label": "Docs 1-Day Pageviews", "color": "#22C55E"},
    "star_daily": {"label": "Stars Best Day", "color": "#FFD700"},
    "star_monthly": {"label": "Stars Best Month", "color": "#FFD700"},
}

# Event type to status mapping (for activity feed dot colors)
EVENT_STATUS_MAP: dict[str, str] = {
    "release": "success",
    "star": "warning",
    "reddit_post": "info",
    "milestone_github": "warning",
    "milestone_pypi": "warning",
    "feature": "info",
    "anomaly_github": "error",
    "external": "info",
}


def _pct(current: float, previous: float) -> float | None:
    """Compute period-over-period percentage change."""
    if previous > 0:
        return (current - previous) / previous * 100
    return None


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


def _make_line_chart(
    data_series: list,
    max_y: float,
    daily: list[dict],
    step: int,
    min_y: float = 0,
    height: int = 350,
) -> ft.LineChart:
    """Build a standard line chart with shared tooltip/grid/border config."""
    return ft.LineChart(
        data_series=data_series,
        left_axis=ft.ChartAxis(labels_size=50, labels_interval=step),
        bottom_axis=ft.ChartAxis(
            labels_size=50,
            labels=[
                ft.ChartAxisLabel(
                    value=i,
                    label=ft.Text(
                        d["date"][-5:], size=9, color=ft.Colors.ON_SURFACE_VARIANT
                    ),
                )
                for i, d in enumerate(daily)
                if i % max(1, len(daily) // 8) == 0 or i == len(daily) - 1
            ],
        ),
        horizontal_grid_lines=ft.ChartGridLines(
            interval=step,
            color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
            width=1,
        ),
        tooltip_bgcolor=Theme.Colors.SURFACE_1,
        tooltip_rounded_radius=8,
        tooltip_padding=10,
        tooltip_max_content_width=200,
        tooltip_tooltip_border_side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        tooltip_fit_inside_vertically=True,
        tooltip_fit_inside_horizontally=True,
        tooltip_show_on_top_of_chart_box_area=True,
        point_line_start=0,
        point_line_end=float("inf"),
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        interactive=True,
        min_y=min_y,
        max_y=max_y,
        min_x=0,
        max_x=len(daily) - 1,
        height=height,
        expand=True,
    )


def _make_legend(items: list[tuple[str, str]]) -> ft.Row:
    """Build chart legend. items = [(color, label), ...]"""
    return ft.Row(
        [
            ft.Row(
                [
                    ft.Container(width=10, height=10, bgcolor=color, border_radius=5),
                    SecondaryText(label, size=Theme.Typography.BODY_SMALL),
                ],
                spacing=4,
            )
            for color, label in items
        ],
        spacing=16,
        alignment=ft.MainAxisAlignment.CENTER,
    )


# ---------------------------------------------------------------------------
# Base class for interactive insight tabs
# ---------------------------------------------------------------------------


class InsightsTab(ft.Container):
    """Base class for insight tabs with date range chips, events toggle, and rebuild pattern."""  # noqa: E501

    _default_days: int = 7  # Override in subclass

    def __init__(self, bulk: BulkInsightsResponse | None = None) -> None:
        super().__init__()

        self._bulk = bulk
        self._days = self._default_days
        self._data = self._load_data(self._days)
        self._highlighted_dates: set[str] = set()
        # Selection / filter state mirroring the aegis-pulse event-chip
        # macro. `_selected_event_id` is None when no chip is selected.
        # `_selected_event_types` is the explicit set of event types
        # shown in the chip strip and as chart annotations - empty
        # means "no events selected", so chips are hidden and the
        # chart shows no event markers. The "All" toggle row in the
        # filter dropdown selects every type present in the data.
        self._selected_event_id: str | None = None
        self._selected_event_types: set[str] = set()
        self._content_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

        # Date-range pills — owned by `DateRangeChips`, which keeps its
        # own selection state and styling so this base class only has to
        # react to the change.
        self._range_chips = DateRangeChips(
            options=RANGE_OPTIONS,
            selected_days=self._days,
            on_change=self._on_range_change,
        )

        self._build_content()

        self.content = self._content_column
        self.padding = ft.padding.only(
            left=Theme.Spacing.MD,
            top=Theme.Spacing.MD,
            bottom=Theme.Spacing.MD,
            right=Theme.Spacing.LG + 8,
        )
        self.expand = True

    def _on_event_click(self, dates: set[str]) -> None:
        if self._highlighted_dates == dates:
            self._highlighted_dates = set()
        else:
            self._highlighted_dates = dates
        self._build_content()
        self._content_column.update()

    def _on_range_change(self, days: int) -> None:
        self._days = days
        self._data = self._load_data(days)
        # `DateRangeChips` already updated its own active pill before
        # invoking this callback, so we only have to react: reload data
        # and rebuild the tab content for the new window.
        self._build_content()
        self._content_column.update()

    def _build_content(self) -> None:
        """Override in subclass to build tab-specific content."""
        raise NotImplementedError

    def _load_data(self, days: int = 14) -> dict[str, Any]:
        """Override in subclass to load tab-specific data."""
        raise NotImplementedError

    def _make_filter_bar(
        self, last_updated: str = "", extra_controls: list[ft.Control] | None = None
    ) -> ft.Row:
        """Build the standard filter bar with range chips and last-updated.

        The Events filter dropdown lives on the chip strip itself
        (see `_render_event_chips`), so it isn't included here.
        """
        right_items: list[ft.Control] = []
        if last_updated:
            right_items.append(
                SecondaryText(
                    f"Last updated: {last_updated}", size=Theme.Typography.BODY_SMALL
                )
            )
        if extra_controls:
            right_items.extend(extra_controls)
        return ft.Row(
            [self._range_chips, ft.Row(right_items, spacing=Theme.Spacing.MD)],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    def _render_event_chips(
        self,
        all_events: list[tuple[str, str, str]],
        valid_dates: set[str] | None = None,
        exclude_types: set[str] | None = None,
    ) -> ft.Control | None:
        """Render the event chip strip + filter dropdown.

        Mirrors the aegis-pulse `alpine_event_chips` macro — uniform
        muted-card chip styling, teal accent for the selected chip,
        amber for chips on the same date as the selection, and a
        right-aligned "Events (N)" dropdown that filters the strip by
        event type. Returns a Column with the filter row above the chip
        row. The filter trigger is always shown; the chip row only
        renders when there are events to display under the current
        filter.
        """
        if exclude_types:
            all_events = [
                (d, lbl, t) for d, lbl, t in all_events if t not in exclude_types
            ]
        if valid_dates is not None:
            all_events = [(d, lbl, t) for d, lbl, t in all_events if d in valid_dates]

        # Apply the dropdown's type filter. Empty set means "no events
        # selected" — chip strip stays empty, button reads neutral.
        # Non-empty restricts to the selected types.
        visible_events = [
            (d, lbl, t) for d, lbl, t in all_events if t in self._selected_event_types
        ]

        grouped = _group_events(visible_events, self._days)
        if not all_events:
            # Nothing to filter and nothing to show — hide the toolbar
            # entirely so empty tabs don't get a stray "Events" button.
            return None

        # Build the filter dropdown. Lists every event type present in
        # the un-filtered set, plus an "All" toggle-all row at the top.
        present_types = sorted({t for _d, _lbl, t in all_events})
        all_selected = bool(present_types) and set(present_types).issubset(
            self._selected_event_types
        )
        active_filter = bool(self._selected_event_types)
        filter_label = f"Events ({len(grouped)})" if active_filter else "Events"
        filter_button = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Text(
                    filter_label,
                    size=Theme.Typography.BODY_SMALL,
                    weight=ft.FontWeight.W_500,
                    color=ft.Colors.ON_SURFACE
                    if active_filter
                    else ft.Colors.ON_SURFACE_VARIANT,
                ),
                bgcolor=ft.Colors.with_opacity(0.10, ChartColors.TEAL)
                if active_filter
                else ft.Colors.SURFACE_CONTAINER_HIGHEST,
                border=ft.border.all(
                    0.5,
                    ChartColors.TEAL if active_filter else ft.Colors.OUTLINE,
                ),
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
            ),
            items=[
                ft.PopupMenuItem(
                    text=("✓ All" if all_selected else "All"),
                    on_click=lambda _e, types=present_types: (
                        self._on_event_types_toggle_all(types)
                    ),
                ),
                *[
                    ft.PopupMenuItem(
                        text=(
                            f"✓ {EVENT_TYPE_LABELS.get(t, t)}"
                            if t in self._selected_event_types
                            else EVENT_TYPE_LABELS.get(t, t)
                        ),
                        on_click=lambda _e, et=t: self._on_event_type_toggle(et),
                    )
                    for t in present_types
                ],
            ],
        )

        highlighted = self._highlighted_dates

        chip_controls: list[ft.Control] = []
        for date, label, etype, dates_set in grouped:
            chip_id = f"{date}::{label}::{etype}"
            is_selected = chip_id == self._selected_event_id
            is_related = not is_selected and bool(dates_set & highlighted)
            if is_selected:
                chip_bg = ft.Colors.with_opacity(0.10, ChartColors.TEAL)
                chip_border_color = ChartColors.TEAL
                chip_text_color = ft.Colors.ON_SURFACE
            elif is_related:
                chip_bg = ft.Colors.with_opacity(0.10, ChartColors.AMBER)
                chip_border_color = ChartColors.AMBER
                chip_text_color = ft.Colors.ON_SURFACE
            else:
                chip_bg = ft.Colors.SURFACE_CONTAINER_HIGHEST
                chip_border_color = ft.Colors.OUTLINE
                chip_text_color = ft.Colors.ON_SURFACE_VARIANT
            chip_controls.append(
                ft.Container(
                    content=ft.Text(
                        f"{label}  {date[-5:]}",
                        size=Theme.Typography.BODY_SMALL,
                        weight=ft.FontWeight.W_500,
                        color=chip_text_color,
                        selectable=False,
                    ),
                    bgcolor=chip_bg,
                    border=ft.border.all(0.5, chip_border_color),
                    border_radius=10,
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                    on_click=lambda _e, cid=chip_id, ds=dates_set: (
                        self._on_event_chip_click(cid, ds)
                    ),
                    ink=True,
                )
            )

        return ft.Column(
            [
                ft.Row(
                    [filter_button],
                    alignment=ft.MainAxisAlignment.END,
                ),
                ft.Row(chip_controls, spacing=6, wrap=True),
            ],
            spacing=6,
        )

    def _on_event_chip_click(self, chip_id: str, dates_set: set[str]) -> None:
        """Toggle chip selection. Clicking the same chip again clears
        the highlight; clicking a different chip moves the highlight to
        its date(s)."""
        if self._selected_event_id == chip_id:
            self._selected_event_id = None
            self._highlighted_dates = set()
        else:
            self._selected_event_id = chip_id
            self._highlighted_dates = set(dates_set)
        self._build_content()
        self._content_column.update()

    def _on_event_type_toggle(self, event_type: str) -> None:
        """Toggle membership of an event type in the filter dropdown."""
        if event_type in self._selected_event_types:
            self._selected_event_types.discard(event_type)
        else:
            self._selected_event_types.add(event_type)
        self._build_content()
        self._content_column.update()

    def _on_event_types_toggle_all(self, types: list[str]) -> None:
        """Dropdown's "All" row — toggle all event types on or off.

        If every type is already selected, clear the set (hides the
        chip strip and turns the button neutral). Otherwise select
        every available type, showing the full chip strip with the
        button in its teal/active state.
        """
        type_set = set(types)
        if type_set.issubset(self._selected_event_types) and self._selected_event_types:
            self._selected_event_types = set()
        else:
            self._selected_event_types = type_set
        self._build_content()
        self._content_column.update()


# ---------------------------------------------------------------------------
# Shared DB loader
# ---------------------------------------------------------------------------


def _build_db_from_bulk(bulk: BulkInsightsResponse) -> dict[str, Any]:
    """Transform bulk-loaded data into the db dict consumed by OverviewTab and SettingsTab."""  # noqa: E501
    from app.services.insights.query_service import InsightQueryService

    cutoff_14d, _ = InsightQueryService.compute_cutoffs(14)

    # -- github_traffic (filter to 14d from bulk) ----------------------------

    clones_rows = [r for r in bulk.daily.get("clones", []) if r.date >= cutoff_14d]
    unique_rows = [
        r for r in bulk.daily.get("unique_cloners", []) if r.date >= cutoff_14d
    ]
    views_rows = [r for r in bulk.daily.get("views", []) if r.date >= cutoff_14d]
    visitors_rows = [
        r for r in bulk.daily.get("unique_visitors", []) if r.date >= cutoff_14d
    ]

    unique_map = {str(r.date)[:10]: int(r.value) for r in unique_rows}
    views_map = {str(r.date)[:10]: int(r.value) for r in views_rows}
    visitors_map = {str(r.date)[:10]: int(r.value) for r in visitors_rows}

    traffic_daily: list[dict[str, Any]] = []
    for r in clones_rows:
        day = str(r.date)[:10]
        traffic_daily.append(
            {
                "date": day,
                "clones": int(r.value),
                "unique_cloners": unique_map.get(day, 0),
                "views": views_map.get(day, 0),
                "unique_visitors": visitors_map.get(day, 0),
            }
        )

    # -- referrers / paths (from latest snapshots) ---------------------------

    referrers_row = bulk.latest.get("referrers")
    referrers: list[dict[str, Any]] = []
    if referrers_row and referrers_row.metadata_:
        meta = referrers_row.metadata_
        if isinstance(meta, dict) and not meta.get("referrers"):
            for domain, counts in meta.items():
                if isinstance(counts, dict):
                    referrers.append(
                        {
                            "domain": domain,
                            "views": counts.get("views", 0),
                            "uniques": counts.get("uniques", 0),
                        }
                    )
        else:
            for ref in meta.get("referrers", []):
                referrers.append(
                    {
                        "domain": ref.get("referrer", ref.get("domain", "unknown")),
                        "views": ref.get("count", ref.get("views", 0)),
                        "uniques": ref.get("uniques", 0),
                    }
                )
        referrers.sort(key=lambda x: -x["views"])

    paths_row = bulk.latest.get("popular_paths")
    popular_paths: list[dict[str, Any]] = []
    if paths_row and paths_row.metadata_:
        for p in paths_row.metadata_.get("popular_paths", []):
            popular_paths.append(
                {
                    "path": p.get("path", "unknown"),
                    "views": p.get("count", p.get("views", 0)),
                    "uniques": p.get("uniques", 0),
                }
            )

    # -- github_stars (from bulk events) ------------------------------------

    star_events = bulk.events.get("new_star", [])
    stars_total = len(star_events)

    stars_recent: list[dict[str, Any]] = []
    star_countries: dict[str, int] = {}
    for ev in star_events:
        meta = ev.metadata_ or {}
        country = meta.get("location", "Unknown")
        if country and country != "Unknown":
            parts = [p.strip() for p in country.split(",")]
            country_key = parts[-1] if parts else "Unknown"
        else:
            country_key = "Unknown"
        star_countries[country_key] = star_countries.get(country_key, 0) + 1

        if len(stars_recent) < 10:
            stars_recent.append(
                {
                    "username": meta.get("username", "unknown"),
                    "location": meta.get("location", ""),
                    "company": meta.get("company", ""),
                    "date": str(ev.date)[:10],
                }
            )

    star_countries = dict(sorted(star_countries.items(), key=lambda x: -x[1]))

    # -- sources / pypi total ------------------------------------------------

    sources = [
        {"key": s.key, "display_name": s.display_name, "enabled": s.enabled}
        for s in bulk.sources
    ]

    pypi_total_row = bulk.latest.get("downloads_total")
    pypi_total = int(pypi_total_row.value) if pypi_total_row else 0

    return {
        "traffic_daily": traffic_daily,
        "referrers": referrers,
        "popular_paths": popular_paths,
        "stars_total": stars_total,
        "stars_recent": stars_recent,
        "star_countries": star_countries,
        "sources": sources,
        "pypi_total": pypi_total,
    }


# ---------------------------------------------------------------------------
# Tab 1: Overview
# ---------------------------------------------------------------------------


class OverviewTab(ft.Container):
    """Overview: key metrics, milestones, recent events, source status."""

    def __init__(
        self,
        metadata: dict[str, Any],
        db: dict[str, Any],
        bulk: BulkInsightsResponse | None = None,
    ) -> None:
        super().__init__()

        daily = db["traffic_daily"]

        # Compute rolling 14d totals
        total_clones = sum(d["clones"] for d in daily)
        total_unique = sum(d["unique_cloners"] for d in daily)
        total_views = sum(d["views"] for d in daily)

        # Compute previous 14d for change arrows using bulk data (no DB)
        from datetime import datetime, timedelta

        stars_total = db["stars_total"]

        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        d14 = now - timedelta(days=14)
        d28 = now - timedelta(days=28)

        def _sum_bulk_range(key: str, start: datetime, end: datetime) -> int:
            rows = bulk.daily.get(key, []) if bulk else []
            return sum(int(r.value) for r in rows if start <= r.date < end)

        prev_clones = _sum_bulk_range("clones", d28, d14)
        prev_unique = _sum_bulk_range("unique_cloners", d28, d14)
        prev_views = _sum_bulk_range("views", d28, d14)

        pypi_14d = _sum_bulk_range("downloads_daily", d14, now + timedelta(days=1))
        pypi_prev14d = _sum_bulk_range("downloads_daily", d28, d14)

        # Stars in range from bulk events
        star_events = bulk.events.get("new_star", []) if bulk else []
        recent_stars = len([r for r in star_events if r.date >= d14])
        prev_star_count = len([r for r in star_events if d28 <= r.date < d14])

        insight_events = bulk.insight_events if bulk else []

        # Recent events of all types from bulk
        recent_events: list[dict[str, Any]] = []
        for ev in insight_events:
            meta = ev.metadata_ if isinstance(ev.metadata_, dict) else {}
            recent_events.append(
                {
                    "date": str(ev.date)[:10],
                    "description": ev.description,
                    "type": ev.event_type,
                    "metadata": meta,
                }
            )

        # Also add releases from bulk event metrics
        for r in bulk.events.get("releases", []) if bulk else []:
            meta = r.metadata_ or {}
            tag = meta.get("tag", "")
            if tag:
                recent_events.append(
                    {
                        "date": str(r.date)[:10],
                        "description": tag,
                        "type": "release",
                        "metadata": meta,
                    }
                )

        # Enrich reddit posts with upvote/comment data from bulk
        reddit_stats: dict[str, dict] = {}
        for r in bulk.events.get("post_stats", []) if bulk else []:
            meta = r.metadata_ or {}
            pid = meta.get("post_id", "")
            if pid:
                reddit_stats[pid] = {
                    "upvotes": int(r.value),
                    "comments": meta.get("comments", 0),
                    "subreddit": meta.get("subreddit", ""),
                }

        # Sort by date desc, take 15
        recent_events.sort(key=lambda x: x["date"], reverse=True)
        recent_events = recent_events[:15]

        # Latest day's deltas from bulk data (for "+X today/yesterday" subtitle)
        def _latest_daily(key: str) -> tuple[int, str]:
            """Get the most recent day's value and label ('today', 'yesterday', 'Xd ago')."""  # noqa: E501
            rows = bulk.daily.get(key, []) if bulk else []
            if not rows:
                return 0, "today"
            last = rows[-1]
            val = int(last.value)
            days_ago = (datetime.now() - last.date).days
            if days_ago == 0:
                return val, "today"
            if days_ago == 1:
                return val, "yesterday"
            return val, f"{days_ago}d ago"

        latest_clones, clones_label = _latest_daily("clones")
        latest_unique, unique_label = _latest_daily("unique_cloners")
        latest_views, views_label = _latest_daily("views")
        latest_downloads, dl_label = _latest_daily("downloads_daily")
        today_str = now.strftime("%Y-%m-%d")
        today_stars = len([r for r in star_events if str(r.date)[:10] == today_str])

        # Top-level metrics with change arrows + "+X today" subtitle
        metrics_row = ft.Row(
            [
                MetricCard(
                    "Stars",
                    str(stars_total),
                    "#FFD700",
                    change_pct=_pct(recent_stars, prev_star_count),
                    prev_value=f"+{today_stars} today",
                ),
                MetricCard(
                    "PyPI Downloads",
                    f"{db['pypi_total']:,}",
                    "#FF69B4",
                    change_pct=_pct(pypi_14d, pypi_prev14d),
                    prev_value=f"+{latest_downloads:,} {dl_label}",
                ),
                MetricCard(
                    "14d Clones",
                    f"{total_clones:,}",
                    Theme.Colors.PRIMARY,
                    change_pct=_pct(total_clones, prev_clones),
                    prev_value=f"+{latest_clones:,} {clones_label}",
                ),
                MetricCard(
                    "14d Unique",
                    f"{total_unique:,}",
                    Theme.Colors.INFO,
                    change_pct=_pct(total_unique, prev_unique),
                    prev_value=f"+{latest_unique:,} {unique_label}",
                ),
                MetricCard(
                    "14d Views",
                    f"{total_views:,}",
                    Theme.Colors.SUCCESS,
                    change_pct=_pct(total_views, prev_views),
                    prev_value=f"+{latest_views:,} {views_label}",
                ),
            ],
            spacing=Theme.Spacing.MD,
        )

        # Recent activity (left) — reuse ExpandableActivityRow
        from datetime import datetime as _dt

        from app.components.frontend.controls.data_table import (
            DataTableColumn,
            DataTableRow,
        )
        from app.services.system.activity import ActivityEvent

        from ..activity_feed import ExpandableActivityRow

        _row_col = [DataTableColumn("Activity")]

        activity_items: list[ft.Control] = []
        for ev in recent_events:
            status = EVENT_STATUS_MAP.get(ev["type"], "info")
            try:
                ts = _dt.strptime(ev["date"], "%Y-%m-%d")
            except (ValueError, TypeError):
                ts = _dt.now()

            # Build details from metadata
            meta = ev.get("metadata", {})
            details = None
            reddit_url = None
            if ev["type"] == "reddit_post":
                pid = meta.get("post_id", "")
                stats = reddit_stats.get(pid, {})
                parts = []
                sub = meta.get("subreddit") or stats.get("subreddit", "")
                if sub:
                    parts.append(f"r/{sub}")
                if stats.get("upvotes"):
                    parts.append(f"{stats['upvotes']} upvotes")
                if stats.get("comments"):
                    parts.append(f"{stats['comments']} comments")
                details = " \u2022 ".join(parts) if parts else None
                reddit_url = meta.get("url", "")
            elif ev["type"] == "star":
                usernames = meta.get("usernames", [])
                if usernames:
                    details = ", ".join(usernames[:10])
                    if len(usernames) > 10:
                        details += f" +{len(usernames) - 10} more"
            release_url = None
            fork_url = None
            if ev["type"] == "fork":
                actor = meta.get("actor", "")
                if actor:
                    fork_url = f"https://github.com/{actor}"
                    details = actor
            elif ev["type"] == "release":
                tag = meta.get("tag", ev["description"])
                release_url = (
                    f"https://github.com/lbedner/aegis-stack/releases/tag/{tag}"
                )
                details = tag
            elif ev["type"] in ("milestone_github", "milestone_pypi"):
                cat = meta.get("category", "")
                if cat:
                    details = cat.replace("_", " ").title()

            # For stars, show just the number in the title, name in details
            # For forks, show just "Fork" in the title, name in details
            message = ev["description"][:80]
            if ev["type"] == "star" and " \u2014 " in message:
                message = message.split(" \u2014 ")[0]  # "⭐ #99 — ncthuc" → "⭐ #99"
            elif ev["type"] == "fork" and not message.startswith("Fork #"):
                message = "Fork"

            event_obj = ActivityEvent(
                component="insights",
                event_type=ev["type"],
                message=message,
                status=status,
                timestamp=ts,
                details=details or (reddit_url if reddit_url else None),
            )
            row = ExpandableActivityRow(event_obj)
            # Hide the status dot — not needed in insights feed
            row.content.controls[0].controls[0].visible = False

            # For reddit posts, replace details with stats + clickable link
            if reddit_url and details:
                row._details_container.content = ft.Column(
                    [
                        SecondaryText(details),
                        ft.Container(
                            content=ft.Text(
                                reddit_url,
                                size=Theme.Typography.BODY_SMALL,
                                style=ft.TextStyle(
                                    color=Theme.Colors.INFO,
                                    decoration=ft.TextDecoration.UNDERLINE,
                                ),
                                selectable=False,
                            ),
                            on_click=lambda e, u=reddit_url: e.page.launch_url(u),
                            ink=True,
                        ),
                    ],
                    spacing=4,
                )
            elif fork_url:
                row._details_container.content = ft.Container(
                    content=ft.Text(
                        fork_url,
                        size=Theme.Typography.BODY_SMALL,
                        style=ft.TextStyle(
                            color=Theme.Colors.INFO,
                            decoration=ft.TextDecoration.UNDERLINE,
                        ),
                        selectable=False,
                    ),
                    on_click=lambda e, u=fork_url: e.page.launch_url(u),
                    ink=True,
                )
            elif release_url:
                row._details_container.content = ft.Container(
                    content=ft.Text(
                        release_url,
                        size=Theme.Typography.BODY_SMALL,
                        style=ft.TextStyle(
                            color=Theme.Colors.INFO,
                            decoration=ft.TextDecoration.UNDERLINE,
                        ),
                        selectable=False,
                    ),
                    on_click=lambda e, u=release_url: e.page.launch_url(u),
                    ink=True,
                )

            activity_items.append(
                DataTableRow(columns=_row_col, row_data=[row], padding=4)
            )

        # Goals (left) + Recent Activity (right) — mirrors the aegis-pulse
        # Summary layout. Goals stubbed pending the auth/no-auth/org
        # endpoint design; the old "Key Milestones" grid is gone since
        # those deltas now live on the metric cards via change_pct.
        goals_section = _build_overview_goals(bulk)

        side_by_side = ft.Row(
            [
                ft.Column([goals_section], spacing=6, expand=2),
                ft.Column(
                    [
                        H3Text("Recent Activity"),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        *activity_items,
                    ],
                    spacing=6,
                    expand=3,
                ),
            ],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Build the full OverviewView once — hero, chart series, and
        # everything else come from the same source of truth so the
        # numbers in the cards always agree with the curves below.
        overview_view = InsightViewService(bulk).overview(days=14) if bulk else None
        hero_view = overview_view.hero if overview_view else None

        # Daily Cloners chart — trim leading zero days so the curve starts
        # where collection actually picked up the project. Two series:
        # blue clones, purple unique-cloners — same palette as the GitHub
        # tab so the visual language stays consistent.
        clones_chart: LineChartCard | None = None
        if overview_view and overview_view.daily:
            trimmed = overview_view.daily
            for i, d in enumerate(overview_view.daily):
                if d.clones or d.unique_cloners:
                    trimmed = overview_view.daily[i:]
                    break
            if trimmed:
                clones_chart = LineChartCard(
                    title="Daily Cloners",
                    subtitle="unique people / clones per day",
                    x_labels=[d.date for d in trimmed],
                    series=[
                        LineSeries(
                            label="Clones",
                            color=ChartColors.TEAL,
                            points=[(i, d.clones) for i, d in enumerate(trimmed)],
                            tooltips=[f"Clones: {d.clones:,}" for d in trimmed],
                            fill=True,
                        ),
                        LineSeries(
                            label="Unique Cloners",
                            color=ChartColors.INDIGO,
                            points=[
                                (i, d.unique_cloners) for i, d in enumerate(trimmed)
                            ],
                            tooltips=[f"Unique: {d.unique_cloners:,}" for d in trimmed],
                        ),
                    ],
                )

        # Cumulative Stars chart — gold line with a 15%-opacity fill,
        # star-history style. min_y is bumped off zero so a healthy
        # project's curve doesn't get squashed against the bottom.
        stars_chart: LineChartCard | None = None
        if overview_view and overview_view.stars_daily:
            stars_daily = overview_view.stars_daily
            min_y_stars = max(
                0,
                stars_daily[0].value
                - max(1, (stars_daily[-1].value - stars_daily[0].value) // 4),
            )
            stars_chart = LineChartCard(
                title="Stars",
                subtitle="cumulative",
                x_labels=[d.date for d in stars_daily],
                series=[
                    LineSeries(
                        label="Cumulative Stars",
                        color=ChartColors.AMBER,
                        points=[(i, d.value) for i, d in enumerate(stars_daily)],
                        tooltips=[f"#{d.value:,}\n{d.date}" for d in stars_daily],
                        fill=True,
                        stroke_width=3,
                    ),
                ],
                min_y=min_y_stars,
            )

        # Daily Cloners (left, expand=2) + Stars (right, expand=1) —
        # mirrors the aegis-pulse Summary 2/3 + 1/3 split. Each side
        # collapses to nothing when its data is empty so we don't render
        # a half-empty row.
        charts_row: ft.Control | None = None
        if clones_chart and stars_chart:
            charts_row = ft.Row(
                [
                    ft.Container(content=clones_chart, expand=2),
                    ft.Container(content=stars_chart, expand=1),
                ],
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        elif clones_chart:
            charts_row = clones_chart
        elif stars_chart:
            charts_row = stars_chart

        column_children: list[ft.Control] = []
        if hero_view is not None:
            column_children.append(_build_overview_hero(hero_view))
        column_children.append(metrics_row)
        if charts_row is not None:
            column_children.extend([ft.Container(height=4), charts_row])
        column_children.extend([ft.Container(height=4), side_by_side])

        self.content = ft.Column(
            column_children,
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = Theme.Spacing.MD
        self.expand = True


# ---------------------------------------------------------------------------
# Tab 2: GitHub
# ---------------------------------------------------------------------------


class GitHubTrafficTab(InsightsTab):
    """GitHub traffic, events, and activity with date range and event annotations."""

    _default_days = 7

    # -- build content --------------------------------------------------------

    def _build_content(self) -> None:  # noqa: C901
        """Build or rebuild all content based on state."""
        data = self._data
        daily = data["daily"]

        last_date = daily[-1]["date"] if daily else ""
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_date),
            ft.Container(height=8),
        ]

        if not daily:
            content.append(SecondaryText("No GitHub traffic data collected yet."))
            self._content_column.controls = content
            return

        # Range-level aggregates
        total_clones = sum(d["clones"] for d in daily)
        total_unique = sum(d["unique_cloners"] for d in daily)
        total_views = sum(d["views"] for d in daily)
        total_visitors = sum(d["unique_visitors"] for d in daily)
        clone_ratio = total_clones / total_unique if total_unique > 0 else 0
        num_days = len(daily)
        range_label = next(
            (label for label, days in RANGE_OPTIONS if days == self._days),
            f"{self._days}d",
        )

        # Period-over-period change

        prev_c = data.get("prev_clones", 0)
        prev_u = data.get("prev_unique", 0)
        prev_v = data.get("prev_views", 0)
        prev_vis = data.get("prev_visitors", 0)

        # Latest day's values for subtitle
        last_day = daily[-1] if daily else {}
        last_clones = last_day.get("clones", 0)
        last_unique = last_day.get("unique_cloners", 0)
        last_views = last_day.get("views", 0)
        last_visitors = last_day.get("unique_visitors", 0)
        last_date = last_day.get("date", "")

        from datetime import datetime as _dt

        _days_ago = (
            (_dt.now() - _dt.strptime(last_date, "%Y-%m-%d")).days if last_date else 0
        )
        _day_label = (
            "today"
            if _days_ago == 0
            else "yesterday"
            if _days_ago == 1
            else f"{_days_ago}d ago"
        )

        # Metric cards — all on one row, always visible
        forks = data.get("forks", [])
        releases = data.get("releases", {})
        star_daily = data.get("star_events_daily", [])
        avg_stars = (
            sum(d["stars"] for d in star_daily) / len(star_daily) if star_daily else 0
        )

        # Previous period clone ratio
        prev_ratio = prev_c / prev_u if prev_u > 0 else 0
        prev_ratio_label = (
            f"prev: {prev_ratio:.1f}:1" if prev_ratio > 0 else f"in {range_label}"
        )

        # Previous period avg stars (from bulk data)
        from app.services.insights.query_service import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(self._days)
        prev_star_rows = [
            r
            for r in self._bulk.daily.get("star_events", [])
            if prev_cutoff <= r.date < cutoff
        ]
        prev_avg_stars = (
            sum(int(r.value) for r in prev_star_rows) / len(prev_star_rows)
            if prev_star_rows
            else 0
        )
        prev_stars_label = (
            f"prev: {prev_avg_stars:.1f}" if prev_star_rows else f"in {range_label}"
        )

        content.append(
            ft.Row(
                [
                    MetricCard(
                        "Clones",
                        f"{total_clones:,}",
                        Theme.Colors.PRIMARY,
                        change_pct=_pct(total_clones, prev_c),
                        prev_value=f"+{last_clones:,} {_day_label}",
                    ),
                    MetricCard(
                        "Unique",
                        f"{total_unique:,}",
                        Theme.Colors.INFO,
                        change_pct=_pct(total_unique, prev_u),
                        prev_value=f"+{last_unique:,} {_day_label}",
                        tooltip="Unique cloners per day, counted independently by GitHub. Not deduplicated across days.",  # noqa: E501
                    ),
                    MetricCard(
                        "Views",
                        f"{total_views:,}",
                        Theme.Colors.SUCCESS,
                        change_pct=_pct(total_views, prev_v),
                        prev_value=f"+{last_views:,} {_day_label}",
                    ),
                    MetricCard(
                        "Visitors",
                        f"{total_visitors:,}",
                        Theme.Colors.WARNING,
                        change_pct=_pct(total_visitors, prev_vis),
                        prev_value=f"+{last_visitors:,} {_day_label}",
                    ),
                    MetricCard(
                        "Clone Ratio",
                        f"{clone_ratio:.1f}:1",
                        "#E91E63",
                        prev_value=prev_ratio_label,
                    ),
                    MetricCard(
                        "Forks",
                        str(len(forks)),
                        "#A855F7",
                        prev_value=f"in {range_label}",
                    ),
                    MetricCard(
                        "Releases",
                        str(len(releases)),
                        "#22C55E",
                        prev_value=f"in {range_label}",
                    ),
                    MetricCard(
                        "Avg Stars/Day",
                        f"{avg_stars:.1f}",
                        "#F59E0B",
                        prev_value=prev_stars_label,
                    ),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Date range text
        date_range = (
            f"{_pretty_date(daily[0]['date'])} \u2014 {_pretty_date(daily[-1]['date'])}"
        )
        content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

        # Event chips
        first_date = daily[0]["date"]
        last_date = daily[-1]["date"]
        window_events = [
            (date, label, etype)
            for date, label, etype in data.get("all_events", [])
            if first_date <= date <= last_date
        ]
        chips = self._render_event_chips(window_events)
        if chips:
            content.append(chips)

        content.append(ft.Container(height=4))

        # -- Clones + Unique chart with event annotations ---------------------

        highlighted = self._highlighted_dates

        # Trim leading zero days separately for each chart
        clone_daily = daily
        for i, d in enumerate(daily):
            if d["clones"] or d["unique_cloners"]:
                clone_daily = daily[i:]
                break

        view_daily = daily
        for i, d in enumerate(daily):
            if d["views"] or d["unique_visitors"]:
                view_daily = daily[i:]
                break

        # Build a date→event-labels map. The Events dropdown's selected
        # types narrow the set when non-empty (== filtered); an empty
        # set means "All", showing every event in the chart's tooltip
        # overlay.
        events_by_date: dict[str, list[str]] = {}
        for ev_date, ev_label, ev_etype in data.get("all_events", []):
            if (
                self._selected_event_types
                and ev_etype not in self._selected_event_types
            ):
                continue
            events_by_date.setdefault(ev_date, []).append(ev_label)

        # -- Clones + Unique chart --------------------------------------------
        # Indices on the chart that correspond to the currently selected
        # event chip — drives the per-point amber marker that lets the
        # eye correlate the chip with its date.
        clone_highlights = frozenset(
            i for i, d in enumerate(clone_daily) if d["date"] in highlighted
        )
        clone_series = [
            LineSeries(
                label="Clones",
                color=ChartColors.TEAL,
                points=[(i, d["clones"]) for i, d in enumerate(clone_daily)],
                tooltips=[f"Clones: {d['clones']:,}" for d in clone_daily],
                fill=True,
                highlighted_indices=clone_highlights,
            ),
            LineSeries(
                label="Unique Cloners",
                color=ChartColors.INDIGO,
                points=[(i, d["unique_cloners"]) for i, d in enumerate(clone_daily)],
                tooltips=[f"Unique: {d['unique_cloners']:,}" for d in clone_daily],
                highlighted_indices=clone_highlights,
            ),
        ]
        content.append(
            LineChartCard(
                title="Clones",
                subtitle="clones / unique cloners per day",
                x_labels=[d["date"] for d in clone_daily],
                series=clone_series,
                height=300,
                event_annotations=[
                    events_by_date.get(d["date"], []) for d in clone_daily
                ],
            )
        )

        content.append(ft.Container(height=12))

        # -- Views + Visitors chart -------------------------------------------
        view_highlights = frozenset(
            i for i, d in enumerate(view_daily) if d["date"] in highlighted
        )
        view_series = [
            LineSeries(
                label="Views",
                color=ChartColors.TEAL,
                points=[(i, d["views"]) for i, d in enumerate(view_daily)],
                tooltips=[f"Views: {d['views']:,}" for d in view_daily],
                fill=True,
                highlighted_indices=view_highlights,
            ),
            LineSeries(
                label="Visitors",
                color=ChartColors.VIOLET,
                points=[(i, d["unique_visitors"]) for i, d in enumerate(view_daily)],
                tooltips=[f"Visitors: {d['unique_visitors']:,}" for d in view_daily],
                highlighted_indices=view_highlights,
            ),
        ]
        content.append(
            LineChartCard(
                title="Views",
                subtitle="page views / unique visitors per day",
                x_labels=[d["date"] for d in view_daily],
                series=view_series,
                height=300,
                event_annotations=[
                    events_by_date.get(d["date"], []) for d in view_daily
                ],
            )
        )

        # Interpretation
        content.append(
            ft.Container(
                content=SecondaryText(
                    f"{range_label} clone ratio of {clone_ratio:.1f}:1 across {total_clones:,} clones "  # noqa: E501
                    f"from {total_unique:,} unique cloners. "
                    f"Traffic data covers {num_days} days.",
                    size=Theme.Typography.BODY_SMALL,
                ),
                padding=ft.padding.symmetric(horizontal=4, vertical=8),
            )
        )

        # -- Avg Unique Cloners by Day of Week --------------------------------
        # Source/cadence pattern lives here — peak/trough days are colored
        # distinctly so the rhythm pops without parsing seven nearly-equal
        # bars. Hidden when there's no cloner data at all.
        weekday = data.get("weekday", [])
        if weekday and any(v > 0 for v in weekday):
            wk_min = min(weekday)
            wk_max = max(weekday)
            pad_bottom = max((wk_max - wk_min) * 0.3, 1)
            pad_top = max((wk_max - wk_min) * 0.15, 1)
            wk_min_y = max(0, int(wk_min - pad_bottom))
            wk_max_y = int(wk_max + pad_top + 0.5)

            # Peak (brand teal) + trough (violet) + middle days (muted teal)
            # — same color treatment as the aegis-pulse Summary tab.
            peak_color = ChartColors.TEAL
            trough_color = ChartColors.VIOLET
            mid_color = ft.Colors.with_opacity(0.55, ChartColors.TEAL)

            wk_groups: list[ft.BarChartGroup] = []
            for i, v in enumerate(weekday):
                if v == wk_max:
                    bar_color = peak_color
                elif v == wk_min:
                    bar_color = trough_color
                else:
                    bar_color = mid_color
                wk_groups.append(
                    ft.BarChartGroup(
                        x=i,
                        bar_rods=[
                            ft.BarChartRod(
                                from_y=wk_min_y,
                                to_y=v,
                                width=28,
                                color=bar_color,
                                tooltip=f"{['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][i]}: {v:.1f}",
                                border_radius=4,
                            )
                        ],
                    )
                )

            # Y-axis ticks rendered explicitly so they pick up the same
            # small + muted styling as the bottom axis (and as the
            # LineChartCard left-axis treatment) — without this, Flet
            # falls back to its default-styled auto-labels which are
            # larger and use the default white text color.
            wk_step = _smart_step(wk_max_y - wk_min_y)
            wk_left_labels: list[ft.ChartAxisLabel] = []
            if wk_step > 0:
                tick = int(wk_min_y) + (
                    wk_step - (int(wk_min_y) % wk_step)
                    if int(wk_min_y) % wk_step
                    else 0
                )
                while tick <= wk_max_y:
                    wk_left_labels.append(
                        ft.ChartAxisLabel(
                            value=tick,
                            label=ft.Text(
                                f"{int(tick):,}",
                                size=9,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        )
                    )
                    tick += wk_step

            wk_chart = ft.BarChart(
                bar_groups=wk_groups,
                left_axis=ft.ChartAxis(labels_size=50, labels=wk_left_labels),
                bottom_axis=ft.ChartAxis(
                    labels_size=40,
                    labels=[
                        ft.ChartAxisLabel(
                            value=i,
                            label=ft.Text(
                                ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][i],
                                size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        )
                        for i in range(7)
                    ],
                ),
                horizontal_grid_lines=ft.ChartGridLines(
                    color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                    width=1,
                ),
                **chart_tooltip_kwargs(),
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                interactive=True,
                min_y=wk_min_y,
                max_y=wk_max_y,
                height=240,
                expand=True,
            )

            # Wrap in the same MetricCard-style card as the line charts
            # so the surfaces stay visually unified. Title row dropped
            # to match LineChartCard — the chart speaks for itself.
            content.append(ft.Container(height=12))
            content.append(
                ft.Container(
                    content=wk_chart,
                    padding=Theme.Spacing.MD,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border=ft.border.all(0.5, ft.Colors.OUTLINE),
                    border_radius=Theme.Components.CARD_RADIUS,
                )
            )

        # -- Referrers + Popular Paths ----------------------------------------
        # Side-by-side data tables, matching the aegis-pulse Summary tab.
        # Each name cell is a clickable link (referrer domain or
        # github.com path), so visitors can dig into the source from
        # the modal instead of copy-pasting URLs.
        referrers = data.get("referrers", [])
        paths = data.get("popular_paths", [])

        traffic_columns = [
            DataTableColumn("Source", style="primary"),
            DataTableColumn("Views", width=80, alignment="right", style="body"),
            DataTableColumn("Unique", width=80, alignment="right", style="secondary"),
        ]

        def _link_cell(label: str, url: str) -> ft.Container:
            return ft.Container(
                content=ft.Text(
                    label,
                    size=Theme.Typography.BODY,
                    style=ft.TextStyle(
                        color=Theme.Colors.INFO,
                        decoration=ft.TextDecoration.UNDERLINE,
                    ),
                    selectable=False,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                on_click=lambda e, u=url: e.page.launch_url(u),
                ink=True,
                expand=True,
            )

        referrer_rows = [
            [
                _link_cell(
                    ref["domain"],
                    f"https://{ref['domain']}"
                    if "." in ref["domain"]
                    else f"https://www.google.com/search?q={ref['domain']}",
                ),
                f"{ref['views']:,}",
                f"{ref['uniques']:,}",
            ]
            for ref in referrers
        ]

        paths_rows = [
            [
                _link_cell(p["path"], f"https://github.com{p['path']}"),
                f"{p['views']:,}",
                f"{p['uniques']:,}",
            ]
            for p in paths
        ]

        referrers_section = ft.Column(
            [
                H3Text("Referrers"),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                DataTable(
                    columns=traffic_columns,
                    rows=referrer_rows,
                    empty_message="No referrer data available.",
                ),
            ],
            spacing=6,
            expand=1,
        )
        paths_section = ft.Column(
            [
                H3Text("Popular Paths"),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                DataTable(
                    columns=traffic_columns,
                    rows=paths_rows,
                    empty_message="No popular path data available.",
                ),
            ],
            spacing=6,
            expand=1,
        )

        content.append(ft.Container(height=8))
        content.append(
            ft.Row(
                [referrers_section, paths_section],
                spacing=Theme.Spacing.LG,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

        self._content_column.controls = content

    # -- data loader ----------------------------------------------------------

    def _load_data(self, days: int = 14) -> dict[str, Any]:
        """Load GitHub data from bulk pre-loaded data with date cutoff."""
        from app.services.insights.query_service import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

        # Traffic daily
        clones_rows = [
            r for r in self._bulk.daily.get("clones", []) if r.date >= cutoff
        ]
        unique_rows = [
            r for r in self._bulk.daily.get("unique_cloners", []) if r.date >= cutoff
        ]
        views_rows = [r for r in self._bulk.daily.get("views", []) if r.date >= cutoff]
        visitors_rows = [
            r for r in self._bulk.daily.get("unique_visitors", []) if r.date >= cutoff
        ]

        unique_map = {str(r.date)[:10]: int(r.value) for r in unique_rows}
        views_map = {str(r.date)[:10]: int(r.value) for r in views_rows}
        visitors_map = {str(r.date)[:10]: int(r.value) for r in visitors_rows}

        daily: list[dict[str, Any]] = []
        for r in clones_rows:
            day = str(r.date)[:10]
            clones = int(r.value)
            unique = unique_map.get(day, 0)
            views = views_map.get(day, 0)
            visitors = visitors_map.get(day, 0)
            # Skip days with no activity to avoid dead space on chart
            if clones == 0 and unique == 0 and views == 0 and visitors == 0:
                continue
            daily.append(
                {
                    "date": day,
                    "clones": clones,
                    "unique_cloners": unique,
                    "views": views,
                    "unique_visitors": visitors,
                }
            )

        # Referrers (latest snapshot)
        referrers_row = self._bulk.latest.get("referrers")
        referrers: list[dict[str, Any]] = []
        if referrers_row and referrers_row.metadata_:
            meta = referrers_row.metadata_
            if isinstance(meta, dict) and not meta.get("referrers"):
                for domain, counts in meta.items():
                    if isinstance(counts, dict):
                        referrers.append(
                            {
                                "domain": domain,
                                "views": counts.get("views", 0),
                                "uniques": counts.get("uniques", 0),
                            }
                        )
            else:
                for ref in meta.get("referrers", []):
                    referrers.append(
                        {
                            "domain": ref.get("referrer", ref.get("domain", "unknown")),
                            "views": ref.get("count", ref.get("views", 0)),
                            "uniques": ref.get("uniques", 0),
                        }
                    )
            referrers.sort(key=lambda x: -x["views"])

        # Popular paths (latest snapshot)
        paths_row = self._bulk.latest.get("popular_paths")
        popular_paths: list[dict[str, Any]] = []
        if paths_row and paths_row.metadata_:
            for p in paths_row.metadata_.get(
                "paths", paths_row.metadata_.get("popular_paths", [])
            ):
                popular_paths.append(
                    {
                        "path": p.get("path", "unknown"),
                        "title": p.get("title", ""),
                        "views": p.get("count", p.get("views", 0)),
                        "uniques": p.get("uniques", 0),
                    }
                )

        # Fork events
        fork_rows = [r for r in self._bulk.events.get("forks", []) if r.date >= cutoff]
        forks: list[dict[str, str]] = []
        for r in fork_rows:
            meta = r.metadata_ or {}
            forks.append(
                {"actor": meta.get("actor", "unknown"), "date": str(r.date)[:10]}
            )

        # Star events daily
        star_rows = [
            r for r in self._bulk.daily.get("star_events", []) if r.date >= cutoff
        ]
        star_events_daily: list[dict[str, Any]] = []
        for r in star_rows:
            star_events_daily.append({"date": str(r.date)[:10], "stars": int(r.value)})

        # Activity summary daily
        activity_rows = [
            r for r in self._bulk.daily.get("activity_summary", []) if r.date >= cutoff
        ]
        activity_summary: list[dict[str, Any]] = []
        for r in activity_rows:
            meta = r.metadata_ or {}
            entry: dict[str, Any] = {"date": str(r.date)[:10]}
            for field in (
                "push",
                "issues",
                "pull_requests",
                "pull_request_reviews",
                "issue_comments",
                "forks",
                "stars",
                "releases",
                "creates",
                "deletes",
            ):
                entry[field] = meta.get(field, 0)
            activity_summary.append(entry)

        # Build all_events list for chips
        all_events: list[tuple[str, str, str]] = []

        # Release events from metrics
        release_rows = [
            r for r in self._bulk.events.get("releases", []) if r.date >= cutoff
        ]
        releases: dict[str, str] = {}
        for r in release_rows:
            meta = r.metadata_ or {}
            tag = meta.get("tag", "")
            day = str(r.date)[:10]
            if tag:
                all_events.append((day, tag, "release"))
                if day in releases:
                    releases[day] += f"\n{tag}"
                else:
                    releases[day] = tag

        # InsightEvent rows filtered to GitHub-relevant types
        cutoff_str = str(cutoff.date())
        for ev in [
            ev
            for ev in self._bulk.insight_events
            if str(ev.date)[:10] >= cutoff_str and ev.event_type in GITHUB_EVENT_TYPES
        ]:
            day = str(ev.date)[:10]
            all_events.append((day, ev.description[:60], ev.event_type))
            # Only add release-type events to the releases annotation map
            if ev.event_type == "release":
                if day in releases:
                    releases[day] += f"\n{ev.description[:60]}"
                else:
                    releases[day] = ev.description[:60]

        all_events.sort(key=lambda x: x[0])

        # Average unique cloners by day-of-week (Sun..Sat) — sourced from
        # view_service so this stays consistent with whatever the rest of
        # the app shows. Empty list when there's no cloner data, so the
        # builder can hide the chart instead of rendering an empty axis.
        github_view = InsightViewService(self._bulk).github(days=days)
        weekday = github_view.unique_cloners_by_weekday

        return {
            "daily": daily,
            "referrers": referrers,
            "popular_paths": popular_paths,
            "forks": forks,
            "releases": releases,
            "all_events": all_events,
            "activity_summary": activity_summary,
            "star_events_daily": star_events_daily,
            "weekday": weekday,
            "prev_clones": sum(
                int(r.value)
                for r in self._bulk.daily.get("clones", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_unique": sum(
                int(r.value)
                for r in self._bulk.daily.get("unique_cloners", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_views": sum(
                int(r.value)
                for r in self._bulk.daily.get("views", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_visitors": sum(
                int(r.value)
                for r in self._bulk.daily.get("unique_visitors", [])
                if prev_cutoff <= r.date < cutoff
            ),
        }


# ---------------------------------------------------------------------------
# Tab 3: Stars
# ---------------------------------------------------------------------------


class StarsTab(InsightsTab):
    """Stars: cumulative chart, recent list, event chips — with date range."""

    _default_days = 7

    def _build_content(self) -> None:
        """Build or rebuild all content based on state."""
        data = self._data
        star_history = data["star_history"]
        total_stars = data["total_stars"]
        range_stars = data["range_stars"]

        last_date = star_history[-1]["date"] if star_history else ""
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_date),
            ft.Container(height=8),
        ]

        # Metric cards
        num_days = len(star_history) if star_history else 1
        avg_per_day = range_stars / num_days if num_days else 0

        content.append(
            ft.Row(
                [
                    MetricCard("Total Stars", str(total_stars), "#FFD700"),
                    MetricCard("In Range", str(range_stars), Theme.Colors.INFO),
                    MetricCard("Avg / Day", f"{avg_per_day:.1f}", Theme.Colors.SUCCESS),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        if not star_history:
            content.append(SecondaryText("No star events in this range."))
            self._content_column.controls = content
            return

        # Date range text
        date_range = f"{_pretty_date(star_history[0]['date'])} \u2014 {_pretty_date(star_history[-1]['date'])}"  # noqa: E501
        content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

        # Event chips — only on dates with stars, exclude star type
        star_dates = {d["date"] for d in star_history}
        chips = self._render_event_chips(
            data.get("all_events", []),
            valid_dates=star_dates,
            exclude_types={"star"},
        )
        if chips:
            content.append(chips)

        # Star History cumulative chart
        max_stars = star_history[-1]["stars"]
        min_stars = star_history[0]["stars"]
        padding = max(1, (max_stars - min_stars) // 4)
        star_min_y = max(0, min_stars - padding)
        star_range = max_stars - star_min_y
        star_step = _smart_step(star_range)
        star_max_y = int((max_stars // star_step + 1) * star_step)
        highlighted = self._highlighted_dates
        # Filter releases: exclude star events, only dates that have chart points
        releases_map = data.get("releases", {})
        non_star_releases: dict[str, str] = {}
        for day, label in releases_map.items():
            if day not in star_dates:
                continue
            lines = [ln for ln in label.split("\n") if not ln.startswith("\u2b50")]
            if lines:
                non_star_releases[day] = "\n".join(lines)

        history_points: list[ft.LineChartDataPoint] = []
        release_anno: list[ft.LineChartDataPoint] = []

        for i, d in enumerate(star_history):
            is_hl = d["date"] in highlighted
            hl_point = ChartPoint.highlight() if is_hl else None
            count = d.get("count", 1)
            names = d.get("usernames", [])
            if count == 1:
                tip = f"#{d['stars']} — {names[0] if names else ''}\n{_pretty_date(d['date'])}"  # noqa: E501
            else:
                first_num = d["stars"] - count + 1
                tip = f"#{first_num}-#{d['stars']} ({count} stars)\n{_pretty_date(d['date'])}"  # noqa: E501
            history_points.append(
                ft.LineChartDataPoint(
                    i,
                    d["stars"],
                    tooltip=tip,
                    point=hl_point,
                )
            )

            rel = non_star_releases.get(d["date"])
            if rel:
                release_anno.append(
                    ft.LineChartDataPoint(i, 0, tooltip=rel, show_tooltip=True)
                )
            else:
                release_anno.append(ft.LineChartDataPoint(i, 0, show_tooltip=False))

        chart_series = [
            ft.LineChartData(
                data_points=history_points,
                stroke_width=3,
                color=ChartColors.TEAL,
                curved=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.15, ChartColors.TEAL),
                point=ChartPoint.dot(ChartColors.TEAL),
                stroke_cap_round=True,
            ),
        ]
        if any(p.show_tooltip for p in release_anno):
            chart_series.append(
                ft.LineChartData(
                    data_points=release_anno,
                    stroke_width=0,
                    color="#9CA3AF",
                )
            )

        history_chart = _make_line_chart(
            chart_series, star_max_y, star_history, star_step, min_y=star_min_y
        )
        content.append(
            ft.Container(content=history_chart, margin=ft.margin.only(right=20))
        )
        content.append(_make_legend([(ChartColors.TEAL, "Cumulative Stars")]))

        self._content_column.controls = content

    def _load_data(self, days: int = 9999) -> dict[str, Any]:
        """Load star data from bulk pre-loaded data with date cutoff."""
        from app.services.insights.query_service import InsightQueryService

        cutoff, _ = InsightQueryService.compute_cutoffs(days)

        # All stars (for total count)
        all_rows = self._bulk.events.get("new_star", [])
        total_stars = len(all_rows)

        if not all_rows:
            return {
                "star_history": [],
                "stars_recent": [],
                "total_stars": 0,
                "range_stars": 0,
                "all_events": [],
                "releases": {},
            }

        # Stars in range
        range_rows = [r for r in all_rows if r.date >= cutoff]
        range_stars = len(range_rows)

        # Cumulative history - only days with stars, within range
        by_date: dict[str, dict[str, Any]] = {}
        for r in range_rows:
            day = str(r.date)[:10]
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            if day not in by_date:
                by_date[day] = {"max_num": 0, "count": 0, "usernames": []}
            by_date[day]["max_num"] = max(by_date[day]["max_num"], int(r.value))
            by_date[day]["count"] += 1
            by_date[day]["usernames"].append(meta.get("username", "unknown"))
        star_history = [
            {
                "date": d,
                "stars": info["max_num"],
                "count": info["count"],
                "usernames": info["usernames"],
            }
            for d, info in sorted(by_date.items())
        ]

        # Recent stars (last 20 in range)
        stars_recent: list[dict[str, Any]] = []
        for r in reversed(range_rows[-20:]):
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            stars_recent.append(
                {
                    "number": int(r.value),
                    "username": meta.get("username", "unknown"),
                    "location": meta.get("location", ""),
                    "company": meta.get("company", ""),
                    "date": str(r.date)[:10],
                }
            )

        # Events for chips + chart annotations
        all_events: list[tuple[str, str, str]] = []
        for r in self._bulk.events.get("releases", []):
            tag = (r.metadata_ or {}).get("tag", "")
            if tag:
                all_events.append((str(r.date)[:10], tag, "release"))
        cutoff_str = str(cutoff.date())
        for ev in [
            ev
            for ev in self._bulk.insight_events
            if str(ev.date)[:10] >= cutoff_str and ev.event_type in GITHUB_EVENT_TYPES
        ]:
            all_events.append((str(ev.date)[:10], ev.description[:60], ev.event_type))

        release_map: dict[str, str] = {}
        for date, label, _ in all_events:
            if date in release_map:
                release_map[date] += f"\n{label}"
            else:
                release_map[date] = label

        all_events.sort(key=lambda x: x[0])

        return {
            "star_history": star_history,
            "stars_recent": stars_recent,
            "total_stars": total_stars,
            "range_stars": range_stars,
            "all_events": all_events,
            "releases": release_map,
        }


# ---------------------------------------------------------------------------
# Tab 4: PyPI (unchanged -- already uses real data)
# ---------------------------------------------------------------------------


class PyPITab(InsightsTab):
    """PyPI: real data from database with date range filter.

    Mirrors the aegis-pulse PyPI panel — always shows Total downloads
    (teal, filled) and Human-only downloads (indigo, line on top) on a
    single chart. The CI/mirror split lives in the chart, not behind a
    toggle, since users typically want to see both at once and seeing
    them stacked is the comparison that actually answers the
    "how much real adoption?" question.
    """

    _default_days = 7

    def _build_content(self) -> None:
        """Build or rebuild content for the current date range."""
        data = self._data
        daily = data["daily"]

        # Compute averages from daily data
        bot_pct = data["bot_percent"]
        num_days = len(daily) if daily else 1
        range_label = next(
            (label for label, days in RANGE_OPTIONS if days == self._days),
            f"{self._days}d",
        )

        range_all = sum(d["total"] for d in daily) if daily else 0

        # Headline metric tracks the same number pulse leads with: total
        # downloads (incl. CI/mirror). Human-only is still on the chart
        # — readers who care about real adoption see the indigo line
        # over the teal area and can compare visually.
        total_display = f"{range_all:,}"
        avg_day = range_all // num_days if num_days else 0

        avg_week = avg_day * 7
        avg_month = avg_day * 30

        last_date = daily[-1]["date"] if daily else ""
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_date),
            ft.Container(height=8),
        ]

        # Period-over-period change tracks the headline (total).
        prev_val = data.get("prev_total", 0)
        cur_val = range_all

        # Latest day's value for subtitle
        last_day = daily[-1] if daily else {}
        last_dl = last_day.get("total", 0)
        last_dl_date = last_day.get("date", "")
        from datetime import datetime as _dt

        _dl_days_ago = (
            (_dt.now() - _dt.strptime(last_dl_date, "%Y-%m-%d")).days
            if last_dl_date
            else 0
        )
        _dl_label = (
            "today"
            if _dl_days_ago == 0
            else "yesterday"
            if _dl_days_ago == 1
            else f"{_dl_days_ago}d ago"
        )

        # Metric cards
        metrics_row = ft.Row(
            [
                MetricCard(
                    "Total Downloads",
                    total_display,
                    ChartColors.TEAL,
                    change_pct=_pct(cur_val, prev_val),
                    prev_value=f"+{last_dl:,} {_dl_label}",
                ),
                MetricCard(
                    "Avg / Day",
                    f"{avg_day:,}",
                    Theme.Colors.INFO,
                    prev_value=f"in {range_label}",
                ),
                MetricCard(
                    "Avg / Week",
                    f"{avg_week:,}",
                    Theme.Colors.SUCCESS,
                    prev_value=f"in {range_label}",
                ),
                MetricCard(
                    "Avg / Month",
                    f"{avg_month:,}",
                    Theme.Colors.PRIMARY,
                    prev_value=f"in {range_label}",
                ),
                MetricCard(
                    "Bot %",
                    f"{bot_pct:.0f}%",
                    Theme.Colors.WARNING if bot_pct > 50 else Theme.Colors.INFO,
                    prev_value=f"in {range_label}",
                ),
            ],
            spacing=Theme.Spacing.MD,
        )
        content.append(metrics_row)

        # Date range + events in window
        releases = data.get("releases", {})
        if daily:
            date_range = f"{_pretty_date(daily[0]['date'])} \u2014 {_pretty_date(daily[-1]['date'])}"  # noqa: E501
            content.append(ft.Container(height=8))
            content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

            # Event chips
            first_date = daily[0]["date"] if daily else ""
            last_date = daily[-1]["date"] if daily else ""
            window_events = [
                (date, label, etype)
                for date, label, etype in data.get("all_events", [])
                if first_date <= date <= last_date
            ]
            chips = self._render_event_chips(window_events)
            if chips:
                content.append(chips)

        # Chart 1: Downloads — always shows both Total (teal, filled
        # area) and Human (indigo, line on top), matching the
        # aegis-pulse PyPI panel exactly. Total is the upper bound, so
        # the y-axis is sized to it.
        if daily:
            max_val = max(d["total"] for d in daily)

            # Smart rounding: small values round to nearest 5, medium to 25, large to 100  # noqa: E501
            if max_val <= 20:
                step = 5
            elif max_val <= 100:
                step = 10
            elif max_val <= 500:
                step = 50
            else:
                step = 100
            rounded_max = int((max_val // step + 1) * step)

            releases = data.get("releases", {})
            highlighted = self._highlighted_dates

            total_points: list[ft.LineChartDataPoint] = []
            human_points: list[ft.LineChartDataPoint] = []
            release_points: list[ft.LineChartDataPoint] = []
            for i, d in enumerate(daily):
                is_hl = d["date"] in highlighted
                point_style = ChartPoint.highlight() if is_hl else None
                total_points.append(
                    ft.LineChartDataPoint(
                        i,
                        d["total"],
                        tooltip=f"Total: {d['total']:,}",
                        point=point_style,
                    )
                )
                human_points.append(
                    ft.LineChartDataPoint(
                        i,
                        d["human"],
                        tooltip=f"Human: {d['human']:,}",
                    )
                )

                rel = releases.get(d["date"])
                if rel:
                    release_points.append(
                        ft.LineChartDataPoint(i, 0, tooltip=f"{rel}", show_tooltip=True)
                    )
                else:
                    release_points.append(
                        ft.LineChartDataPoint(i, 0, show_tooltip=False)
                    )

            chart1_series = [
                # Total = teal filled area (pulse THEME.teal #17CCBF)
                ft.LineChartData(
                    data_points=total_points,
                    stroke_width=2,
                    color=ChartColors.TEAL,
                    below_line_bgcolor=ft.Colors.with_opacity(0.15, ChartColors.TEAL),
                    curved=True,
                    stroke_cap_round=True,
                ),
                # Human = indigo line on top (pulse THEME.indigo #6366F1)
                ft.LineChartData(
                    data_points=human_points,
                    stroke_width=2,
                    color=ChartColors.INDIGO,
                    curved=True,
                    stroke_cap_round=True,
                ),
                # Release annotations — invisible series, tooltip-only
                ft.LineChartData(
                    data_points=release_points,
                    stroke_width=0,
                    color="#9CA3AF",
                ),
            ]

            chart1 = _make_line_chart(chart1_series, rounded_max, daily, step)
            legend1 = _make_legend(
                [
                    (ChartColors.TEAL, "Total"),
                    (ChartColors.INDIGO, "Human"),
                ]
            )

            chart1_wrapped = ft.Container(
                content=chart1,
                margin=ft.margin.only(right=20),
            )
            content.extend([ft.Container(height=8), chart1_wrapped, legend1])

        # Bar chart: downloads by version
        versions = data["versions"]
        if versions:
            # Sort by version number (semantic sort)
            def _version_sort_key(ver: str) -> tuple:
                parts = (
                    ver.replace("rc", ".")
                    .replace("a", ".")
                    .replace("b", ".")
                    .split(".")
                )
                return tuple(int(p) if p.isdigit() else 0 for p in parts)

            all_sorted = sorted(versions.keys(), key=_version_sort_key)

            # Filter out versions with 0 downloads
            sorted_versions = []
            for ver in all_sorted:
                info = versions[ver]
                val = info.get("total", 0) if isinstance(info, dict) else info
                if val > 0:
                    sorted_versions.append(ver)

            bar_groups = []
            bar_max = 0
            for i, ver in enumerate(sorted_versions):
                info = versions[ver]
                val = info.get("total", 0) if isinstance(info, dict) else info

                bar_max = max(bar_max, val)

                bar_groups.append(
                    ft.BarChartGroup(
                        x=i,
                        bar_rods=[
                            ft.BarChartRod(
                                from_y=0,
                                to_y=val,
                                width=max(8, 400 // len(sorted_versions)),
                                color=ChartColors.TEAL,
                                border_radius=ft.border_radius.only(
                                    top_left=3, top_right=3
                                ),
                                tooltip=f"{ver}: {val:,}",
                            )
                        ],
                    )
                )

            bar_rounded_max = int(bar_max * 1.15) + 1 if bar_max > 0 else 10

            # Show every Nth label to avoid overlap
            label_step = max(1, len(sorted_versions) // 12)

            version_bar = ft.BarChart(
                bar_groups=bar_groups,
                left_axis=ft.ChartAxis(
                    labels_size=50, labels_interval=max(1, bar_rounded_max // 4)
                ),
                bottom_axis=ft.ChartAxis(
                    labels_size=50,
                    labels=[
                        ft.ChartAxisLabel(
                            value=i,
                            label=ft.Text(
                                ver, size=8, color=ft.Colors.ON_SURFACE_VARIANT
                            ),
                        )
                        for i, ver in enumerate(sorted_versions)
                        if i % label_step == 0 or i == len(sorted_versions) - 1
                    ],
                ),
                horizontal_grid_lines=ft.ChartGridLines(
                    interval=bar_rounded_max // 4 or 1,
                    color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                    width=1,
                ),
                tooltip_bgcolor=Theme.Colors.SURFACE_1,
                tooltip_rounded_radius=8,
                tooltip_padding=10,
                tooltip_tooltip_border_side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                max_y=bar_rounded_max,
                height=250,
                expand=True,
            )

            bar_wrapped = ft.Container(
                content=version_bar, margin=ft.margin.only(right=20)
            )
            bar_legend = ft.Row(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=10,
                                height=10,
                                bgcolor=ChartColors.TEAL,
                                border_radius=5,
                            ),
                            SecondaryText(
                                "Downloads by Version",
                                size=Theme.Typography.BODY_SMALL,
                            ),
                        ],
                        spacing=4,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            )

            content.extend([ft.Container(height=12), bar_wrapped, bar_legend])

        # Three pie charts in one row
        pie_charts: list[ft.Control] = []

        installers = data["installers"]
        if installers:
            total_inst = sum(installers.values())
            pie_charts.append(
                PieChartCard(
                    title=f"By Installer ({range_label})",
                    sections=[
                        {"value": count, "label": f"{name} ({count / total_inst:.0%})"}
                        for name, count in list(installers.items())[:8]
                    ],
                )
            )

        countries = data["countries"]
        if countries:
            total_c = sum(countries.values())
            pie_charts.append(
                PieChartCard(
                    title=f"By Country ({range_label})",
                    sections=[
                        {"value": count, "label": f"{code} ({count / total_c:.0%})"}
                        for code, count in list(countries.items())[:10]
                    ],
                )
            )

        dist_types = data.get("types", {})
        if dist_types:
            total_t = sum(dist_types.values())
            pie_charts.append(
                PieChartCard(
                    title=f"Dist Type ({range_label})",
                    sections=[
                        {"value": count, "label": f"{name} ({count / total_t:.0%})"}
                        for name, count in dist_types.items()
                    ],
                )
            )

        if pie_charts:
            content.extend(
                [
                    ft.Container(height=8),
                    ft.Row(pie_charts, spacing=Theme.Spacing.MD),
                ]
            )

        # Version table
        versions = data["versions"]
        if versions:
            from app.components.frontend.controls.data_table import (
                DataTable,
                DataTableColumn,
            )

            version_columns = [
                DataTableColumn(header="Version", width=100, style="primary"),
                DataTableColumn(header="Total", width=80, alignment="right"),
                DataTableColumn(header="Human", width=80, alignment="right"),
                DataTableColumn(header="Bot", width=80, alignment="right"),
                DataTableColumn(header="Bot %", width=70, alignment="right"),
            ]

            version_rows_data = []
            for ver, info in list(versions.items())[:10]:
                if isinstance(info, dict):
                    t, h = info.get("total", 0), info.get("human", 0)
                else:
                    t, h = info, 0
                b = t - h
                pct = f"{(b / t * 100):.0f}%" if t > 0 else "\u2014"
                pct_color = "#EF4444" if t > 0 and b / t > 0.8 else "#22C55E"
                version_rows_data.append(
                    [
                        ver,
                        f"{t:,}",
                        ft.Text(f"{h:,}", color="#22C55E", size=12),
                        ft.Text(f"{b:,}", color="#EF4444", size=12),
                        ft.Text(
                            pct, color=pct_color, size=12, weight=ft.FontWeight.W_600
                        ),
                    ]
                )

            # Totals row
            total_t = sum(
                info.get("total", 0) if isinstance(info, dict) else info
                for info in versions.values()
            )
            total_h = sum(
                info.get("human", 0) if isinstance(info, dict) else 0
                for info in versions.values()
            )
            total_b = total_t - total_h
            total_pct = f"{(total_b / total_t * 100):.0f}%" if total_t > 0 else "\u2014"

            version_rows_data.append(
                [
                    ft.Text("TOTAL", size=12, weight=ft.FontWeight.W_700),
                    ft.Text(f"{total_t:,}", size=12, weight=ft.FontWeight.W_700),
                    ft.Text(
                        f"{total_h:,}",
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color="#22C55E",
                    ),
                    ft.Text(
                        f"{total_b:,}",
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color="#EF4444",
                    ),
                    ft.Text(
                        total_pct,
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color="#EF4444"
                        if total_t > 0 and total_b / total_t > 0.8
                        else "#22C55E",
                    ),
                ]
            )

            version_table = DataTable(
                columns=version_columns,
                rows=version_rows_data,
            )

            # Daily downloads table (sorted by highest day)
            daily_columns = [
                DataTableColumn(header="Date", width=80, style="primary"),
                DataTableColumn(header="Total", width=70, alignment="right"),
                DataTableColumn(header="Human", width=70, alignment="right"),
                DataTableColumn(header="Bot", width=70, alignment="right"),
            ]

            sorted_days = sorted(daily, key=lambda d: d["date"], reverse=True)
            daily_rows_data = []
            for d in sorted_days:
                bot = d["total"] - d["human"]
                daily_rows_data.append(
                    [
                        d["date"][-5:],
                        f"{d['total']:,}",
                        ft.Text(f"{d['human']:,}", color="#22C55E", size=12),
                        ft.Text(f"{bot:,}", color="#EF4444", size=12),
                    ]
                )

            daily_table = DataTable(
                columns=daily_columns,
                rows=daily_rows_data,
                scroll_height=400,
            )

            content.extend(
                [
                    ft.Container(height=12),
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    H3Text(f"Downloads by Version ({range_label})"),
                                    version_table,
                                ],
                                expand=True,
                            ),
                            ft.Column(
                                [
                                    H3Text(f"Daily Downloads ({range_label})"),
                                    daily_table,
                                ],
                                expand=True,
                            ),
                        ],
                        spacing=Theme.Spacing.LG,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ]
            )

        self._content_column.controls = content

    def _load_data(self, days: int = 14) -> dict:
        """Load PyPI data from bulk pre-loaded data."""
        from app.services.insights.query_service import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

        # Total
        total_row = self._bulk.latest.get("downloads_total")
        total = int(total_row.value) if total_row else 0

        # Daily total + human
        daily_rows = [
            r for r in self._bulk.daily.get("downloads_daily", []) if r.date >= cutoff
        ]
        human_rows = [
            r
            for r in self._bulk.daily.get("downloads_daily_human", [])
            if r.date >= cutoff
        ]
        human_map = {str(r.date)[:10]: int(r.value) for r in human_rows}

        daily = []
        for r in daily_rows:
            day = str(r.date)[:10]
            t = int(r.value)
            h = human_map.get(day, 0)
            daily.append({"date": day, "total": t, "human": h})

        today_total = daily[-1]["total"] if daily else 0
        today_human = daily[-1]["human"] if daily else 0

        # Bot % computed over entire selected range
        range_total = sum(d["total"] for d in daily)
        range_human = sum(d["human"] for d in daily)
        bot_pct = (
            ((range_total - range_human) / range_total * 100) if range_total > 0 else 0
        )

        # Latest installer breakdown (aggregate from all days)
        all_installers: dict[str, int] = {}
        for r in [
            r
            for r in self._bulk.daily.get("downloads_by_installer", [])
            if r.date >= cutoff
        ]:
            meta = r.metadata_ or {}
            for name, count in meta.get("installers", {}).items():
                all_installers[name] = all_installers.get(name, 0) + count
        installers = dict(sorted(all_installers.items(), key=lambda x: -x[1]))

        # Latest country breakdown (aggregate)
        all_countries: dict[str, int] = {}
        for r in [
            r
            for r in self._bulk.daily.get("downloads_by_country", [])
            if r.date >= cutoff
        ]:
            meta = r.metadata_ or {}
            for code, count in meta.get("countries", {}).items():
                all_countries[code] = all_countries.get(code, 0) + count
        countries = dict(sorted(all_countries.items(), key=lambda x: -x[1]))

        # Per-day per-version data
        version_daily_rows = [
            r
            for r in self._bulk.daily.get("downloads_by_version", [])
            if r.date >= cutoff
        ]
        version_daily: dict[str, dict[str, int]] = {}
        for r in version_daily_rows:
            day = str(r.date)[:10]
            meta = r.metadata_ or {}
            day_versions = meta.get("versions", {})
            version_daily[day] = {}
            for ver, info in day_versions.items():
                if isinstance(info, dict):
                    version_daily[day][ver] = info.get("total", 0)
                else:
                    version_daily[day][ver] = info

        # Version breakdown with real human/bot
        versions: dict[str, dict[str, int]] = {}
        for r in version_daily_rows:
            meta = r.metadata_ or {}
            for ver, info in meta.get("versions", {}).items():
                if ver not in versions:
                    versions[ver] = {"total": 0, "human": 0}
                if isinstance(info, dict):
                    versions[ver]["total"] += info.get("total", 0)
                    versions[ver]["human"] += info.get("human", 0)
                else:
                    versions[ver]["total"] += info
        versions = dict(sorted(versions.items(), key=lambda x: -x[1]["total"]))

        # Distribution type breakdown
        all_types: dict[str, int] = {}
        for r in [
            r for r in self._bulk.daily.get("downloads_by_type", []) if r.date >= cutoff
        ]:
            meta = r.metadata_ or {}
            for t, count in meta.get("types", {}).items():
                all_types[t] = all_types.get(t, 0) + count
        dist_types = dict(sorted(all_types.items(), key=lambda x: -x[1]))

        # Events for chart annotations
        all_events: list[tuple[str, str, str]] = []
        for r in self._bulk.events.get("releases", []):
            tag = (r.metadata_ or {}).get("tag", "")
            if tag:
                all_events.append((str(r.date)[:10], tag, "release"))
        for ev in [
            ev for ev in self._bulk.insight_events if ev.event_type in PYPI_EVENT_TYPES
        ]:
            all_events.append((str(ev.date)[:10], ev.description[:60], ev.event_type))

        release_map: dict[str, str] = {}
        for date, label, _ in all_events:
            if date in release_map:
                release_map[date] += f"\n{label}"
            else:
                release_map[date] = label

        return {
            "total": total,
            "today_total": today_total,
            "today_human": today_human,
            "bot_percent": bot_pct,
            "prev_total": sum(
                int(r.value)
                for r in self._bulk.daily.get("downloads_daily", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_human": sum(
                int(r.value)
                for r in self._bulk.daily.get("downloads_daily_human", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "daily": daily,
            "version_daily": version_daily,
            "installers": installers,
            "countries": countries,
            "versions": versions,
            "types": dist_types,
            "releases": release_map,
            "all_events": all_events,
        }


# ---------------------------------------------------------------------------
# Tab 5: Docs (Plausible)
# ---------------------------------------------------------------------------


class DocsTab(InsightsTab):
    """Docs analytics from Plausible with date range and event annotations."""

    _default_days = 7

    def _build_content(self) -> None:
        """Build or rebuild all content."""
        data = self._data
        daily = data["daily"]

        last_collected = data.get("last_collected", "")
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_collected),
            ft.Container(height=8),
        ]

        if not daily:
            content.append(
                SecondaryText(
                    "No Plausible data collected yet. Run: my-app insights collect plausible"  # noqa: E501
                )
            )
            self._content_column.controls = content
            return

        # Aggregates over range
        total_visitors = sum(d["visitors"] for d in daily)
        total_pageviews = sum(d["pageviews"] for d in daily)
        num_days = len(daily)
        avg_bounce = sum(d["bounce_rate"] for d in daily) / num_days if num_days else 0
        avg_duration = (
            sum(d["avg_duration"] for d in daily) / num_days if num_days else 0
        )
        views_per_visit = total_pageviews / total_visitors if total_visitors else 0
        duration_min = int(avg_duration // 60)
        duration_sec = int(avg_duration % 60)

        # Period-over-period change
        prev_v = data.get("prev_visitors", 0)
        prev_pv = data.get("prev_pageviews", 0)
        prev_b = data.get("prev_bounce", 0)
        prev_d = data.get("prev_duration", 0)

        # Metric cards with change arrows
        content.append(
            ft.Row(
                [
                    MetricCard(
                        "Visitors",
                        f"{total_visitors:,}",
                        ChartColors.TEAL,
                        change_pct=_pct(total_visitors, prev_v),
                    ),
                    MetricCard(
                        "Pageviews",
                        f"{total_pageviews:,}",
                        ChartColors.INDIGO,
                        change_pct=_pct(total_pageviews, prev_pv),
                    ),
                    MetricCard(
                        "Views/Visit", f"{views_per_visit:.1f}", Theme.Colors.SUCCESS
                    ),
                    MetricCard(
                        "Bounce Rate",
                        f"{avg_bounce:.0f}%",
                        Theme.Colors.WARNING if avg_bounce > 50 else Theme.Colors.INFO,
                        change_pct=_pct(avg_bounce, prev_b),
                        invert=True,
                    ),
                    MetricCard(
                        "Avg Duration",
                        f"{duration_min}m {duration_sec}s",
                        "#A855F7",
                        change_pct=_pct(avg_duration, prev_d),
                    ),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Insight cards: Most Read, Most Visited, Top Country
        top_pages = data.get("top_pages", [])
        countries = data.get("countries", [])
        insight_cards: list[ft.Control] = []

        if top_pages:

            def _page_title(url: str) -> str:
                parts = [p for p in url.strip("/").split("/") if p]
                return parts[-1].replace("-", " ").title() if parts else "Home"

            content_pages = [
                p for p in top_pages if len(p["url"].strip("/").split("/")) >= 2
            ]
            read_pages = [p for p in content_pages if (p.get("time_s") or 0) > 0]
            by_visitors = sorted(content_pages, key=lambda x: -x["visitors"])

            # Card 1: Most Read (highest time_s)
            if read_pages:
                mr = read_pages[0]
                mr_time = mr.get("time_s") or 0
                mr_min = int(mr_time // 60)
                mr_sec = int(mr_time % 60)
                insight_cards.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                SecondaryText("Most Read"),
                                ft.Text(
                                    _page_title(mr["url"]),
                                    size=24,
                                    weight=ft.FontWeight.W_600,
                                ),
                                SecondaryText(
                                    f"{mr_min}m {mr_sec}s read time",
                                    size=Theme.Typography.BODY_SMALL,
                                ),
                            ],
                            spacing=Theme.Spacing.XS,
                        ),
                        padding=Theme.Spacing.MD,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_radius=Theme.Components.CARD_RADIUS,
                        border=ft.border.all(0.5, ft.Colors.OUTLINE),
                        expand=True,
                        tooltip=mr["url"],
                    )
                )

            # Card 2: Most Visited (highest visitors, if different from Most Read)
            most_read_url = read_pages[0]["url"] if read_pages else ""
            if by_visitors and by_visitors[0]["url"] != most_read_url:
                tv = by_visitors[0]
                insight_cards.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                SecondaryText("Most Visited"),
                                ft.Text(
                                    _page_title(tv["url"]),
                                    size=24,
                                    weight=ft.FontWeight.W_600,
                                ),
                                SecondaryText(
                                    f"{tv['visitors']} visitors",
                                    size=Theme.Typography.BODY_SMALL,
                                ),
                            ],
                            spacing=Theme.Spacing.XS,
                        ),
                        padding=Theme.Spacing.MD,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_radius=Theme.Components.CARD_RADIUS,
                        border=ft.border.all(0.5, ft.Colors.OUTLINE),
                        expand=True,
                        tooltip=tv["url"],
                    )
                )

        # Card 3: Top Country
        if countries:
            top_country = countries[0]
            insight_cards.append(
                ft.Container(
                    content=ft.Column(
                        [
                            SecondaryText("Top Country"),
                            ft.Text(
                                COUNTRY_NAMES.get(
                                    top_country["country"], top_country["country"]
                                ),
                                size=24,
                                weight=ft.FontWeight.W_600,
                            ),
                            SecondaryText(
                                f"{top_country['visitors']} visitors",
                                size=Theme.Typography.BODY_SMALL,
                            ),
                        ],
                        spacing=Theme.Spacing.XS,
                    ),
                    padding=Theme.Spacing.MD,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=Theme.Components.CARD_RADIUS,
                    border=ft.border.all(0.5, ft.Colors.OUTLINE),
                    expand=True,
                )
            )

        # Card 4: Top 3 Countries
        if len(countries) >= 2:
            country_items: list[ft.Control] = []
            for i, c in enumerate(countries[:3], 1):
                country_items.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                SecondaryText(
                                    f"#{i}", size=Theme.Typography.BODY_SMALL
                                ),
                                BodyText(
                                    COUNTRY_NAMES.get(c["country"], c["country"]),
                                    size=Theme.Typography.BODY_SMALL,
                                ),
                                ft.Container(expand=True),
                                SecondaryText(
                                    f"{c['visitors']}", size=Theme.Typography.BODY_SMALL
                                ),
                            ],
                            spacing=4,
                        ),
                    )
                )
            insight_cards.append(
                ft.Container(
                    content=ft.Column(
                        [
                            SecondaryText("Top Countries"),
                            *country_items,
                        ],
                        spacing=Theme.Spacing.XS,
                    ),
                    padding=Theme.Spacing.MD,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=Theme.Components.CARD_RADIUS,
                    border=ft.border.all(0.5, ft.Colors.OUTLINE),
                    expand=True,
                )
            )

        if insight_cards:
            content.append(ft.Container(height=8))
            content.append(ft.Row(insight_cards, spacing=Theme.Spacing.MD))

        # Date range
        date_range = (
            f"{_pretty_date(daily[0]['date'])} \u2014 {_pretty_date(daily[-1]['date'])}"
        )
        content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

        # Event chips — only on days with visitor activity
        active_dates = {d["date"] for d in daily}
        chips = self._render_event_chips(
            data.get("all_events", []), valid_dates=active_dates
        )
        if chips:
            content.append(chips)

        content.append(ft.Container(height=4))

        # Visitors + Pageviews chart
        highlighted = self._highlighted_dates
        releases_map = {
            day: label
            for day, label in (data.get("releases", {})).items()
            if day in active_dates
        }

        max_val = max(
            max(d["pageviews"] for d in daily), max(d["visitors"] for d in daily)
        )
        step = _smart_step(max_val)
        max_y = int((max_val // step + 1) * step)

        visitor_points: list[ft.LineChartDataPoint] = []
        pageview_points: list[ft.LineChartDataPoint] = []
        release_anno: list[ft.LineChartDataPoint] = []

        for i, d in enumerate(daily):
            is_hl = d["date"] in highlighted
            hl_point = ChartPoint.highlight() if is_hl else None

            visitor_points.append(
                ft.LineChartDataPoint(
                    i,
                    d["visitors"],
                    tooltip=f"Visitors: {d['visitors']}",
                    point=hl_point,
                )
            )
            pageview_points.append(
                ft.LineChartDataPoint(
                    i,
                    d["pageviews"],
                    tooltip=f"Pageviews: {d['pageviews']}",
                )
            )

            rel = releases_map.get(d["date"])
            if rel:
                release_anno.append(
                    ft.LineChartDataPoint(i, 0, tooltip=rel, show_tooltip=True)
                )
            else:
                release_anno.append(ft.LineChartDataPoint(i, 0, show_tooltip=False))

        # Match the aegis-pulse Docs panel: Visitors as the filled
        # primary series (teal), Pageviews as a line on top (indigo).
        # Same visual grammar as the GitHub Clones+Unique chart and the
        # PyPI Total+Human chart, so all three "primary + companion"
        # series read the same way across the modal.
        chart_series = [
            ft.LineChartData(
                data_points=visitor_points,
                stroke_width=2,
                color=ChartColors.TEAL,
                curved=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.15, ChartColors.TEAL),
                stroke_cap_round=True,
            ),
            ft.LineChartData(
                data_points=pageview_points,
                stroke_width=2,
                color=ChartColors.INDIGO,
                curved=True,
                stroke_cap_round=True,
            ),
        ]
        if any(p.show_tooltip for p in release_anno):
            chart_series.append(
                ft.LineChartData(
                    data_points=release_anno,
                    stroke_width=0,
                    color="#9CA3AF",
                )
            )

        chart = _make_line_chart(chart_series, max_y, daily, step)
        content.append(ft.Container(content=chart, margin=ft.margin.only(right=20)))
        content.append(
            _make_legend(
                [
                    (ChartColors.TEAL, "Visitors"),
                    (ChartColors.INDIGO, "Pageviews"),
                ]
            )
        )

        # Top Pages table - six-column `DataTable` matching the pulse
        # PAGE / VISITORS / PAGEVIEWS / BOUNCE / TIME / SCROLL layout.
        # Title sits in the first column header (same convention as the
        # bottom Top Countries / Top Sources cards), so the whole card
        # reads as one unit.
        top_pages = data.get("top_pages", [])
        if top_pages:

            def _format_duration(seconds: float) -> str:
                d_min = int(seconds // 60)
                d_sec = int(seconds % 60)
                return f"{d_min}m {d_sec}s" if d_min else f"{d_sec}s"

            def _format_pct(value: float | None) -> str:
                return "-" if value is None else f"{value:.1f}%"

            def _page_link(url: str) -> ft.Container:
                full_url = f"https://lbedner.github.io{url}"
                return ft.Container(
                    content=ft.Text(
                        url,
                        size=Theme.Typography.BODY,
                        style=ft.TextStyle(
                            color=Theme.Colors.INFO,
                            decoration=ft.TextDecoration.UNDERLINE,
                        ),
                        selectable=False,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    on_click=lambda e, u=full_url: e.page.launch_url(u),
                    ink=True,
                    expand=True,
                )

            pages_columns = [
                DataTableColumn("TOP PAGES", style="primary"),
                DataTableColumn("VISITORS", width=80, alignment="right", style="body"),
                DataTableColumn(
                    "PAGEVIEWS", width=90, alignment="right", style="secondary"
                ),
                DataTableColumn(
                    "BOUNCE", width=70, alignment="right", style="secondary"
                ),
                DataTableColumn("TIME", width=70, alignment="right", style="secondary"),
                DataTableColumn(
                    "SCROLL", width=70, alignment="right", style="secondary"
                ),
            ]
            pages_rows = [
                [
                    _page_link(p["url"]),
                    f"{p['visitors']:,}",
                    f"{p['pageviews']:,}",
                    _format_pct(p.get("bounce_rate")),
                    _format_duration(p.get("time_s") or 0),
                    _format_pct(p.get("scroll")),
                ]
                for p in top_pages
            ]

            content.append(ft.Container(height=12))
            content.append(
                DataTable(
                    columns=pages_columns,
                    rows=pages_rows,
                    empty_message="No page data available.",
                )
            )

        # Top Countries + Top Sources - two side-by-side `DataTable`s.
        # Title lives in the table header (first column) rather than as
        # a separate `H3Text`, so the card reads as one unit instead of
        # a heading + table stack. Sits at the bottom because it's the
        # long-tail "where is the traffic actually coming from?" view;
        # metrics + chart answer the headline question first.
        top_sources = data.get("top_sources", [])
        if countries or top_sources:
            countries_table = DataTable(
                columns=[
                    DataTableColumn("TOP COUNTRIES", style="primary"),
                    DataTableColumn("", width=80, alignment="right", style="body"),
                ],
                rows=[
                    [
                        COUNTRY_NAMES.get(c["country"], c["country"]),
                        f"{c['visitors']:,}",
                    ]
                    for c in countries[:7]
                ],
                empty_message="No country data available.",
            )
            sources_table = DataTable(
                columns=[
                    DataTableColumn("TOP SOURCES", style="primary"),
                    DataTableColumn("", width=80, alignment="right", style="body"),
                ],
                rows=[[s["source"], f"{s['visitors']:,}"] for s in top_sources[:7]],
                empty_message="No source data available.",
            )

            content.append(ft.Container(height=8))
            content.append(
                ft.Row(
                    [
                        ft.Container(content=countries_table, expand=1),
                        ft.Container(content=sources_table, expand=1),
                    ],
                    spacing=Theme.Spacing.LG,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )

        self._content_column.controls = content

    def _load_data(self, days: int = 30) -> dict[str, Any]:
        """Load Plausible data from bulk pre-loaded data."""
        from app.services.insights.query_service import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

        # Daily metrics - current period
        visitors_rows = [
            r for r in self._bulk.daily.get("visitors", []) if r.date >= cutoff
        ]
        pageviews_rows = [
            r for r in self._bulk.daily.get("pageviews", []) if r.date >= cutoff
        ]
        duration_rows = [
            r for r in self._bulk.daily.get("avg_duration", []) if r.date >= cutoff
        ]
        bounce_rows = [
            r for r in self._bulk.daily.get("bounce_rate", []) if r.date >= cutoff
        ]

        # Previous period totals for comparison
        prev_visitors = sum(
            int(r.value)
            for r in self._bulk.daily.get("visitors", [])
            if prev_cutoff <= r.date < cutoff
        )
        prev_pageviews = sum(
            int(r.value)
            for r in self._bulk.daily.get("pageviews", [])
            if prev_cutoff <= r.date < cutoff
        )
        prev_dur_rows = [
            r
            for r in self._bulk.daily.get("avg_duration", [])
            if prev_cutoff <= r.date < cutoff
        ]
        prev_duration = (
            sum(float(r.value) for r in prev_dur_rows) / len(prev_dur_rows)
            if prev_dur_rows
            else 0
        )
        prev_bounce_rows = [
            r
            for r in self._bulk.daily.get("bounce_rate", [])
            if prev_cutoff <= r.date < cutoff
        ]
        prev_bounce = (
            sum(float(r.value) for r in prev_bounce_rows) / len(prev_bounce_rows)
            if prev_bounce_rows
            else 0
        )

        pv_map = {str(r.date)[:10]: int(r.value) for r in pageviews_rows}
        dur_map = {str(r.date)[:10]: float(r.value) for r in duration_rows}
        bounce_map = {str(r.date)[:10]: float(r.value) for r in bounce_rows}

        daily: list[dict[str, Any]] = []
        last_collected = ""
        for r in visitors_rows:
            day = str(r.date)[:10]
            visitors = int(r.value)
            pageviews = pv_map.get(day, 0)
            # Skip days with no activity to avoid dead space on chart
            if visitors == 0 and pageviews == 0:
                continue
            last_collected = day
            daily.append(
                {
                    "date": day,
                    "visitors": visitors,
                    "pageviews": pageviews,
                    "avg_duration": dur_map.get(day, 0),
                    "bounce_rate": bounce_map.get(day, 0),
                }
            )

        # Top pages - aggregate per-day snapshots across selected range.
        # `visitors` and `pageviews` are sums; `time_s`, `bounce_rate`,
        # `scroll` are visitor-weighted averages (so a page with 100
        # visitors at 30s and 1 visitor at 300s reports the right
        # average, not (30+300)/2). Sorted by visitors desc to match
        # the header sort indicator on the pulse layout.
        all_pages: dict[str, dict[str, Any]] = {}
        for r in [r for r in self._bulk.daily.get("top_pages", []) if r.date >= cutoff]:
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            for p in meta.get("pages", []):
                url = p.get("url", "")
                if not url:
                    continue
                accum = all_pages.setdefault(
                    url,
                    {
                        "url": url,
                        "visitors": 0,
                        "pageviews": 0,
                        "_time_weighted": 0.0,
                        "_time_weight": 0,
                        "_bounce_weighted": 0.0,
                        "_bounce_weight": 0,
                        "_scroll_weighted": 0.0,
                        "_scroll_weight": 0,
                    },
                )
                visitors = p.get("visitors", 0) or 0
                accum["visitors"] += visitors
                accum["pageviews"] += p.get("pageviews", 0) or 0

                if visitors > 0:
                    if p.get("time_s") is not None:
                        accum["_time_weighted"] += float(p["time_s"]) * visitors
                        accum["_time_weight"] += visitors
                    if p.get("bounce_rate") is not None:
                        accum["_bounce_weighted"] += float(p["bounce_rate"]) * visitors
                        accum["_bounce_weight"] += visitors
                    if p.get("scroll") is not None:
                        accum["_scroll_weighted"] += float(p["scroll"]) * visitors
                        accum["_scroll_weight"] += visitors

        top_pages: list[dict[str, Any]] = []
        for accum in all_pages.values():
            tw = accum.pop("_time_weighted")
            twn = accum.pop("_time_weight")
            bw = accum.pop("_bounce_weighted")
            bwn = accum.pop("_bounce_weight")
            sw = accum.pop("_scroll_weighted")
            swn = accum.pop("_scroll_weight")
            accum["time_s"] = tw / twn if twn else 0.0
            accum["bounce_rate"] = bw / bwn if bwn else None
            accum["scroll"] = sw / swn if swn else None
            top_pages.append(accum)
        top_pages.sort(key=lambda x: -x["visitors"])
        top_pages = top_pages[:20]

        # Countries - aggregate per-day snapshots across selected range
        all_countries: dict[str, int] = {}
        for r in [
            r for r in self._bulk.daily.get("top_countries", []) if r.date >= cutoff
        ]:
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            for c in meta.get("countries", []):
                code = c.get("country", "")
                all_countries[code] = all_countries.get(code, 0) + c.get("visitors", 0)
        countries = [
            {"country": code, "visitors": count}
            for code, count in sorted(all_countries.items(), key=lambda x: -x[1])
        ][:20]

        # Sources - aggregate per-day snapshots across selected range.
        # Source labels come from the Plausible referrer breakdown
        # ("Direct / None", "GitHub", "Reddit", ...) - pre-formatted.
        all_sources: dict[str, int] = {}
        for r in [
            r for r in self._bulk.daily.get("top_sources", []) if r.date >= cutoff
        ]:
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            for s in meta.get("sources", []):
                name = s.get("source", "") or "Direct / None"
                all_sources[name] = all_sources.get(name, 0) + s.get("visitors", 0)
        top_sources = [
            {"source": name, "visitors": count}
            for name, count in sorted(all_sources.items(), key=lambda x: -x[1])
        ][:20]

        # Events
        all_events: list[tuple[str, str, str]] = []
        for r in self._bulk.events.get("releases", []):
            tag = (r.metadata_ or {}).get("tag", "")
            if tag:
                all_events.append((str(r.date)[:10], tag, "release"))
        cutoff_str = str(cutoff.date())
        for ev in [
            ev
            for ev in self._bulk.insight_events
            if str(ev.date)[:10] >= cutoff_str and ev.event_type in DOCS_EVENT_TYPES
        ]:
            all_events.append((str(ev.date)[:10], ev.description[:60], ev.event_type))

        release_map: dict[str, str] = {}
        for date, label, _ in all_events:
            if date in release_map:
                release_map[date] += f"\n{label}"
            else:
                release_map[date] = label

        all_events.sort(key=lambda x: x[0])

        return {
            "daily": daily,
            "top_pages": top_pages,
            "countries": countries,
            "top_sources": top_sources,
            "all_events": all_events,
            "releases": release_map,
            "prev_visitors": prev_visitors,
            "prev_pageviews": prev_pageviews,
            "prev_bounce": prev_bounce,
            "prev_duration": prev_duration,
            "last_collected": last_collected,
        }


# ---------------------------------------------------------------------------
# Tab 6: Reddit
# ---------------------------------------------------------------------------


class RedditTab(ft.Container):
    """Reddit: tracked post stats from database."""

    def __init__(self, bulk: BulkInsightsResponse | None = None) -> None:
        super().__init__()
        self._bulk = bulk

        posts = self._load_posts()

        if not posts:
            self.content = ft.Column(
                [
                    SecondaryText(
                        "No Reddit posts tracked. Use: my-app insights reddit add <url>"
                    )
                ],
                scroll=ft.ScrollMode.AUTO,
            )
            self.padding = Theme.Spacing.MD
            self.expand = True
            return

        last_date = posts[0]["date"] if posts else ""
        content: list[ft.Control] = [
            SecondaryText(
                f"Last updated: {last_date}" if last_date else "",
                size=Theme.Typography.BODY_SMALL,
            ),
            ft.Container(height=4),
        ]

        for post in posts:
            meta = post.get("metadata", {})
            subreddit = meta.get("subreddit", "")
            title = meta.get("title", "")
            comments = meta.get("comments", 0)
            upvote_ratio = meta.get("upvote_ratio", 0)
            url = meta.get("url", "")
            upvotes = post.get("upvotes", 0)
            date = post.get("date", "")

            # Post card — compact layout
            post_card = ft.Container(
                content=ft.Column(
                    [
                        # Row 1: subreddit + date + stats
                        ft.Row(
                            [
                                ft.Container(
                                    content=LabelText(
                                        f"r/{subreddit}", color=Theme.Colors.BADGE_TEXT
                                    ),
                                    bgcolor="#FF5722",
                                    padding=ft.padding.symmetric(
                                        horizontal=6, vertical=2
                                    ),
                                    border_radius=4,
                                ),
                                SecondaryText(
                                    _pretty_date(date), size=Theme.Typography.BODY_SMALL
                                ),
                                ft.Container(expand=True),
                                ft.Text(
                                    f"{upvotes:,}",
                                    size=13,
                                    weight=ft.FontWeight.W_700,
                                    color="#FF5722",
                                ),
                                SecondaryText("upvotes", size=Theme.Typography.CAPTION),
                                ft.Container(width=8),
                                ft.Text(
                                    str(comments),
                                    size=13,
                                    weight=ft.FontWeight.W_700,
                                    color=Theme.Colors.INFO,
                                ),
                                SecondaryText(
                                    "comments", size=Theme.Typography.CAPTION
                                ),
                                ft.Container(width=8),
                                ft.Text(
                                    f"{upvote_ratio:.0%}",
                                    size=13,
                                    weight=ft.FontWeight.W_700,
                                    color=Theme.Colors.SUCCESS
                                    if upvote_ratio and upvote_ratio > 0.9
                                    else Theme.Colors.WARNING,
                                ),
                            ],
                            spacing=4,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        # Row 2: title as hyperlink
                        ft.Text(
                            spans=[
                                ft.TextSpan(
                                    title,
                                    style=ft.TextStyle(
                                        size=13,
                                        decoration=ft.TextDecoration.UNDERLINE,
                                        color=Theme.Colors.PRIMARY,
                                    ),
                                    url=url,
                                ),
                            ],
                        )
                        if url
                        else BodyText(title),
                    ],
                    spacing=6,
                ),
                padding=ft.padding.all(10),
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
            )

            content.append(post_card)

        self.content = ft.Column(
            content,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = Theme.Spacing.MD
        self.expand = True

    def _load_posts(self) -> list[dict]:
        """Load Reddit posts from bulk pre-loaded data."""
        rows = self._bulk.events.get("post_stats", [])
        if not rows:
            return []

        # Get original post dates from events
        event_dates: dict[str, str] = {}
        for ev in [
            ev for ev in self._bulk.insight_events if ev.event_type in {"reddit_post"}
        ]:
            pid = (ev.metadata_ or {}).get("post_id", "")
            if pid and pid not in event_dates:
                event_dates[pid] = str(ev.date)[:10]

        # Group by post_id, take latest snapshot per post
        seen: set[str] = set()
        posts = []
        for r in rows:
            meta = r.metadata_ or {}
            post_id = meta.get("post_id", "")
            if post_id in seen:
                continue
            seen.add(post_id)
            original_date = event_dates.get(post_id, str(r.date)[:10])
            posts.append(
                {
                    "upvotes": int(r.value),
                    "date": original_date,
                    "metadata": meta,
                }
            )

        return posts


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------


def _group_events(
    events: list[tuple[str, str, str]],
    days: int,
) -> list[tuple[str, str, str, set[str]]]:
    """Group same-type events by time bucket for cleaner display.

    Returns list of (display_date, label, type, dates_set).
    At small ranges (<=30d), no grouping — each event gets its own chip.
    """
    from datetime import datetime as dt  # noqa: I001
    import re

    # Always return with dates_set for consistent interface
    if days <= 30 or not events:
        return [(date, label, etype, {date}) for date, label, etype in events]

    # Determine bucket size
    if days <= 90:

        def bucket_key(date_str: str) -> str:
            d = dt.strptime(date_str, "%Y-%m-%d")
            # ISO week: YYYY-WNN
            return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    else:

        def bucket_key(date_str: str) -> str:
            return date_str[:7]  # YYYY-MM

    # Group by (bucket, type)
    buckets: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for date, label, etype in events:
        key = (bucket_key(date), etype)
        buckets.setdefault(key, []).append((date, label))

    result: list[tuple[str, str, str, set[str]]] = []
    for (_, etype), items in buckets.items():
        dates = {d for d, _ in items}
        first_date = min(dates)

        if len(items) == 1:
            result.append((items[0][0], items[0][1], etype, dates))
            continue

        if etype == "release":
            tags = [lbl for _, lbl in sorted(items)]
            label = f"{tags[0]}\u2013{tags[-1]}" if len(tags) > 1 else tags[0]
        elif etype == "star":
            # Extract star numbers from labels like "⭐ #80-#85 (6 stars)" or "⭐ #99 — user"  # noqa: E501
            nums: list[int] = []
            for _, lbl in items:
                for m in re.findall(r"#(\d+)", lbl):
                    nums.append(int(m))
            if nums:
                label = f"\u2b50 #{min(nums)}-#{max(nums)} ({len(items)} events)"
            else:
                label = f"\u2b50 ({len(items)} stars)"
        elif etype == "reddit_post":
            # Keep individual reddit posts — don't group
            for date, lbl in items:
                result.append((date, lbl, etype, {date}))
            continue
        else:
            label = f"{etype} ({len(items)})"

        result.append((first_date, label, etype, dates))

    result.sort(key=lambda x: x[0])
    return result


def _extract_max_number(text: str) -> str:
    """Extract the largest number from a text string (e.g., '5,292 clones' -> '5,292')."""  # noqa: E501
    import re

    numbers = re.findall(r"\d[\d,]*", text)
    if not numbers:
        return ""
    return max(numbers, key=lambda n: int(n.replace(",", "")))


def _smart_step(max_val: float) -> int:
    """Pick a nice y-axis interval based on magnitude."""
    if max_val <= 20:
        return 5
    if max_val <= 100:
        return 10
    if max_val <= 500:
        return 50
    return 100


def _pretty_date(date_str: str) -> str:
    """Format '2026-04-03' as 'April 3rd, 2026'."""
    from datetime import datetime as dt

    try:
        d = dt.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str

    day = d.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return d.strftime(f"%B {day}{suffix}, %Y")


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


class InsightsDetailDialog(BaseDetailPopup):
    """Insights service detail modal with tabbed interface."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        self._metadata: dict[str, Any] = component_data.metadata or {}
        self._tabs_container = ft.Container(
            content=ft.Column(
                [ft.ProgressBar()],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                expand=True,
            ),
            padding=ft.padding.symmetric(horizontal=60),
            expand=True,
        )

        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_insights"),
            subtitle_text=get_component_subtitle(
                "service_insights", metadata=self._metadata
            ),
            sections=[self._tabs_container],
            scrollable=False,
            status_detail=get_status_detail(component_data),
            width=1500,
            height=850,
        )

    def did_mount(self) -> None:
        self.page.run_task(self._load_and_build)

    async def _load_and_build(self) -> None:
        """Fetch bulk data from API and build all tabs."""
        from app.components.frontend.state.session_state import get_session_state

        client = get_session_state(self.page).api_client
        raw = await client.get("/api/v1/insights/all")
        if not raw:
            self._tabs_container.content = SecondaryText(
                "Failed to load insights data."
            )
            self._tabs_container.update()
            return

        bulk = BulkInsightsResponse.model_validate(raw)
        db = _build_db_from_bulk(bulk)
        metadata = self._metadata

        tabs_list = [
            ft.Tab(text="Overview", content=OverviewTab(metadata, db, bulk)),
            ft.Tab(text="GitHub", content=GitHubTrafficTab(bulk=bulk)),
            ft.Tab(text="Stars", content=StarsTab(bulk=bulk)),
            ft.Tab(text="PyPI", content=PyPITab(bulk=bulk)),
            ft.Tab(text="Docs", content=DocsTab(bulk=bulk)),
            ft.Tab(text="Reddit", content=RedditTab(bulk=bulk)),
            ft.Tab(text="Settings", content=SettingsTab(metadata, db)),
        ]

        tabs = PulseTabs(
            selected_index=0,
            tabs=tabs_list,
            expand=True,
        )

        self._tabs_container.content = tabs
        self._tabs_container.update()
