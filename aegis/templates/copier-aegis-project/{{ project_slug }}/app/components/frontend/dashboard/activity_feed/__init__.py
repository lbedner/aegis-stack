"""The dashboard's activity feed.

Split into what a row IS (``rows``), when several become one
(``grouping``), and the feed that assembles them (``feed``).
"""

from app.components.frontend.dashboard.activity_feed.feed import ActivityFeed
from app.components.frontend.dashboard.activity_feed.grouping import (
    EventGroup,
    group_consecutive_events,
)
from app.components.frontend.dashboard.activity_feed.rows import (
    ExpandableActivityRow,
    GroupedActivityRow,
    format_relative_time,
)

__all__ = [
    "ActivityFeed",
    "EventGroup",
    "ExpandableActivityRow",
    "GroupedActivityRow",
    "format_relative_time",
    "group_consecutive_events",
]
