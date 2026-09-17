"""The values every insights tab reads from.

Split out because the package split copied them into all ten modules -
four constants, forty-five lines, ten times over - two of which
nothing had read since before the split. Definitions that drift
apart are worse than a shared import, and these describe one thing: what
an event is called, what colour it takes, what a range option means.
"""

RANGE_OPTIONS = [
    ("7d", 7),
    ("14d", 14),
    ("1m", 30),
    ("3m", 90),
    ("6m", 180),
    ("1y", 365),
    ("All", 9999),
]


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
