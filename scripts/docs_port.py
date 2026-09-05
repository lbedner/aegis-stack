"""Pick a host port for ``make docs-serve``.

The docs server used to insist on 8001, which is exactly where a
generated project's webserver lands when 8000 is taken. Previewing the
docs beside a running stack then failed to bind, and the error reads as
"a docs server is already running" rather than as a collision.

The probe BINDS rather than connects, on the same address mkdocs is about
to bind (loopback: this is a local preview, not a server). A connect
probe only proves nothing is listening; a bind fails for every reason
mkdocs would - already bound, bound but idle, privileged without root -
and the port is skipped. No SO_REUSEADDR: with it, a bind can succeed
beside a live listener on macOS and hand out a port that is in use.
"""

from __future__ import annotations

import os
import socket
import sys


def _is_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        return False
    else:
        return True
    finally:
        sock.close()


def docs_port(base: int | None = None, max_attempts: int = 20) -> int:
    """The base port if it can be bound, else the next one that can."""
    start = base if base is not None else int(os.environ.get("DOCS_PORT_BASE", "8001"))
    if not 1 <= start <= 65535:
        raise ValueError(f"docs_port: {start} is not a TCP port")
    # Never scan past the top of the range: 65536 is not a port, and the
    # socket call raises rather than declining.
    for port in range(start, min(start + max_attempts, 65536)):
        if _is_free(port):
            if port != start:
                print(f">> port {start} unavailable", file=sys.stderr)
            print(f">> docs: http://127.0.0.1:{port}", file=sys.stderr)
            return port
    raise RuntimeError(
        f"docs_port: no free port in {start}..{start + max_attempts - 1}"
    )


if __name__ == "__main__":
    print(docs_port())
