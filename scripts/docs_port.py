"""Pick a host port for ``make docs-serve``.

The docs server used to insist on 8001, which is exactly where a
generated project's webserver lands when 8000 is taken. Previewing the
docs beside a running stack then failed to bind, and the error reads as
"a docs server is already running" rather than as a collision.

Deliberately a probe rather than a bind: connecting needs no privileges,
so a low base port does not require root.
"""

from __future__ import annotations

import errno
import os
import socket
import sys

_DEFAULT_BASE = 8001


def _attempt(port: int) -> int:
    """0 = free, 1 = busy, -1 = ambiguous.

    macOS answers a self-connect straight after a recent bind with
    EINVAL, which is not a real "in use" signal, so the caller retries
    instead of trusting it.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect(("127.0.0.1", port))
    except ConnectionRefusedError:
        return 0
    except OSError as exc:
        return -1 if exc.errno == errno.EINVAL else 1
    else:
        return 1
    finally:
        sock.close()


def _is_free(port: int) -> bool:
    for _ in range(3):
        verdict = _attempt(port)
        if verdict >= 0:
            return verdict == 0
    return False  # persistent EINVAL: do not hand it out


def docs_port(base: int | None = None, max_attempts: int = 20) -> int:
    """The base port if it is free, else the next one that is."""
    start = (
        base
        if base is not None
        else int(os.environ.get("DOCS_PORT_BASE", _DEFAULT_BASE))
    )
    for port in range(start, start + max_attempts):
        if _is_free(port):
            if port != start:
                print(f">> port {start} in use", file=sys.stderr)
            print(f">> docs: http://127.0.0.1:{port}", file=sys.stderr)
            return port
    raise RuntimeError(
        f"docs_port: no free port in {start}..{start + max_attempts - 1}"
    )


if __name__ == "__main__":
    print(docs_port())
