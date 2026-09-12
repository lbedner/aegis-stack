"""Detection for unrecoverable Flet session states.

Flet raises AssertionError from ``_process_remove_command`` when a
session's server-side control tree has desynced from the client - the
classic trigger is a tab reconnecting across a webserver restart. The
session cannot be repaired server-side; only a client reload creates a
working one. Background loops must stop instead of retrying forever.
"""

from typing import Any

from app.core.log import logger


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
