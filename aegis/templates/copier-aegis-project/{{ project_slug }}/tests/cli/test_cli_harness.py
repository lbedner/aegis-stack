"""The CLI harness owns the one event loop an async command runs on, so it
is also where the process-shared cache is closed: after the command, inside
that loop. Closed any later, the Redis client's pool is torn down by the
garbage collector after the loop is gone ("RuntimeError: Event loop is
closed" at exit)."""

import asyncio

import pytest

from app.cli import main as cli_main
from app.core.cache import get_cache


def _closing(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.AbstractEventLoop]:
    closed_on: list[asyncio.AbstractEventLoop] = []

    async def aclose() -> None:
        closed_on.append(asyncio.get_running_loop())

    monkeypatch.setattr(get_cache(), "aclose", aclose)
    return closed_on


def test_the_cache_closes_on_the_commands_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    closed_on = _closing(monkeypatch)
    ran_on: list[asyncio.AbstractEventLoop] = []

    async def command() -> str:
        ran_on.append(asyncio.get_running_loop())
        return "synced"

    assert asyncio.run(cli_main.run_command(command())) == "synced"
    assert closed_on == ran_on


def test_a_failing_command_still_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    closed_on = _closing(monkeypatch)

    async def command() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(cli_main.run_command(command()))
    assert len(closed_on) == 1
