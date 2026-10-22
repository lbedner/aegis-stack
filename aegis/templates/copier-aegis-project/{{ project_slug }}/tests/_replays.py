"""A request kept to replay, for a test: served with its hops, answered
and kept as the server keeps one (``replays.keep``)."""

from app.core import replays
from app.core.replays import Hop, Recording


async def kept(
    path: str, *hops: Hop, route: str = "", status: int = 200, ms: float = 20.0
) -> Recording:
    token = replays.start("GET", path)
    recording = replays.current()
    assert recording is not None
    recording.hops += hops
    found = replays.finish(token, route=route or path, status=status, ms=ms)
    assert found is not None
    await replays.keep(found)
    return found
