"""Display-ready views over one ``BulkInsightsResponse``.

One module per tab (``overview``, ``github``, ``stars``, ``pypi``,
``docs``, ``reddit``), each exposing ``build(bulk, days)``; ``events``
holds the timeline logic the tabs share and ``formatting`` the labels,
dates and urls. Both the Flet dashboard and the htmx pages consume the
same views, so a number is computed in exactly one place.

``InsightViewService`` is the facade the cache and the dashboard hold:
one method per tab, named after its URL section.
"""

from __future__ import annotations

from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import (
    DocsView,
    GitHubView,
    OverviewView,
    PyPIView,
    RedditView,
    StarsView,
)
from app.services.insights.views import docs, github, overview, pypi, reddit, stars

__all__ = ["InsightViewService"]


class InsightViewService:
    """Transforms one bulk response into the per-tab view models."""

    def __init__(self, bulk: BulkInsightsResponse) -> None:
        self._bulk = bulk

    def overview(self, days: int = 14) -> OverviewView:
        return overview.build(self._bulk, days)

    def github(self, days: int = 14) -> GitHubView:
        return github.build(self._bulk, days)

    def stars(self, days: int = 14) -> StarsView:
        return stars.build(self._bulk, days)

    def pypi(self, days: int = 14) -> PyPIView:
        return pypi.build(self._bulk, days)

    def docs(self, days: int = 14) -> DocsView:
        return docs.build(self._bulk, days)

    def reddit(self, days: int = 14) -> RedditView:
        return reddit.build(self._bulk, days)
