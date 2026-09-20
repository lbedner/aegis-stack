"""``setup_dashboard`` still wires the screen together.

The bootstrap used to be one function closing over every control it
built; it is now five modules handing each other arguments, and the
failure mode of that shape is a control that gets built but never
connected - a toggle with no handler, a body the view never mounts, a
refresher nothing can reach. None of that shows up in a lint or a type
check, and no other test calls this function, so it asserts the wiring
rather than the rendering.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import flet as ft
import pytest

from app.components.frontend.main import setup_dashboard
from app.components.frontend.state.session_state import init_session_state

HEALTH: dict[str, Any] = {
    "components": {
        "aegis": {
            "sub_components": {
                "components": {
                    "sub_components": {
                        "backend": {"name": "backend", "status": "healthy",
                                    "message": "ok"},
                    }
                },
            }
        }
    }
}


class _StubView:
    """Enough of ``BaseView`` for the bootstrap: a page, controls, tasks."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.controls: list[ft.Control] = []
        self._tasks: list[asyncio.Task[None]] = []
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


@pytest.fixture
def page() -> MagicMock:
    page = MagicMock(spec=ft.Page)
    page.data = None
    page.session_id = "test-session"
    # client_storage is awaited by the per-user project hydration.
    page.client_storage = MagicMock()
    page.client_storage.get_async = AsyncMock(return_value=None)
    page.client_storage.set_async = AsyncMock(return_value=None)
    page.client_storage.remove_async = AsyncMock(return_value=None)
    return page


async def _get(path: str, *args: Any, **kwargs: Any) -> Any:
    """The two endpoints the bootstrap hits, and nothing else."""
    if path == "/health/detailed":
        return HEALTH
    return []


@pytest.fixture
async def booted(page: MagicMock) -> Any:
    client = MagicMock()
    client.get = AsyncMock(side_effect=_get)
    init_session_state(page, api_client=client)

    view = _StubView(page)
    await setup_dashboard(view)  # type: ignore[arg-type]
    yield view
    for task in view._tasks:
        task.cancel()
    await asyncio.gather(*view._tasks, return_exceptions=True)


async def test_the_view_gets_a_header_and_a_body(booted: _StubView) -> None:
    header, body = booted.controls
    assert isinstance(header, ft.Container)
    assert isinstance(body, ft.SelectionArea)


async def test_refresh_is_reachable_from_page_data(booted: _StubView) -> None:
    """Modals and cards call the refresher through ``page.data``."""
    assert callable(booted.page.data["refresh_dashboard"])
    assert callable(booted.page.data["update_component"])


def _containers(body: ft.SelectionArea) -> list[ft.Control]:
    return [c for c in body.content.content.controls if c.visible is not None]


async def test_the_toggle_cycles_exactly_one_visible_view(
    booted: _StubView,
) -> None:
    """Cards, then diagram, then stack, and round again - one at a time.

    Asserted from the first click rather than from the mounted state:
    a per-user stack with no projects yet opens on the empty-state CTA
    with all three hidden, which is a different (and correct) start.
    """
    header = booted.controls[0]
    toggle = header.content.controls[1].controls[1].content
    assert isinstance(toggle, ft.IconButton)
    assert toggle.on_click is not None, "view toggle lost its handler"

    body = booted.controls[1]
    stack, cards, diagram = _containers(body)[-3:]
    seen = []
    for _ in range(4):
        await toggle.on_click(None)
        seen.append(
            (bool(stack.visible), bool(cards.visible), bool(diagram.visible))
        )
    assert seen == [
        (False, True, False),
        (False, False, True),
        (True, False, False),
        (False, True, False),
    ]


async def test_the_theme_button_is_bound_after_the_dashboard_exists(
    booted: _StubView,
) -> None:
    """It cannot be bound in ``build_chrome``: the connection check it
    needs belongs to a ``SystemDashboard`` that does not exist yet."""
    header = booted.controls[0]
    theme_button = header.content.controls[1].controls[2].content
    assert theme_button.on_click is not None
    # Sessions start dark, so the first toggle lands on light and the
    # button offers dark; the second brings the moon back.
    await theme_button.on_click(None)
    assert theme_button.icon == ft.Icons.DARK_MODE
    await theme_button.on_click(None)
    assert theme_button.icon == ft.Icons.LIGHT_MODE


async def test_the_background_loops_are_tracked_for_cancellation(
    booted: _StubView,
) -> None:
    """``view.on_leave`` cancels whatever is on ``_tasks``; a loop that
    never lands there outlives the view."""
    assert booted._tasks
    assert all(isinstance(t, asyncio.Task) for t in booted._tasks)
