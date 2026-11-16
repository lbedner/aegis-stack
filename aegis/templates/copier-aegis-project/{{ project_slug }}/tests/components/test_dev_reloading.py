"""Dev auto-reload for the scheduler and the arq and taskiq workers
(``app.entrypoints.reloading``): a restart on a change, and a new process
when the one it ran was killed.

watchfiles' CLI, which it replaced, restarts only on a change: one killed
(out of memory) left the CLI running as the container's main process with
nothing under it, the container never restarted and no job ran.
"""

from signal import SIGINT
from typing import Any

import pytest

from app.entrypoints import reloading


class Process:
    """A started command: ``ended`` is what ``poll`` answers."""

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.ended: int | None = None
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self.ended

    def send_signal(self, number: int) -> None:
        self.signals.append(number)
        self.ended = -number

    def wait(self, timeout: float) -> int | None:
        return self.ended


def _started(monkeypatch: pytest.MonkeyPatch) -> list[Process]:
    started: list[Process] = []

    def popen(command: list[str], **_: Any) -> Process:
        started.append(Process(command))
        return started[-1]

    monkeypatch.setattr(reloading.subprocess, "Popen", popen)
    return started


def _ticks(started: list[Process], *ends: int | None) -> Any:
    """One tick with no change per value: the running process ends so
    first (None: it keeps running)."""
    for end in ends:
        started[-1].ended = end
        yield set()


@pytest.mark.parametrize(
    ("ended", "replaced"),
    [
        (-9, True),  # killed (out of memory): a new one, now
        (None, False),  # still running
        # It exited itself (code that fails to import): a new one would
        # fail the same, in a loop. It waits for the change that fixes it.
        (3, False),
    ],
)
def test_a_killed_process_is_replaced(
    monkeypatch: pytest.MonkeyPatch, ended: int | None, replaced: bool
) -> None:
    started = _started(monkeypatch)

    reloading.supervise(["python", "-m", "job"], _ticks(started, ended))

    assert len(started) == (2 if replaced else 1)
    assert started[0].command == ["python", "-m", "job"]


def test_a_change_restarts_it_and_the_end_stops_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _started(monkeypatch)

    reloading.supervise(["job"], iter([{("modified", "app/x.py")}]))

    assert len(started) == 2
    assert started[0].signals == [SIGINT]  # asked to stop, as watchfiles did
    assert started[1].signals == [SIGINT]  # the supervisor stopping stops it


@pytest.mark.parametrize(
    ("exitcode", "cause"),
    [(-9, "likely out of memory"), (-15, "signal 15"), (0, None), (None, None)],
)
def test_killed_names_the_cause(exitcode: int | None, cause: str | None) -> None:
    assert reloading.killed(exitcode) == cause
