"""Close the runtime backend's connections (``app.core.runtime``): the
Docker backend keeps one client to the socket proxy for every call."""

from app.core import runtime


async def shutdown_hook() -> None:
    await runtime.close()
