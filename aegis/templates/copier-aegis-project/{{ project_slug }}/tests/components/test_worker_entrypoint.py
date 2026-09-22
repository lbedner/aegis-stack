"""The worker runs inside a loop it started itself.

``python -m arq <settings>`` calls ``asyncio.get_event_loop()`` with no
running loop, which is a RuntimeError on Python 3.14. arq's own watch
flag hid it by running the worker inside ``asyncio.run`` - so the dev
branch worked and the non-dev branch, the one a deployment takes, was
dead.

One entrypoint for both branches, and it owns the loop.
"""

from __future__ import annotations

import asyncio

import pytest

from app.entrypoints import worker


def test_the_queue_names_its_settings() -> None:
    from app.components.worker.queues.system import WorkerSettings

    assert worker.settings_for("system") is WorkerSettings


def test_an_unknown_queue_says_which_one() -> None:
    with pytest.raises(SystemExit) as raised:
        worker.settings_for("nowhere")
    assert "nowhere" in str(raised.value)


class Recorder:
    def __init__(self, explode: type[BaseException] | None = None) -> None:
        self.seen: list[str] = []
        self._explode = explode

    async def async_run(self) -> None:
        self.seen.append("ran")
        if self._explode is not None:
            raise self._explode()

    async def close(self) -> None:
        self.seen.append("closed")


@pytest.mark.asyncio
async def test_it_runs_the_worker_it_built(monkeypatch: pytest.MonkeyPatch) -> None:
    built = Recorder()
    monkeypatch.setattr(worker, "create_worker", lambda settings: built)

    await worker.main("system")

    assert built.seen == ["ran", "closed"]


@pytest.mark.asyncio
async def test_a_stopped_worker_still_lets_go_of_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """watchfiles stops the process on every edit. Without the close,
    the loop shuts before redis connections do, and each reload prints
    a page of "Event loop is closed" from their deallocators."""
    built = Recorder(explode=asyncio.CancelledError)
    monkeypatch.setattr(worker, "create_worker", lambda settings: built)

    with pytest.raises(asyncio.CancelledError):
        await worker.main("system")

    assert built.seen == ["ran", "closed"]
