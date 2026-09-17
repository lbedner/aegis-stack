"""The insights modal itself: the tab bar and what it holds."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft


from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.services.insights.schemas import BulkInsightsResponse
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from app.components.frontend.dashboard.modals.insights_modal.docs_tab import (
    DocsTab,
)
from app.components.frontend.dashboard.modals.insights_modal.github_traffic_tab import (
    GitHubTrafficTab,
)
from app.components.frontend.dashboard.modals.insights_modal.overview_tab import (
    OverviewTab,
)
from app.components.frontend.dashboard.modals.insights_modal.pypi_tab import (
    PyPITab,
)
from app.components.frontend.dashboard.modals.insights_modal.reddit_tab import (
    RedditTab,
)
from app.components.frontend.dashboard.modals.insights_modal.settings_tab import (
    SettingsTab,
)
from app.components.frontend.dashboard.modals.insights_modal.stars_tab import (
    StarsTab,
)


# Event type → chip border/highlight color

# Shared date range options for all tabs

# Milestone category config (for Overview trophy cards)

# Event type to status mapping (for activity feed dot colors)


def _build_db_from_bulk(bulk: BulkInsightsResponse) -> dict[str, Any]:
    """Transform bulk-loaded data into the db dict consumed by OverviewTab and SettingsTab."""  # noqa: E501
    from app.services.insights.domains.metrics import InsightQueryService

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
