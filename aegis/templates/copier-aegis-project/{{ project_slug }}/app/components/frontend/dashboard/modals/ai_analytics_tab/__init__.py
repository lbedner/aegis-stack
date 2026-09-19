"""AI analytics: usage, cost, sentiment and recent calls.

Split out of one 530-line module. ``tab`` is the surface; the rest is
one section each, plus the payload shaping they share.
"""

from .activity import RecentActivitySection
from .sentiment import SENTIMENT_COLORS, SentimentSection, sentiment_chart_sections
from .shaping import _format_relative_time, _transform_api_response
from .stats import HeroStatsSection, _get_success_rate_color
from .tab import AIAnalyticsTab

__all__ = [
    "SENTIMENT_COLORS",
    "AIAnalyticsTab",
    "HeroStatsSection",
    "RecentActivitySection",
    "SentimentSection",
    "_format_relative_time",
    "_get_success_rate_color",
    "_transform_api_response",
    "sentiment_chart_sections",
]
