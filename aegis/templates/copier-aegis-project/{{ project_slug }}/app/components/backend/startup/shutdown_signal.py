"""Let a stream that would stay open (a page's live SSE) end as the server
starts shutting down (``concurrency.watch_shutdown``): run as the app
starts, once the server has put its own signal handlers in place."""

from app.core.concurrency import watch_shutdown


async def startup_hook() -> None:
    watch_shutdown()
