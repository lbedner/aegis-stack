"""The runner: a process on another machine that claims runs over the
app's API, runs a command for each (a coding agent, in a fresh worktree of
the repository it answers from), and posts back what it printed. Driven
here against a fake API and a real git repository."""

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import httpx
import pytest

from app.services.meetings.domains.actions.runner import Runner, run_once

PROMPT = "Then Dana asked:\n\nCan the CSV export ship this week?"


def _api(
    runs: list[dict[str, Any]], finished: list[dict[str, Any]]
) -> httpx.MockTransport:
    """An API that hands out ``runs`` one claim at a time, then nothing,
    and keeps what each finish posted."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer mrt_test"
        if request.url.path.endswith("/runs/claim"):
            assert json.loads(request.content) == {"actions": ["agent"]}
            return (
                httpx.Response(200, json=runs.pop(0)) if runs else httpx.Response(204)
            )
        run_id = int(request.url.path.split("/")[-2])
        finished.append({"id": run_id, **json.loads(request.content)})
        return httpx.Response(
            200, json={"id": run_id, "action": "agent", "status": "done"}
        )

    return httpx.MockTransport(handle)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one commit, for the runner's worktrees."""
    path = tmp_path / "repo"
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (path / "README.md").write_text("The export ships on Thursdays.\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "first"], check=True)
    return path


def _runner(repo: Path | None, command: list[str]) -> Runner:
    return Runner(
        url="http://app",
        token="mrt_test",
        actions=["agent"],
        command=command,
        repo=repo,
        ref="HEAD",
    )


# Prints the question's last line and where it ran, then the README there.
ANSWER = [
    sys.executable,
    "-c",
    "import os, sys; print(sys.argv[1].splitlines()[-1]); print(os.getcwd());"
    " print(open('README.md').read().strip())",
    "{prompt}",
]


async def test_a_run_is_answered_in_a_fresh_worktree_and_posted(repo: Path) -> None:
    finished: list[dict[str, Any]] = []
    api = _api([{"id": 7, "action": "agent", "prompt": PROMPT}], finished)

    assert await run_once(_runner(repo, ANSWER), transport=api)

    ((done),) = finished
    question, where, readme = done["result"].splitlines()
    assert done["id"] == 7 and done["ok"] is True
    assert question == "Can the CSV export ship this week?"
    assert readme == "The export ships on Thursdays."
    assert Path(where) != repo and not Path(where).exists()


async def test_nothing_waiting_does_nothing(repo: Path) -> None:
    finished: list[dict[str, Any]] = []

    assert not await run_once(_runner(repo, ANSWER), transport=_api([], finished))
    assert finished == []


async def test_a_command_that_fails_posts_why(repo: Path) -> None:
    finished: list[dict[str, Any]] = []
    fails = [sys.executable, "-c", "import sys; sys.exit('no answer here')", "{prompt}"]
    api = _api([{"id": 3, "action": "agent", "prompt": PROMPT}], finished)

    await run_once(_runner(repo, fails), transport=api)

    ((done),) = finished
    assert done["ok"] is False and "no answer here" in done["result"]


async def test_a_command_without_a_prompt_placeholder_reads_it_on_stdin() -> None:
    """Any headless command works: one that takes the prompt as an argument
    names ``{prompt}``, one that reads it from stdin does not; no repository
    runs it where the runner was started."""
    finished: list[dict[str, Any]] = []
    stdin = [
        sys.executable,
        "-c",
        "import sys; print(sys.stdin.read().splitlines()[-1])",
    ]
    api = _api([{"id": 4, "action": "agent", "prompt": PROMPT}], finished)

    await run_once(_runner(None, stdin), transport=api)

    assert finished[0]["result"] == "Can the CSV export ship this week?"
