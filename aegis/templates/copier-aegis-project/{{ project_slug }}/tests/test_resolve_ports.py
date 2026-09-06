"""Tests for scripts/resolve_ports.py, the Python port of resolve-ports.sh.

``make serve`` / ``uv run poe serve`` both call ``resolve_ports`` to pick free
host ports so a busy default (another stack, a local Postgres on 5432, etc.)
doesn't kill the run with "bind: address already in use". These tests pin
the port-scan logic and the ``.env.ports`` write contract that
``app/core/config.py``'s ``Settings`` depends on (see
``tests/test_host_port_resolution.py``): only ``POSTGRES_HOST_PORT``,
``REDIS_HOST_PORT``, ``OLLAMA_HOST_PORT`` and ``INGRESS_DASHBOARD_PORT`` may
ever be persisted, because ``Settings`` has no field for the others and
rejects unknown keys.
"""

from __future__ import annotations

import errno
import socket
from pathlib import Path

import pytest

from scripts import resolve_ports as resolve_ports_module
from scripts.resolve_ports import (
    _find_free_port,
    _is_free,
    docs_port,
    resolve_ports,
)


def _listen_free() -> socket.socket:
    """Bind and listen on an OS-assigned free port (avoids fixed-port flakiness)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock


def _free_port() -> int:
    """Return a currently-free port (bound to 0, then closed)."""
    sock = _listen_free()
    port = sock.getsockname()[1]
    sock.close()
    return port


class _FakeSocket:
    def __init__(self, outcomes: list[Exception | None]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def settimeout(self, timeout: float) -> None:
        pass

    def connect(self, address: tuple[str, int]) -> None:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if outcome is not None:
            raise outcome

    def close(self) -> None:
        pass


class TestFindFreePort:
    def test_returns_base_port_when_free(self) -> None:
        base = _free_port()
        assert _find_free_port(base, max_attempts=5) == base

    def test_skips_a_busy_port(self) -> None:
        blocker = _listen_free()
        try:
            taken = blocker.getsockname()[1]
            assert _find_free_port(taken, max_attempts=50) > taken
        finally:
            blocker.close()

    def test_raises_when_range_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(resolve_ports_module, "_is_free", lambda port: False)
        with pytest.raises(RuntimeError):
            _find_free_port(50000, max_attempts=3)


class TestEinvalRetry:
    """A connect() to a just-freed ephemeral port can self-collide with
    EINVAL on macOS; this is not a real "in use" signal and must be retried,
    not mistaken for busy.
    """

    def test_retries_past_einval_then_detects_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcomes: list[Exception | None] = [
            OSError(errno.EINVAL, "self-connect"),
            None,
        ]
        fake = _FakeSocket(outcomes)
        monkeypatch.setattr(
            resolve_ports_module.socket, "socket", lambda *a, **k: fake
        )
        # A successful connect means something IS listening -> busy, not free.
        assert _is_free(12345) is False
        assert fake.calls == 2

    def test_persistent_einval_falls_back_to_busy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcomes: list[Exception | None] = [OSError(errno.EINVAL, "x")] * 3
        fake = _FakeSocket(outcomes)
        monkeypatch.setattr(
            resolve_ports_module.socket, "socket", lambda *a, **k: fake
        )
        assert _is_free(12345) is False
        assert fake.calls == 3

    def test_connection_refused_is_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeSocket([ConnectionRefusedError()])
        monkeypatch.setattr(
            resolve_ports_module.socket, "socket", lambda *a, **k: fake
        )
        assert _is_free(12345) is True
        assert fake.calls == 1


class TestResolvePorts:
    @pytest.fixture(autouse=True)
    def _identity_port_scan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return each base port unshifted, so these tests exercise the
        key-allowlist and env-override wiring deterministically without
        depending on which ports happen to be free (the scan itself is
        covered by TestFindFreePort)."""
        monkeypatch.setattr(
            resolve_ports_module,
            "_find_free_port",
            lambda start, max_attempts=20: start,
        )

    def test_writes_only_allowlisted_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WEBSERVER_PORT_BASE", "41400")
        monkeypatch.setenv("POSTGRES_PORT_BASE", "41401")
        monkeypatch.setenv("REDIS_PORT_BASE", "41402")
        ports_file = tmp_path / ".env.ports"

        ports = resolve_ports(
            ingress=False,
            postgres=True,
            redis=True,
            ollama=False,
            ports_file=ports_file,
        )

        content = ports_file.read_text()
        assert "POSTGRES_HOST_PORT" in content
        assert "REDIS_HOST_PORT" in content
        assert "WEBSERVER_HOST_PORT" not in content
        assert ports["WEBSERVER_HOST_PORT"] == 41400
        assert ports["POSTGRES_HOST_PORT"] == 41401
        assert ports["REDIS_HOST_PORT"] == 41402

    def test_never_persists_webserver_or_ingress_http(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WEBSERVER_PORT_BASE", "41410")
        monkeypatch.setenv("INGRESS_PORT_BASE", "41411")
        monkeypatch.setenv("INGRESS_DASHBOARD_BASE", "41412")
        ports_file = tmp_path / ".env.ports"

        ports = resolve_ports(
            ingress=True,
            postgres=False,
            redis=False,
            ollama=False,
            ports_file=ports_file,
        )

        content = ports_file.read_text()
        assert "WEBSERVER_HOST_PORT" not in content
        assert "INGRESS_HTTP_PORT" not in content
        assert "INGRESS_DASHBOARD_PORT" in content
        assert ports["INGRESS_HTTP_PORT"] == 41411
        assert ports["INGRESS_DASHBOARD_PORT"] == 41412

    def test_only_resolves_requested_resources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WEBSERVER_PORT_BASE", "41420")
        ports_file = tmp_path / ".env.ports"

        ports = resolve_ports(
            ingress=False,
            postgres=False,
            redis=False,
            ollama=False,
            ports_file=ports_file,
        )

        assert set(ports) == {"WEBSERVER_HOST_PORT"}

    def test_truncates_file_each_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WEBSERVER_PORT_BASE", "41430")
        monkeypatch.setenv("REDIS_PORT_BASE", "41431")
        ports_file = tmp_path / ".env.ports"
        ports_file.write_text("STALE_KEY=1\n")

        resolve_ports(
            ingress=False,
            postgres=False,
            redis=True,
            ollama=False,
            ports_file=ports_file,
        )

        assert "STALE_KEY" not in ports_file.read_text()


class TestDocsPort:
    """``make docs-serve`` picks a port the way ``make serve`` does.

    A hardcoded 8001 is the port a second stack's webserver lands on and
    the port this project's own compose publishes, so the docs server
    failed to bind whenever anything else was already up. Nothing about
    a docs preview needs a fixed port.
    """

    def test_it_takes_the_base_port_when_free(self) -> None:
        base = _free_port()
        assert docs_port(base) == base

    def test_it_steps_past_a_busy_port(self) -> None:
        blocker = _listen_free()
        try:
            taken = blocker.getsockname()[1]
            assert docs_port(taken) > taken
        finally:
            blocker.close()

    def test_it_says_where_the_docs_landed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A resolved port is useless if the user cannot see it."""
        blocker = _listen_free()
        try:
            taken = blocker.getsockname()[1]
            chosen = docs_port(taken)
        finally:
            blocker.close()
        assert str(chosen) in capsys.readouterr().err
