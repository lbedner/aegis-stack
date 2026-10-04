"""Docker's log stream, as the Docker backend reads it (``docker.py``):
multiplexed frames from a container without a TTY, raw text from one with,
cut into whole lines and the bytes still waiting for the rest."""

from __future__ import annotations

from app.core.runtime import LogLine, parse_log_line

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


def decode(buffer: bytes, multiplexed: bool) -> tuple[list[LogLine], bytes]:
    """Complete lines out of ``buffer``, and the bytes still incomplete.

    ponytail: a line split across two multiplexed frames comes out as two
    lines; Docker writes one frame per write, so this needs a writer that
    flushes mid-line. Join per stream if it shows up.
    """
    if multiplexed:
        frames, rest = split_frames(buffer)
    else:
        text, newline, rest = buffer.rpartition(b"\n")
        frames = [("stdout", text)] if newline else []
    lines = [
        parse_log_line(line, stream)
        for stream, payload in frames
        for line in payload.decode(errors="replace").splitlines()
        if line.strip()
    ]
    return lines, rest
