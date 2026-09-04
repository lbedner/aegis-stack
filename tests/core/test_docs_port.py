"""``make docs-serve`` must not insist on a port something else holds.

8001 was hardcoded, and 8001 is exactly where a generated project's
webserver lands when 8000 is taken. Previewing the docs beside a running
stack failed to bind, which reads as "a docs server is already running"
rather than as a port collision.
"""

from __future__ import annotations

import socket

import pytest

from scripts import docs_port as docs_port_module
from scripts.docs_port import docs_port


def _listen_free() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock


def _free_port() -> int:
    sock = _listen_free()
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_it_takes_the_base_port_when_free() -> None:
    base = _free_port()
    assert docs_port(base) == base


def test_it_steps_past_a_busy_port() -> None:
    blocker = _listen_free()
    try:
        taken = blocker.getsockname()[1]
        assert docs_port(taken) > taken
    finally:
        blocker.close()


def test_it_says_where_the_docs_landed(capsys: pytest.CaptureFixture[str]) -> None:
    """A resolved port is useless if the user cannot see it."""
    blocker = _listen_free()
    try:
        taken = blocker.getsockname()[1]
        chosen = docs_port(taken)
    finally:
        blocker.close()
    assert str(chosen) in capsys.readouterr().err


def test_it_gives_up_rather_than_scanning_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Better a clear error than a silent scan up the port range."""
    monkeypatch.setattr(docs_port_module, "_is_free", lambda port: False)
    with pytest.raises(RuntimeError):
        docs_port(9999, max_attempts=3)
