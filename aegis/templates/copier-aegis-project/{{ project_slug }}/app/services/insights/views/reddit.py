"""The Reddit tab."""

from __future__ import annotations

from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import RedditPostView, RedditView
from app.services.insights.utils import range_cutoffs
from app.services.insights.views.formatting import country_label, day_str


def build(bulk: BulkInsightsResponse, days: int = 14) -> RedditView:
    """Pulls from ``insight_metric`` rows with period=EVENT for the
    post_stats metric type (the collector stores full post metadata
    there; the ``insight_events`` timeline row is a thin link-only
    pointer). The metric row's ``value`` holds the latest upvote count.

    Honors ``days`` so the post list filters in lockstep with the rest
    of the dashboard.
    """
    cutoff, _ = range_cutoffs(days)
    post_metrics = sorted(
        (m for m in bulk.events.get("post_stats", []) if m.date >= cutoff),
        key=lambda m: m.date,
        reverse=True,
    )

    posts: list[RedditPostView] = []
    for row in post_metrics[:20]:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        subreddit = meta.get("subreddit", "")
        title = meta.get("title", "")
        hourly = meta.get("hourly_views_48h") or []
        peak_hour: int | None = None
        if hourly:
            # argmax + 1 so the UI can say "Peak: hour 2" (1-indexed,
            # matching how Reddit's own analytics labels the buckets).
            peak_hour = max(range(len(hourly)), key=lambda i: hourly[i]) + 1
        # Known ISO codes get the flagged country name, the same treatment
        # the Docs tab uses; "OTHER" / empty code rows keep their raw name.
        raw_countries = meta.get("top_countries") or []
        decorated_countries = [
            {
                **c,
                "name": country_label(c["code"])
                if c.get("code") and c["code"].upper() != "OTHER"
                else c.get("name", ""),
            }
            for c in raw_countries
            if isinstance(c, dict)
        ]
        posts.append(
            RedditPostView(
                description=f"r/{subreddit} — {title[:80]}" if subreddit else title,
                title=title,
                date=day_str(row.date),
                subreddit=subreddit,
                upvotes=int(row.value) if row.value is not None else 0,
                comments=meta.get("comments", 0) or 0,
                upvote_ratio=meta.get("upvote_ratio"),
                views=meta.get("views"),
                shares=meta.get("shares"),
                url=meta.get("url", ""),
                top_countries=decorated_countries,
                hourly_views_48h=hourly,
                peak_hour=peak_hour,
                top_comments=meta.get("top_comments") or [],
            )
        )

    return RedditView(total=len(post_metrics), posts=posts)
