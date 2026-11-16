"""A race in anyio's wait on a raw socket, which is how it reads the proxy's
Unix socket under httpx (``docker.py``).

anyio registers the wait's own ``future.set_result`` as the socket's
reader and removes it in a done-callback, which runs on the loop's next
pass. A read cancelled as the socket turns readable (a followed log
stopped mid-flow, as every one is when the server shuts down) has uvloop
call that ``set_result`` on the cancelled future first, and the loop logs
``InvalidStateError``. ``guard`` re-registers each wait with a callback
that settles only a future still waiting.
"""

import asyncio
from collections.abc import Callable
from functools import cache
from typing import Any

from app.core.log import logger


def _settle(future: asyncio.Future[Any]) -> None:
    if not future.done():
        future.set_result(None)


def _waiting(
    wait: Callable[..., asyncio.Future[Any]], register: str
) -> Callable[..., asyncio.Future[Any]]:
    def guarded(stream: Any, loop: asyncio.AbstractEventLoop) -> asyncio.Future[Any]:
        future = wait(stream, loop)
        getattr(loop, register)(stream._raw_socket, _settle, future)  # replaces anyio's
        return future

    return guarded


@cache
def guard() -> None:
    """Settle anyio's raw-socket waits only while they wait; once per process."""
    # ponytail: patches anyio 4.16's private _RawSocketMixin; drop it once
    # anyio's own reader callback checks the future (none does yet).
    try:
        from anyio._backends._asyncio import _RawSocketMixin as Mixin
    except ImportError as exc:
        logger.warning("deploy.socket_race.unguarded", error=str(exc))
        return
    Mixin._wait_until_readable = _waiting(Mixin._wait_until_readable, "add_reader")
    Mixin._wait_until_writable = _waiting(Mixin._wait_until_writable, "add_writer")
