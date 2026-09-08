"""Formatting the view builders share: percentages, dates, labels, urls."""

from __future__ import annotations

from datetime import datetime
import re

from app.core.constants import COUNTRY_NAMES

# Event type -> display color
EVENT_COLORS: dict[str, str] = {
    "release": "success",
    "star": "warning",
    "fork": "secondary",
    "reddit_post": "error",
    "feature": "info",
    "milestone_github": "accent",
    "milestone_pypi": "accent",
    "anomaly_github": "error",
    "localization": "info",
    "external": "neutral",
}

# Milestone event type -> card color
MILESTONE_COLORS: dict[str, str] = {
    "milestone_github": "success",
    "milestone_pypi": "accent",
    "milestone_plausible": "secondary",
    "feature": "info",
}


def pct(current: float, previous: float) -> int | None:
    """Period-over-period percentage change. None if no previous data."""
    if previous == 0:
        return None
    return int(((current - previous) / previous) * 100)


def extract_max_number(text: str) -> str:
    """The largest number in ``text``, commas preserved.

    e.g. '5,292 clones, 777 unique' -> '5,292'
    """
    numbers = re.findall(r"\d[\d,]*", text)
    if not numbers:
        return ""
    return max(numbers, key=lambda n: int(n.replace(",", "")))


def event_color(event_type: str) -> str:
    return EVENT_COLORS.get(event_type, "primary")


def pretty_date(dt: datetime | str) -> str:
    """'March 20, 2026'."""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    return dt.strftime("%B %d, %Y")


def short_date(dt: datetime | str) -> str:
    """'Apr 03'."""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    return dt.strftime("%b %d")


def day_str(dt: datetime | str) -> str:
    """'2026-04-10'."""
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime("%Y-%m-%d")


def country_label(code: str) -> str:
    """'US' -> the flagged country name; the raw code when unknown."""
    return COUNTRY_NAMES.get(code.upper(), code) if code else code


def page_title(url: str) -> str:
    parts = [p for p in url.strip("/").split("/") if p]
    return parts[-1].replace("-", " ").title() if parts else "Home"


def referrer_url(name: str) -> str:
    """A click-through URL for a referrer row.

    Names look like `github.com`, `google.com`, `lbedner.github.io`, or
    sometimes `com.reddit.frontpage` (mobile reverse-domain). Hostname
    shapes get a scheme; anything else is skipped so no junk hrefs ship.
    """
    if not name or "." not in name or " " in name:
        return ""
    if name.startswith("http://") or name.startswith("https://"):
        return name
    return f"https://{name}"


def page_url(site: str, path: str) -> str:
    """A docs page URL from a Plausible (site, path) pair.

    Plausible only stores the path (`/docs/cli/insights`); the site comes
    from the snapshot metadata. Empty when either piece is missing, and
    the UI falls back to plain text.
    """
    if not site or not path:
        return ""
    site = site.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"https://{site}{path}"


def semver_tuple(v: str) -> tuple[tuple[int, ...], str]:
    """'0.6.10' -> ((0, 6, 10), '') for sorting; a pre-release suffix rides along."""
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
    if not m:
        return ((0,), v)
    nums = tuple(int(x) for x in m.group(1).split("."))
    return (nums, m.group(2))
