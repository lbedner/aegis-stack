"""The PyPI tab: downloads, bot share, and the country / installer /
type / version breakdowns."""

from __future__ import annotations

from typing import Any

from app.services.insights.schemas import (
    BulkInsightsResponse,
    PyPICountryBreakdown,
    PyPIDownloadMetadata,
    PyPIInstallerBreakdown,
    PyPITypeBreakdown,
)
from app.services.insights.schemas.views import (
    BreakdownItem,
    DailyValuePoint,
    MetricCardView,
    PyPIView,
    VersionSeries,
)
from app.services.insights.utils import range_cutoffs
from app.services.insights.views.events import (
    PYPI_EVENT_TYPES,
    event_type_options,
    filter_events,
)
from app.services.insights.views.formatting import (
    country_label,
    day_str,
    pct,
    semver_tuple,
)


def build(bulk: BulkInsightsResponse, days: int = 14) -> PyPIView:
    cutoff, prev_cutoff = range_cutoffs(days)
    daily_dl = bulk.daily.get("downloads_daily", [])
    daily_human = bulk.daily.get("downloads_daily_human", [])

    daily_dl_in_range = [r for r in daily_dl if r.date >= cutoff]
    daily_human_in_range = [r for r in daily_human if r.date >= cutoff]
    daily_dl_prev = [r for r in daily_dl if prev_cutoff <= r.date < cutoff]
    daily_human_prev = [r for r in daily_human if prev_cutoff <= r.date < cutoff]

    days_count = len(daily_dl_in_range) or 1
    total_dl = sum(r.value for r in daily_dl_in_range)
    total_human = sum(r.value for r in daily_human_in_range)
    bot_pct = int((1 - total_human / total_dl) * 100) if total_dl > 0 else 0

    prev_days_count = len(daily_dl_prev) or 1
    prev_total_dl = sum(r.value for r in daily_dl_prev)
    prev_total_human = sum(r.value for r in daily_human_prev)
    prev_bot_pct = (
        int((1 - prev_total_human / prev_total_dl) * 100) if prev_total_dl > 0 else 0
    )

    # Country / installer / dist-type breakdowns aggregate the per-day
    # snapshots within the selected range (same pattern as versions).
    def _aggregate(key: str, schema: Any, attr: str) -> dict[str, int]:
        totals: dict[str, int] = {}
        for r in bulk.daily.get(key, []):
            if r.date < cutoff:
                continue
            meta = r.metadata_ if hasattr(r, "metadata_") else {}
            if not isinstance(meta, dict):
                continue
            try:
                parsed = schema.model_validate(meta)
            except Exception:
                continue
            for k, v in getattr(parsed, attr).items():
                totals[k] = totals.get(k, 0) + int(v)
        return totals

    country_counts = _aggregate(
        "downloads_by_country", PyPICountryBreakdown, "countries"
    )
    # ``countries`` feeds the world map, so the long tail stays; the side
    # table reads the top-10 slice, capped server-side.
    countries = sorted(
        [
            BreakdownItem(name=country_label(k), value=v, code=k)
            for k, v in country_counts.items()
        ],
        key=lambda x: -x.value,
    )[:50]
    top_countries = countries[:10]

    installer_counts = _aggregate(
        "downloads_by_installer", PyPIInstallerBreakdown, "installers"
    )
    installers = sorted(
        [BreakdownItem(name=k, value=v) for k, v in installer_counts.items()],
        key=lambda x: -x.value,
    )[:10]

    type_counts = _aggregate("downloads_by_type", PyPITypeBreakdown, "types")
    dist_types = sorted(
        [BreakdownItem(name=k, value=v) for k, v in type_counts.items()],
        key=lambda x: -x.value,
    )[:10]

    # Version breakdown across the selected range.
    versions: list[BreakdownItem] = []
    version_totals: list[BreakdownItem] = []
    version_rows = bulk.daily.get("downloads_by_version", [])
    if version_rows:
        period_totals: dict[str, int] = {}
        for r in version_rows:
            if r.date < cutoff:
                continue
            meta = r.metadata_ if hasattr(r, "metadata_") else {}
            if not isinstance(meta, dict):
                continue
            try:
                pm = PyPIDownloadMetadata.model_validate(meta)
            except Exception:
                continue
            for k, v in pm.versions.items():
                period_totals[k] = period_totals.get(k, 0) + v.total

        all_items = [BreakdownItem(name=k, value=v) for k, v in period_totals.items()]
        versions = sorted(all_items, key=lambda x: -x.value)[:10]
        # Full list in semver order for the period bar chart
        version_totals = sorted(all_items, key=lambda x: semver_tuple(x.name))

    # Per-version daily series for the secondary chart
    version_dates: list[str] = []
    version_series: list[VersionSeries] = []
    version_rows_in_range = [r for r in version_rows if r.date >= cutoff]
    if version_rows_in_range:
        version_dates = [day_str(r.date) for r in version_rows_in_range]
        totals_in_range: dict[str, int] = {}
        parsed_per_day: list[dict[str, int]] = []
        for r in version_rows_in_range:
            meta = r.metadata_ if hasattr(r, "metadata_") else {}
            day_counts: dict[str, int] = {}
            if isinstance(meta, dict):
                try:
                    pm = PyPIDownloadMetadata.model_validate(meta)
                    for k, v in pm.versions.items():
                        day_counts[k] = v.total
                        totals_in_range[k] = totals_in_range.get(k, 0) + v.total
                except Exception:
                    pass
            parsed_per_day.append(day_counts)

        # Up to 10 versions so the user can choose which to chart
        top_versions = [
            v for v, _ in sorted(totals_in_range.items(), key=lambda x: -x[1])[:10]
        ]
        for v in top_versions:
            values = [day.get(v, 0) for day in parsed_per_day]
            version_series.append(VersionSeries(version=v, values=values))

    avg_change = pct(total_dl / days_count, prev_total_dl / prev_days_count)
    metrics = [
        MetricCardView(
            label="Downloads",
            value=int(total_dl),
            change_pct=pct(total_dl, prev_total_dl),
        ),
        MetricCardView(
            label="Avg / Day", value=int(total_dl / days_count), change_pct=avg_change
        ),
        MetricCardView(
            label="Avg / Week",
            value=int(total_dl / days_count * 7),
            change_pct=avg_change,
        ),
        MetricCardView(
            label="Avg / Month",
            value=int(total_dl / days_count * 30),
            change_pct=avg_change,
        ),
        MetricCardView(
            label="Bot %",
            value=f"{bot_pct}%",
            change_pct=pct(bot_pct, prev_bot_pct),
            lower_is_better=True,
        ),
    ]

    events = filter_events(bulk, PYPI_EVENT_TYPES, cutoff=cutoff, days=days)
    return PyPIView(
        metrics=metrics,
        daily=[
            DailyValuePoint(date=day_str(r.date), value=int(r.value))
            for r in daily_dl_in_range
        ],
        daily_human=[
            DailyValuePoint(date=day_str(r.date), value=int(r.value))
            for r in daily_human_in_range
        ],
        countries=countries,
        top_countries=top_countries,
        installers=installers,
        dist_types=dist_types,
        versions=versions,
        version_totals=version_totals,
        version_series=version_series,
        version_dates=version_dates,
        events=events,
        event_types=event_type_options(events),
    )
