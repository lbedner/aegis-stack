"""A surface holding a fresh status can apply it without a full refresh.

Loading an Ollama model updates that modal immediately and leaves its
dashboard card stale for up to thirty seconds. The workaround has been
``trigger_dashboard_refresh``, which repaints the entire board to change
one card - and the modal already has the answer in hand, because it
calls ``check_ollama_health()`` in-process and holds the resulting
``ComponentStatus``.

So one component can be applied on its own. The whole-dashboard refresh
goes through the same path, so there is one way to apply a status rather
than two that can drift.
"""

from __future__ import annotations

import flet as ft
import pytest

from app.components.frontend.main import SystemDashboard
from app.services.system.models import ComponentStatus


def status(name: str, state: str = "healthy", **metadata: object) -> ComponentStatus:
    return ComponentStatus(
        name=name,
        status=state,
        message="ok",
        response_time_ms=1.0,
        metadata=dict(metadata),
    )


class Harness:
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
        state = getattr(data.status, "value", data.status)
        return ft.Container(content=ft.Text(f"{name}:{state}"))

    @property
    def cards(self) -> list[ft.Control]:
        return self.container.content.controls

    async def full_refresh(self, components: dict[str, ComponentStatus]) -> None:
        await self.dashboard.update_component_cards(components, self.creator)


COMPONENTS = {
    "backend": status("backend"),
    "ollama": status("ollama", running_models_count=0),
    "redis": status("redis"),
}


class TestApplyingOneComponent:
    @pytest.mark.asyncio
    async def test_only_that_card_is_rebuilt(self) -> None:
        h = Harness()
        await h.full_refresh(COMPONENTS)
        h.built.clear()

        await h.dashboard.update_component(
            "ollama", status("ollama", running_models_count=1)
        )

        assert h.built == ["ollama"]

    @pytest.mark.asyncio
    async def test_the_other_cards_keep_their_identity(self) -> None:
        """The reason this exists: repainting the board to change one
        card discards every other card's controls."""
        h = Harness()
        await h.full_refresh(COMPONENTS)
        keep = {"backend": h.cards[0], "redis": h.cards[2]}

        await h.dashboard.update_component(
            "ollama", status("ollama", running_models_count=1)
        )

        assert h.cards[0] is keep["backend"]
        assert h.cards[2] is keep["redis"]

    @pytest.mark.asyncio
    async def test_the_new_status_reaches_the_card(self) -> None:
        h = Harness()
        await h.full_refresh(COMPONENTS)

        await h.dashboard.update_component("ollama", status("ollama", "unhealthy"))

        assert h.cards[1].content.value == "ollama:unhealthy"

    @pytest.mark.asyncio
    async def test_the_card_stays_in_its_slot(self) -> None:
        h = Harness()
        await h.full_refresh(COMPONENTS)

        await h.dashboard.update_component("ollama", status("ollama", "warning"))

        assert len(h.cards) == 3
        assert [c.content.value.split(":")[0] for c in h.cards] == [
            "backend",
            "ollama",
            "redis",
        ]


class TestItAgreesWithTheFullRefresh:
    @pytest.mark.asyncio
    async def test_an_applied_status_is_not_rebuilt_by_the_next_refresh(self) -> None:
        """One way to apply a status, not two. If the single-component
        path bypassed the cache, the next cycle would rebuild the card it
        had just updated."""
        h = Harness()
        await h.full_refresh(COMPONENTS)
        fresh = status("ollama", running_models_count=1)
        await h.dashboard.update_component("ollama", fresh)
        h.built.clear()

        await h.full_refresh(dict(COMPONENTS, ollama=fresh))

        assert h.built == []

    @pytest.mark.asyncio
    async def test_a_stale_status_in_the_next_refresh_wins(self) -> None:
        """The refresh is authoritative. A component applied optimistically
        and then contradicted by the health check must show the health
        check's answer, not keep the optimistic one."""
        h = Harness()
        await h.full_refresh(COMPONENTS)
        await h.dashboard.update_component(
            "ollama", status("ollama", running_models_count=1)
        )
        h.built.clear()

        await h.full_refresh(COMPONENTS)  # health says zero again

        assert h.built == ["ollama"]
        assert h.cards[1].content.value == "ollama:healthy"


class TestWhenItCannotApply:
    @pytest.mark.asyncio
    async def test_an_unknown_component_is_ignored(self) -> None:
        """A modal for a component this dashboard does not show must not
        insert a card the board never had."""
        h = Harness()
        await h.full_refresh(COMPONENTS)

        await h.dashboard.update_component("nothing-like-this", status("x"))

        assert len(h.cards) == 3

    @pytest.mark.asyncio
    async def test_it_is_safe_before_the_first_paint(self) -> None:
        """A modal can be open before the first refresh has run."""
        h = Harness()

        await h.dashboard.update_component("ollama", status("ollama"))

        assert h.cards == []
