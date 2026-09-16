"""Detection for unrecoverable Flet session states.

Flet raises AssertionError from ``_process_remove_command`` when a
session's server-side control tree has desynced from the client - the
classic trigger is a tab reconnecting across a webserver restart. The
session cannot be repaired server-side; only a client reload creates a
working one. Background loops must stop instead of retrying forever.
"""

import time
from typing import Any
from uuid import uuid4

from app.core.log import logger

# This process's identity, minted at import. A tab that reconnects
# carrying a different one was talking to a webserver that no longer
# exists, so the control tree it holds was never built here.
BOOT_ID = uuid4().hex
BOOT_ID_KEY = "aegis.boot_id"

# How long a page may read as disconnected before its loops give up on it.
# Flet fires a disconnect on transient WebSocket blips and reconnects within
# seconds, so an immediate exit would kill healthy sessions.
DISCONNECT_GRACE_SECONDS = 30.0


def is_tree_corruption(exc: BaseException) -> bool:
    """True when the exception signals a desynced Flet control tree."""
    return isinstance(exc, AssertionError) and "_process_remove_command" in str(exc)


async def handle_corrupt_session(page: Any) -> None:
    """Steer a desynced session's client to a fresh page load.

    ``launch_url`` with ``_self`` replaces the current page - the one
    command that still works on a corrupted session because it does not
    touch the control tree. The caller should stop its loop afterwards.
    """
    logger.warning("Session tree corrupt; steering client to reload")
    try:
        page.launch_url("/dashboard/", web_window_name="_self")
    except Exception as e:
        logger.debug(f"Client reload nudge failed (client must reload manually): {e}")


class SessionLoops:
    """The rules every background loop of one page shares.

    A page runs several: the dashboard refresh (30s), the worker-modal
    flush (0.1s), the SSE listener. They need the same three answers, and
    when each loop answered for itself they disagreed:

    * **Is the page still worth working for?** Measured in TIME, not in
      iterations. The same "30 checks" meant 3 seconds to the 0.1s loop
      and fifteen minutes to the 30s one.
    * **Is this exception fatal?** A desynced control tree cannot be
      repaired server-side, so retrying is a spin. Only the dashboard
      loop knew that; the other two caught ``Exception`` and carried on
      forever - and could not even be stopped by the liveness check,
      because a session that reconnected across a restart IS connected.
      Its tree is what is broken.
    * **Who else has to stop?** All of them. One corrupt tree means the
      page is unrecoverable, so the first loop to notice stops the rest.
    """

    def __init__(
        self,
        page: Any,
        is_connected: Any,
        grace_seconds: float = DISCONNECT_GRACE_SECONDS,
    ) -> None:
        self._page = page
        self._is_connected = is_connected
        self._grace_seconds = grace_seconds
        self._first_failure: float | None = None
        self._stopped = False

    def alive(self, now: float | None = None) -> bool:
        """True while this page's loops should keep running."""
        if self._stopped:
            return False
        if self._is_connected():
            self._first_failure = None
            return True
        current = time.monotonic() if now is None else now
        if self._first_failure is None:
            self._first_failure = current
        within_grace = (current - self._first_failure) < self._grace_seconds
        if not within_grace:
            logger.debug("Page disconnected past the grace period; loops exiting")
        return within_grace

    async def fatal(self, exc: BaseException) -> bool:
        """True when the caller must return, and every other loop too.

        Handles the corruption itself - one nudge to the client, not one
        per loop - and latches the stop so the remaining loops exit at
        their next check rather than waiting on a liveness signal that
        will never come.
        """
        if not is_tree_corruption(exc):
            return False
        if not self._stopped:
            self._stopped = True
            await handle_corrupt_session(self._page)
        return True

    def stop(self) -> None:
        """End this page's loops (page teardown, navigation away)."""
        self._stopped = True


async def reload_if_server_restarted(page: Any) -> bool:
    """Reload a tab that predates this process, before it touches the tree.

    The corruption itself is only detectable by provoking it: some later
    ``update()`` raises from ``_process_remove_command`` and the loops
    stop. This catches the same condition one step earlier, at connect,
    where the cure is identical and nothing has failed yet - the user
    sees a blink instead of a frozen frame.

    ``client_storage`` is a session command rather than a control-tree
    update, so it still answers on a stale session; that is the same
    property ``launch_url`` relies on to steer the reload.

    Returns True when the page was sent to reload, so the caller can stop
    setting up a session that is about to be replaced. Any failure here
    returns False: a connect must never be blocked by this check, and the
    reactive path in ``SessionLoops`` still covers what it misses.
    """
    try:
        seen = await page.client_storage.get_async(BOOT_ID_KEY)
        if seen is not None and seen != BOOT_ID:
            logger.warning(
                "Tab predates this webserver process; reloading before it renders",
                seen_boot_id=seen,
                boot_id=BOOT_ID,
            )
            await handle_corrupt_session(page)
            return True
        if seen != BOOT_ID:
            await page.client_storage.set_async(BOOT_ID_KEY, BOOT_ID)
    except Exception as e:
        logger.debug(f"Boot-id check unavailable ({e}); relying on loop detection")
    return False
