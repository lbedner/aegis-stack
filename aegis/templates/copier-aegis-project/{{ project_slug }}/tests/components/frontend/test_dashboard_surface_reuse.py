"""The status table and the diagram skip a refresh that changes nothing.

The cards learned this first (see test_dashboard_card_reuse). These two
surfaces were still rebuilding wholesale on every cycle: the table
constructs a fresh ``DataTable``, and the diagram clears its canvas, its
node stack and its node map before redrawing.

Measured before this existed, with eighteen components reported twice
with identical statuses:

    status table : 231 controls,  1 survived the refresh
    diagram      : 173 controls, 11 survived

and the rendered text was identical both times. 392 control objects
discarded every thirty seconds, per connected session, to show exactly
what was already on screen.

Unlike the cards, these two are rebuilt as a whole rather than per
component, so the win here is skipping the cycle entirely when the
component set is unchanged - which in the steady state is every cycle.
"""

from __future__ import annotations

import pytest

from app.components.frontend.dashboard.diagram.diagram_view import DiagramView
from app.components.frontend.dashboard.status_overview import StatusOverviewPanel
from app.services.system.models import ComponentStatus
from tests.components.frontend._tree import texts, walk


def st(name: str, state: str = "healthy", **metadata: object) -> ComponentStatus:
    return ComponentStatus(
        name=name,
        status=state,
        message="ok",
        response_time_ms=1.0,
        metadata=dict(metadata),
    )


COMPONENTS = {
    "backend": st("backend"),
    "database": st("database", size="12 MB"),
    "redis": st("redis"),
}


def survivors(before: list[object], after: list[object]) -> int:
    return sum(1 for x in after if any(x is y for y in before))


SURFACES = [
    pytest.param(StatusOverviewPanel, id="status_table"),
    pytest.param(DiagramView, id="diagram"),
]


class TestAnUnchangedRefreshIsSkipped:
    @pytest.mark.parametrize("surface", SURFACES)
    def test_the_controls_survive(self, surface: type) -> None:
        """Identity is the property: Flet only sends a small diff when
        the objects it already knows about are still there."""
        view = surface()
        view.update_components(COMPONENTS)
        before = list(walk(view))

        view.update_components(dict(COMPONENTS))
        after = list(walk(view))

        assert survivors(before, after) == len(after), (
            f"{surface.__name__} rebuilt "
            f"{len(after) - survivors(before, after)} of {len(after)} controls "
            f"for a refresh that changed nothing"
        )

    @pytest.mark.parametrize("surface", SURFACES)
    def test_what_it_shows_is_unchanged(self, surface: type) -> None:
        """Skipping the rebuild must not skip the content."""
        view = surface()
        view.update_components(COMPONENTS)
        before = texts(view)

        view.update_components(dict(COMPONENTS))

        assert texts(view) == before


class TestAChangedRefreshStillRedraws:
    @pytest.mark.parametrize("surface", SURFACES)
    def test_a_status_flip_redraws(self, surface: type) -> None:
        """The skip is an optimisation, not a freeze. A component going
        down has to reach the screen.

        Identity rather than text, because the diagram carries status as
        node colour and its rendered strings do not move at all.
        """
        view = surface()
        view.update_components(COMPONENTS)
        before = list(walk(view))

        view.update_components(dict(COMPONENTS, redis=st("redis", "unhealthy")))

        assert survivors(before, list(walk(view))) < len(before)

    def test_the_table_shows_the_new_state_in_words(self) -> None:
        """The table does render status as text, so it must change."""
        view = StatusOverviewPanel()
        view.update_components(COMPONENTS)
        before = texts(view)

        view.update_components(dict(COMPONENTS, redis=st("redis", "unhealthy")))

        assert texts(view) != before

    @pytest.mark.parametrize("surface", SURFACES)
    def test_a_new_component_is_rendered(self, surface: type) -> None:
        view = surface()
        view.update_components(COMPONENTS)

        view.update_components(dict(COMPONENTS, worker=st("worker")))

        assert any("worker" in t.lower() for t in texts(view))

    @pytest.mark.parametrize("surface", SURFACES)
    def test_a_departed_component_leaves(self, surface: type) -> None:
        view = surface()
        view.update_components(COMPONENTS)

        remaining = {k: v for k, v in COMPONENTS.items() if k != "redis"}
        view.update_components(remaining)

        assert not any("redis" in t.lower() for t in texts(view))

    @pytest.mark.parametrize("surface", SURFACES)
    def test_metadata_alone_is_enough_to_redraw(self, surface: type) -> None:
        """A component can change without changing status; the cached
        comparison has to see the whole payload, not just the state."""
        view = surface()
        view.update_components(COMPONENTS)
        before = list(walk(view))

        view.update_components(dict(COMPONENTS, database=st("database", size="13 MB")))

        assert survivors(before, list(walk(view))) < len(before)
