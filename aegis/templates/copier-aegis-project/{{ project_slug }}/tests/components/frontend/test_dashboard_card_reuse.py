"""A refresh repaints what changed, and nothing else.

The dashboard rebuilt every card every 30 seconds, per connected
session. Flet holds the control tree server-side and can only send a
small diff when the control OBJECTS survive between updates, so a board
of freshly constructed cards is transmitted as a full subtree
replacement - 32 controls per card, 18 cards, and measured identical
content on both sides of the cycle.

Object identity is therefore the property under test, not the rendered
output: a card that renders the same but is a different object still
costs a full replacement on the wire.
"""

from __future__ import annotations

from typing import Any

import flet as ft
import pytest

from app.components.frontend.main import SystemDashboard
from app.services.system.models import ComponentStatus


def status(name: str, state: str = "healthy", **metadata: Any) -> ComponentStatus:
    return ComponentStatus(
        name=name,
        status=state,
        message="ok",
        response_time_ms=1.0,
        metadata=dict(metadata),
    )


def make_card(name: str, data: ComponentStatus) -> ft.Container:
    """Stand-in for ``create_component_card``: one control per component."""
    state = getattr(data.status, "value", data.status)
    return ft.Container(content=ft.Text(f"{name}:{state}"))


class Harness:
    """A dashboard wired to a bare cards container."""

    def __init__(self) -> None:
        self.container = ft.Container(content=ft.Row(controls=[]))
        self.dashboard = SystemDashboard()
        self.dashboard._cards_container = self.container
        # Without this the update path returns before touching anything
        # and every assertion below passes for the wrong reason.
        self.dashboard._is_page_connected = lambda: True  # type: ignore[method-assign]
        self.built: list[str] = []

    def creator(self, name: str, data: ComponentStatus) -> ft.Container:
        self.built.append(name)
        return make_card(name, data)

    @property
    def cards(self) -> list[ft.Control]:
        return self.container.content.controls

    async def refresh(self, components: dict[str, ComponentStatus]) -> None:
        await self.dashboard.update_component_cards(components, self.creator)


COMPONENTS = {
    "backend": status("backend"),
    "database": status("database", size="12 MB"),
    "redis": status("redis"),
}


class TestNothingChanged:
    @pytest.mark.asyncio
    async def test_a_second_refresh_rebuilds_no_cards(self) -> None:
        """The ordinary case. A healthy board repaints forever for no
        visible difference; that is the waste this exists to remove."""
        h = Harness()
        await h.refresh(COMPONENTS)
        h.built.clear()

        await h.refresh(dict(COMPONENTS))

        assert len(h.cards) == 3, "the first refresh built nothing; test is vacuous"
        assert h.built == [], f"rebuilt {h.built} when nothing changed"

    @pytest.mark.asyncio
    async def test_the_card_objects_survive(self) -> None:
        """Identity is the point: Flet can only send a small diff when
        the objects are the same ones it already knows about."""
        h = Harness()
        await h.refresh(COMPONENTS)
        before = list(h.cards)

        await h.refresh(dict(COMPONENTS))

        assert [id(c) for c in h.cards] == [id(c) for c in before]


class TestSomethingChanged:
    @pytest.mark.asyncio
    async def test_only_the_changed_component_is_rebuilt(self) -> None:
        h = Harness()
        await h.refresh(COMPONENTS)
        h.built.clear()

        moved = dict(COMPONENTS, database=status("database", size="13 MB"))
        await h.refresh(moved)

        assert h.built == ["database"]

    @pytest.mark.asyncio
    async def test_the_untouched_cards_keep_their_identity(self) -> None:
        h = Harness()
        await h.refresh(COMPONENTS)
        keep = {name: h.cards[i] for i, name in enumerate(COMPONENTS)}

        await h.refresh(dict(COMPONENTS, redis=status("redis", state="unhealthy")))

        assert h.cards[0] is keep["backend"]
        assert h.cards[1] is keep["database"]
        assert h.cards[2] is not keep["redis"], "the changed card must be replaced"

    @pytest.mark.asyncio
    async def test_the_new_card_lands_in_the_right_slot(self) -> None:
        """Replacing in place, not appending: order is the layout."""
        h = Harness()
        await h.refresh(COMPONENTS)

        await h.refresh(dict(COMPONENTS, database=status("database", state="warning")))

        assert len(h.cards) == 3
        assert h.cards[1].content.value == "database:warning"


class TestTheComponentSetChanging:
    @pytest.mark.asyncio
    async def test_a_new_component_is_added(self) -> None:
        h = Harness()
        await h.refresh(COMPONENTS)

        await h.refresh(dict(COMPONENTS, worker=status("worker")))

        assert len(h.cards) == 4
        assert h.cards[3].content.value == "worker:healthy"

    @pytest.mark.asyncio
    async def test_a_departed_component_is_dropped(self) -> None:
        h = Harness()
        await h.refresh(COMPONENTS)

        remaining = {k: v for k, v in COMPONENTS.items() if k != "redis"}
        await h.refresh(remaining)

        assert len(h.cards) == 2
        assert all("redis" not in c.content.value for c in h.cards)

    @pytest.mark.asyncio
    async def test_a_component_that_returns_is_rebuilt(self) -> None:
        """Its cached status went with it, so it cannot be mistaken for
        unchanged when it comes back."""
        h = Harness()
        await h.refresh(COMPONENTS)
        await h.refresh({k: v for k, v in COMPONENTS.items() if k != "redis"})
        h.built.clear()

        await h.refresh(dict(COMPONENTS))

        assert "redis" in h.built
