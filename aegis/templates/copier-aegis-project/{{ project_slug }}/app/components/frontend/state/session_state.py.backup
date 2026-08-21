"""
Session-scoped state for the Overseer.

A single ``SessionState`` instance lives on ``page.data["session_state"]``
for the lifetime of a Flet session. It holds resources that views and
controls share within a session — the HTTP client, theme manager, and
(when auth is enabled) the signed-in user.

This is the **only** intentional home for cross-view session state.
Anything in ``app/core/`` is app-scoped and must never take a page; if
something needs page-bound behavior, it belongs here or in a
``SessionState``-owned service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import flet as ft

from app.core.client import APIClient
from app.core.log import logger

if TYPE_CHECKING:
    from app.components.frontend.theme import ThemeManager

_SESSION_KEY = "session_state"


@dataclass
class SessionState:
    """
    Per-session shared resources.

    Owned by ``page.data["session_state"]``. Dies with the page.
    """

    page: ft.Page
    api_client: APIClient
    theme_manager: ThemeManager | None = None

    _data: dict[str, Any] = field(default_factory=dict)
    """Bag for ad-hoc session-scoped values keyed by string."""

    def get(self, key: str, default: Any = None) -> Any:
        """Read an ad-hoc session value."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Write an ad-hoc session value."""
        self._data[key] = value


def get_session_state(page: ft.Page) -> SessionState:
    """
    Return the SessionState for ``page``, raising if it has not been
    initialized yet. Callers should not construct ``SessionState``
    directly — use the bootstrap helper in ``frontend.main``.
    """
    if page.data is None or _SESSION_KEY not in page.data:
        raise RuntimeError(
            "SessionState has not been initialized for this page. "
            "Call init_session_state() during app bootstrap."
        )
    return page.data[_SESSION_KEY]  # type: ignore[no-any-return]


def init_session_state(
    page: ft.Page,
    *,
    api_client: APIClient,
    theme_manager: ThemeManager | None = None,
) -> SessionState:
    """Construct and attach the SessionState to ``page.data``."""
    if page.data is None:
        page.data = {}
    state = SessionState(
        page=page,
        api_client=api_client,
        theme_manager=theme_manager,
    )
    page.data[_SESSION_KEY] = state
    logger.info("session_state.initialized", session_id=page.session_id)
    return state


async def clear_session_state(page: ft.Page) -> None:
    """Remove the SessionState. Used during a hard session teardown.

    ``aclose()``s the per-session ``APIClient`` first so the underlying
    httpx connection pool is released — this is the one code path where
    we tear SessionState down on purpose, so it's the right place for
    deterministic cleanup. Sign-out does NOT call this (the user can
    sign back in without losing the page); transient WebSocket blips
    do NOT call this (Flet would re-create the page); only true
    end-of-session teardown.
    """
    if page.data is None or _SESSION_KEY not in page.data:
        return
    state: SessionState = page.data[_SESSION_KEY]
    try:
        await state.api_client.aclose()
    except Exception as exc:
        logger.warning(
            "session_state.aclose_failed",
            session_id=page.session_id,
            error=str(exc),
        )
    del page.data[_SESSION_KEY]
    logger.info("session_state.cleared", session_id=page.session_id)
