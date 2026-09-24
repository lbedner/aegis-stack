"""
Legacy dashboard wrapper.

The existing dashboard rendering predates the View/router architecture
— it's a 700-line closure inside ``flet_main``. Rather than rewrite it,
this thin wrapper hosts the body inside a real ``BaseView`` so the
router can navigate to it. ``on_enter`` calls into ``main.setup_dashboard``
which owns the actual rendering; ``on_leave`` cancels every background
task the dashboard spawned.

A future PR will inline this into a proper ``DashboardView`` with the
composition-in-``__init__`` style. For now this preserves the existing
dashboard while letting routing/login/logout flow through cleanly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import flet as ft

from app.components.frontend.controls.views.base import BaseView
from app.core.log import logger


class LegacyDashboardView(BaseView):
    """Hosts the existing dashboard body as a routed View."""

    def __init__(self, *, page: ft.Page, route: str) -> None:
        super().__init__(
            page=page,
            route=route,
            padding=ft.padding.only(left=12, right=12, top=12, bottom=12),
        )
        self._tasks: list[asyncio.Task[Any]] = []
        # Controls are populated lazily in ``on_enter`` because the dashboard
        # needs ``self.page`` (set by Flet on mount) to wire its handlers.

    async def on_enter(self, params: dict[str, Any]) -> None:
        # Lazy import: setup_dashboard lives in ``main`` which transitively
        # imports a lot of dashboard internals. Importing at module load time
        # would create a cycle through the router.
        from app.components.frontend.main import setup_dashboard

        try:
            await setup_dashboard(self)
        except Exception:
            logger.exception(
                "legacy_dashboard.setup_failed",
                session_id=self.page.session_id,
            )

    async def on_leave(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        # Not a view task: the worker modal owns when it runs.
        stream = (self.page.data or {}).get("worker_stream")
        if stream is not None:
            stream.stop()
        logger.info(
            "legacy_dashboard.on_leave.tasks_cancelled",
            session_id=self.page.session_id,
        )

    async def on_refresh(self) -> None:
        # The legacy ``setup_dashboard`` exposes its refresh function on
        # ``page.data["refresh_dashboard"]`` for callers that need it.
        if self.page.data:
            refresh = self.page.data.get("refresh_dashboard")
            if callable(refresh):
                try:
                    await refresh()
                except Exception:
                    logger.exception(
                        "legacy_dashboard.on_refresh.failed",
                        session_id=self.page.session_id,
                    )
