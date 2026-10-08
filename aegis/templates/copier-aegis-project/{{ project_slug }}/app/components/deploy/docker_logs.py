"""Docker's log stream, as the Docker backend reads it (``docker.py``):
multiplexed frames from a container without a TTY, raw text from one with,
cut into whole lines per stream, history and live alike."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.core.runtime import LogLine, RuntimeUnavailableError, parse_log_line

_STREAMS = {0: "stdin", 1: "stdout", 2: "stderr"}


def split_frames(buffer: bytes) -> tuple[list[tuple[str, bytes]], bytes]:
    """Docker's multiplexed log stream: an 8-byte header (stream, three
    zero bytes, big-endian size) before each payload. Whole frames, and
    whatever is left for the next read."""
    frames: list[tuple[str, bytes]] = []
    while len(buffer) >= 8:
        size = int.from_bytes(buffer[4:8], "big")
        if len(buffer) < 8 + size:
            break
        frames.append((_STREAMS.get(buffer[0], "stdout"), buffer[8 : 8 + size]))
        buffer = buffer[8 + size :]
    return frames, buffer


def is_multiplexed(head: bytes) -> bool:
    """A container without a TTY multiplexes stdout and stderr; one with a
    TTY (the workers set ``tty: true``) sends raw text."""
    return len(head) >= 4 and head[0] in _STREAMS and head[1:4] == b"\0\0\0"


class LogDecoder:
    """Whole lines out of Docker's bytes, however they arrive: a line split
    across frames or reads is joined per stream; unfinished bytes are bounded."""

    LIMIT = 1024 * 1024

    def __init__(self) -> None:
        self.buffer = b""
        self.multiplexed: bool | None = None
        self.pending: dict[str, bytes] = {}

    def feed(self, chunk: bytes) -> list[LogLine]:
        self.buffer += chunk
        if self.multiplexed is None and len(self.buffer) >= 4:
            self.multiplexed = is_multiplexed(self.buffer)
        if self.multiplexed:
            frames, self.buffer = split_frames(self.buffer)
        elif self.multiplexed is False:
            frames, self.buffer = [("stdout", self.buffer)], b""
        else:
            frames = []
        lines = []
        for stream, payload in frames:
            text = self.pending.get(stream, b"") + payload
            parts = text.split(b"\n")
            self.pending[stream] = parts.pop()
            if any(len(part) > self.LIMIT for part in parts):
                raise RuntimeUnavailableError(
                    "Docker log line exceeded the 1 MiB input limit; source history may be incomplete"
                )
            lines += [
                parse_log_line(part.decode(errors="replace"), stream) for part in parts
            ]
        if len(self.buffer) + sum(map(len, self.pending.values())) > self.LIMIT:
            raise RuntimeUnavailableError(
                "Docker log input exceeded the 1 MiB pending-byte limit; source history may be incomplete"
            )
        return lines

    def flush(self) -> list[LogLine]:
        return [
            parse_log_line(text.decode(errors="replace"), stream)
            for stream, text in self.pending.items()
            if text
        ]


def history(body: bytes) -> list[LogLine]:
    """A whole ``logs`` response's non-blank lines."""
    decoder = LogDecoder()
    return [line for line in decoder.feed(body) + decoder.flush() if line.text.strip()]


async def follow(
    client: httpx.AsyncClient, instance: str, params: dict[str, str], socket: str
) -> AsyncIterator[LogLine]:
    """History and live lines on one request (no tail/follow race)."""
    try:
        async with client.stream(
            "GET",
            f"/containers/{instance}/logs",
            params=params,
            timeout=httpx.Timeout(10.0, read=None),
        ) as response:
            if response.status_code != 200:
                raise RuntimeUnavailableError(
                    f"Docker refused logs for {instance}: {response.status_code}"
                )
            decoder = LogDecoder()
            async for chunk in response.aiter_bytes():
                for line in decoder.feed(chunk):
                    yield line
            for line in decoder.flush():
                yield line
    except httpx.TransportError as error:
        raise RuntimeUnavailableError(
            f"Docker socket proxy unreachable at {socket}: {error}"
        ) from error
