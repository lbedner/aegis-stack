"""
Page-level event handlers for the Overseer.

Each handler is a thin entry point wired to a Flet ``page.on_*`` slot in
``main()``. They keep the entrypoint clean and give us one place to add
cross-cutting concerns (logging, error UI) per event.

- ``on_connect`` fires when the WebSocket connects (initial load + browser
  refresh + reconnect after a transient drop). When the user refreshes,
  this is our cue to call ``current_view.on_refresh()``.
- ``on_disconnect`` fires on tab close / lost connection. Logging only.
- ``on_error`` fires on uncaught Flet runtime errors. Logging only.
- ``on_resize`` fires on viewport changes. Right now nothing UI-level
  depends on it, but the hook is reserved for closing overlay menus
  later.
"""

from __future__ import annotations

import flet as ft

from app.core.log import logger


async def on_connect(event: ft.ControlEvent) -> None:
    page: ft.Page = event.page
    logger.info(
        "page.on_connect",
        route=page.route,
        session_id=page.session_id,
    )

    # Browser refresh path: tell the active view to reload its data.
    if page.views:
        current = page.views[-1]
        if hasattr(current, "on_refresh"):
            try:
                await current.on_refresh()
            except Exception:
                logger.exception(
                    "page.on_connect.refresh_failed",
                    view=type(current).__name__,
                )

    # A reconnect rebuilds the client, which can come back without the
    # overlay popups the server still considers open (observed when
    # launch_url opens a provider tab: the browser pauses this tab, the
    # socket blips, and the reconnected client renders without the open
    # modal). Re-assert them with a real visibility delta so the rebuilt
    # client shows what the user had open.
    from app.components.frontend.dashboard.modals.base_popup import BasePopup

    open_popups = [
        control
        for control in page.overlay
        if isinstance(control, BasePopup) and control.visible
    ]
    logger.info("page.on_connect.open_popups", count=len(open_popups))
    for popup in open_popups:
        popup.hide()
        page.update()
        popup.show()
    if open_popups:
        page.update()


async def on_disconnect(event: ft.ControlEvent) -> None:
    page: ft.Page = event.page
    logger.info(
        "page.on_disconnect",
        route=page.route,
        session_id=page.session_id,
    )
    # NOTE: do NOT ``aclose()`` the per-session APIClient here. Flet
    # fires ``on_disconnect`` on transient WebSocket blips too — the
    # session_id stays the same and ``on_connect`` fires moments later
    # against the *same* SessionState. Closing the httpx client on
    # disconnect would leave the post-reconnect call to ``/auth/me``
    # hitting a closed client.
    #
    # ``APIClient.aclose()`` is intentionally caller-driven instead:
    # it runs from ``clear_session_state(page)`` (the one place
    # SessionState is destroyed on purpose). Flet 0.28 doesn't expose
    # a true session-destroyed hook, so anything more eager would be a
    # hack. In practice the connection pool drains via Python GC when
    # the page object is collected.


async def on_error(event: ft.ControlEvent) -> None:
    page: ft.Page = event.page
    logger.error(
        "page.on_error",
        data=event.data,
        route=page.route,
        session_id=page.session_id,
    )


async def on_resize(event: ft.ControlEvent) -> None:
    page: ft.Page = event.page
    logger.debug(
        "page.on_resize",
        width=page.width,
        height=page.height,
        session_id=page.session_id,
    )
    # Reserved for closing overlay menus / dropdowns when the viewport
    # changes. No-op for now.
