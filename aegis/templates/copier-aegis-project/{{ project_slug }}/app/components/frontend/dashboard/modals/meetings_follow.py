"""A record followed in a Flet pane while something is happening to it
(the bot in a call, notes or a guide being written): read again every few
seconds and drawn, while it is the one shown and its tab is there
(``SessionLoops``: Flet keeps a closed tab's session for an hour)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.core.session_health import (
    SessionLoops,
    page_is_connected,
)

FOLLOW_SECONDS = 3


async def follow(
    page: ft.Page,
    read: Callable[[], Awaitable[Any]],
    shown: Callable[[], bool],
    draw: Callable[[dict[str, Any]], None],
    busy: Callable[[dict[str, Any]], bool],
    seconds: float = FOLLOW_SECONDS,
) -> bool:
    """Whether it settled (its last read drawn); False once it is no longer
    shown, its tab is gone, or a read failed."""
    loops = SessionLoops(page, lambda: page_is_connected(page))
    while shown() and loops.alive():
        await asyncio.sleep(seconds)
        record = await read()
        if not isinstance(record, dict) or not shown():
            return False
        draw(record)
        if not busy(record):
            return True
    return False
