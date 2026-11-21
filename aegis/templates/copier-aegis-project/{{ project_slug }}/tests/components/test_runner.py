"""The runner: a process on another machine that claims runs over the
app's API, runs a command for each (a coding agent, in a worktree of the
repository it answers from), and posts back what it printed. Driven here
against a fake API, real git repositories and stand-in commands."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.components.runner import client, hooks, protocol
from app.components.runner.client import Runner, run_once
from app.components.runner.protocol import CLAIM, Answer, ClaimedRun

PROMPT = "Then Dana asked:\n\nCan the CSV export ship this week?"


def _python(code: str, *args: str) -> list[str]:
    """A command that runs ``code`` with ``args``."""
    return [sys.executable, "-c", code, *args]


def _agent(said: dict[str, Any], *before: str, code: int = 0) -> list[str]:
    """A command that answers as a coding agent does: the lines ``before``
    it, then ``said`` as one JSON object, exiting ``code``."""
    lines = [*before, json.dumps(said)]
    return _python(f"import sys; print({chr(10).join(lines)!r}); sys.exit({code})")


def _run(**fields: Any) -> dict[str, Any]:
    """A run as the app hands it to a runner, but for ``fields``."""
    asked = {"id": 7, "action": "agent", "prompt": PROMPT, **fields}
    return ClaimedRun(**asked).model_dump()


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one commit, for the runner's worktrees."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    (path / "README.md").write_text("The export ships on Thursdays.\n")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "first")
    return path


def _runner(repo: Path | None, command: list[str], **more: Any) -> Runner:
    return Runner(
        url="http://app",
        token="rnr_test",
        actions=["agent"],
        command=command,
        repo=repo,
        ref="HEAD",
        **more,
    )


async def _posted(
    runner: Runner, *runs: dict[str, Any], asked: list[dict[str, Any]] | None = None
) -> list[Answer]:
    """What ``runner`` posts back for ``runs``, claimed one at a time until
    none waits; what it sent to claim each goes in ``asked``."""
    waiting, posted = list(runs), []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer rnr_test"
        body = json.loads(request.content)
        if request.url.path == CLAIM:
            if asked is not None:
                asked.append(body)
            return (
                httpx.Response(200, json=waiting.pop(0))
                if waiting
                else httpx.Response(204)
            )
        posted.append(Answer(**body))
        return httpx.Response(200, json={"id": 7, "action": "agent", "status": "done"})

    while await run_once(runner, transport=httpx.MockTransport(handle)):
        pass
    return posted


# Prints the question's last line and where it ran, then the README there.
ANSWER = _python(
    "import os, sys; print(sys.argv[1].splitlines()[-1]); print(os.getcwd());"
    " print(open('README.md').read().strip())",
    "{prompt}",
)
# Writes its first argument into NOTES.md where it runs, and answers as a
# coding agent does, saying its session.
WORK = _python(
    "import json, sys; open('NOTES.md', 'a').write(sys.argv[1] + chr(10));"
    " print(json.dumps({'result': 'Noted ' + sys.argv[2], 'total_cost_usd': 0.25}))",
    "{prompt}",
    "{session}",
)
# Answers with its first argument, as a coding agent does.
SAYS = "import json, sys; print(json.dumps({'result': sys.argv[1], 'total_cost_usd': 0.1}))"


async def test_a_run_is_answered_in_a_fresh_worktree_and_posted(repo: Path) -> None:
    asked: list[dict[str, Any]] = []

    (done,) = await _posted(_runner(repo, ANSWER), _run(), asked=asked)

    question, where, readme = done.result.splitlines()
    assert done.ok and done.worktree is None
    assert question == "Can the CSV export ship this week?"
    assert readme == "The export ships on Thursdays."
    assert Path(where) != repo and not Path(where).exists()
    assert asked[0]["actions"] == ["agent"]


async def test_nothing_waiting_does_nothing(repo: Path) -> None:
    assert await _posted(_runner(repo, ANSWER)) == []


async def test_a_command_that_fails_posts_why(repo: Path) -> None:
    fails = _python("import sys; sys.exit('no answer here')", "{prompt}")

    (done,) = await _posted(_runner(repo, fails), _run())

    assert not done.ok and "no answer here" in done.result


async def test_a_command_without_a_prompt_placeholder_reads_it_on_stdin() -> None:
    """Any headless command works: one that takes the prompt as an argument
    names ``{prompt}``, one that reads it from stdin does not; no repository
    runs it where the runner was started."""
    stdin = _python("import sys; print(sys.stdin.read().splitlines()[-1])")

    (done,) = await _posted(_runner(None, stdin), _run())

    assert done.result == "Can the CSV export ship this week?"


async def test_a_long_answer_keeps_its_start_and_a_long_failure_its_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(protocol, "KEEP", 5)
    answers = _python("print('abcdefghij')")
    fails = _python("import sys; sys.exit('abcdefghij')")

    (said,) = await _posted(_runner(None, answers), _run())
    (failed,) = await _posted(_runner(None, fails), _run())

    assert (said.result, failed.result) == ("abcde", "fghij")


async def test_a_run_with_a_branch_leaves_its_worktree_on_it(
    repo: Path, tmp_path: Path
) -> None:
    """Work, not one answer: the worktree stays, on the run's branch, with
    what the agent changed, and the run says where it is and what the
    agent says its session has cost. The app is told where the runner
    keeps worktrees when it claims, to say where before the run is back."""
    asked: list[dict[str, Any]] = []
    run = _run(prompt="first", branch="issue-12-export", session_id="0f0f")
    kept = tmp_path / "kept"

    (done,) = await _posted(_runner(repo, WORK, worktrees=kept), run, asked=asked)

    where = kept / "issue-12-export"
    assert done.ok and done.result == "Noted 0f0f"
    assert done.cost == 0.25 and done.worktree == str(where)
    assert (where / "NOTES.md").read_text() == "first\n"
    assert _git(where, "branch", "--show-current") == "issue-12-export"
    # Where the app says the work will be (``queries.take``) is where it is.
    assert f"{asked[0]['worktrees']}/{run['branch']}" == done.worktree


async def test_a_follow_up_resumes_the_session_in_the_same_worktree(
    repo: Path, tmp_path: Path
) -> None:
    """A later run of the same session runs the resume form where the first
    left off: the agent remembers what it read and did."""
    first = _run(prompt="first", branch="issue-12", session_id="0f0f")
    second = {**first, "prompt": "second", "resume": True}
    resume = [*WORK[:3], "resumed {prompt}", "{session}"]
    runner = _runner(repo, WORK, worktrees=tmp_path / "kept", resume_command=resume)

    done = await _posted(runner, first, second)

    notes = (tmp_path / "kept" / "issue-12" / "NOTES.md").read_text()
    assert notes == "first\nresumed second\n"
    assert [answer.ok for answer in done] == [True, True]


async def test_a_branch_the_remote_has_is_worked_on_as_it_is_there(
    repo: Path, tmp_path: Path
) -> None:
    """Follow-up work on a branch someone pushed starts from that branch,
    not from the ref a new branch is cut from."""
    _git(repo, "checkout", "-q", "-b", "work-7")
    (repo / "PUSHED.md").write_text("already there\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "pushed work")
    _git(repo, "checkout", "-q", "-")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)
    runner = _runner(clone, WORK, worktrees=tmp_path / "kept")

    (done,) = await _posted(runner, _run(branch="work-7"))

    assert done.ok and (tmp_path / "kept" / "work-7" / "PUSHED.md").exists()


async def test_a_run_with_no_session_is_given_one(repo: Path) -> None:
    """One command serves every run: a run handed over with no session (by
    an app from before it gave every run one) gets one of the runner's."""
    (done,) = await _posted(_runner(repo, WORK), _run(prompt="hello"))

    assert UUID(done.result.removeprefix("Noted "))


@pytest.mark.parametrize(
    ("resume", "command", "resume_command", "said"),
    [
        pytest.param(
            False,
            _python("import sys; sys.exit('Session ID is already in use.')"),
            _python(SAYS, "resumed {prompt}"),
            "resumed go on",
            id="begun-in-a-run-the-app-never-heard-from",
        ),
        pytest.param(
            True,
            _python(SAYS, "started {prompt}"),
            _python("import sys; sys.exit('No conversation found')"),
            "started go on",
            id="never-begun-or-kept-on-another-machine",
        ),
        pytest.param(
            True,
            _python(SAYS, "started {prompt}"),
            _agent({"is_error": True, "total_cost_usd": 0, "errors": ["None"]}, code=1),
            "started go on",
            id="refused-in-the-agents-own-words",
        ),
    ],
)
async def test_a_session_the_agent_refuses_one_way_is_tried_the_other(
    resume: bool, command: list[str], resume_command: list[str], said: str
) -> None:
    """Whether a session is one to start or to continue is the agent's to
    say: what the app expects is tried first, and the other form once if
    the agent refuses it at once, so no session is stuck."""
    run = _run(prompt="go on", session_id="0f0f", resume=resume)
    runner = _runner(None, command, resume_command=resume_command)

    (done,) = await _posted(runner, run)

    assert (done.ok, done.result) == (True, said)


async def test_a_session_refused_both_ways_says_why_each_time() -> None:
    """Whatever stopped the first form (a bad login, say) is the reason:
    the second form's refusal goes under it, never in its place."""
    start = _python("import sys; sys.exit('Invalid API key')")
    resume = _python("import sys; sys.exit('No conversation found')")
    run = _run(session_id="0f0f")

    (done,) = await _posted(_runner(None, start, resume_command=resume), run)

    assert not done.ok
    assert done.result == "Invalid API key\nNo conversation found"


async def test_a_command_that_worked_before_it_failed_is_not_run_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A refusal comes at once. A command that failed later was working:
    running the other form would be a second run of the same work, and
    its refusal would hide why the first one failed."""
    monkeypatch.setattr(client, "REFUSAL_SECONDS", 0.2)
    slow = _python("import sys, time; time.sleep(0.6); sys.exit('ran out of disk')")
    other = _python("import sys; open(sys.argv[1], 'w')", str(tmp_path / "ran-again"))
    run = _run(session_id="0f0f")

    (done,) = await _posted(_runner(None, slow, resume_command=other), run)

    assert not done.ok and "ran out of disk" in done.result
    assert not (tmp_path / "ran-again").exists()


@pytest.mark.parametrize(
    ("said", "result"),
    [
        pytest.param(
            {
                "type": "result",
                "subtype": "error_max_turns",
                "is_error": True,
                "total_cost_usd": 0.0043,
                "errors": ["Reached maximum number of turns (1)"],
            },
            "Reached maximum number of turns (1)",
            id="its-reasons",
        ),
        pytest.param(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "total_cost_usd": 0.0043,
            },
            "error_during_execution",
            id="the-kind-of-failure",
        ),
    ],
)
async def test_an_agents_error_answer_is_read_for_why_and_what_it_cost(
    said: dict[str, Any], result: str
) -> None:
    (done,) = await _posted(_runner(None, _agent(said, code=1)), _run())

    assert (done.ok, done.result, done.cost) == (False, result, 0.0043)


async def test_an_agent_that_says_it_failed_is_a_failed_run() -> None:
    failing = _agent(
        {"result": "Out of budget", "total_cost_usd": 1.5, "is_error": True}
    )

    (done,) = await _posted(_runner(None, failing), _run())

    assert (done.ok, done.result, done.cost) == (False, "Out of budget", 1.5)


async def test_an_answer_after_a_line_of_warning_is_still_the_agents() -> None:
    warns = _agent({"result": "fine", "total_cost_usd": 0.1}, "warning: update due")

    (done,) = await _posted(_runner(None, warns), _run())

    assert (done.result, done.cost) == ("fine", 0.1)


@pytest.mark.parametrize("cost", [False, float("nan"), -1], ids=str)
async def test_a_cost_that_is_no_amount_is_no_cost(cost: Any) -> None:
    odd = _agent({"result": "fine", "total_cost_usd": cost})

    (done,) = await _posted(_runner(None, odd), _run())

    assert done.ok and done.cost is None


async def test_a_prompt_that_names_a_placeholder_reaches_the_command_as_asked() -> None:
    echo = _python("import sys; print(sys.argv[1])", "{prompt}")
    asked_of = "explain the {session} and {prompt} placeholders"

    (done,) = await _posted(_runner(None, echo), _run(prompt=asked_of))

    assert done.result == asked_of


async def test_a_command_out_of_time_is_stopped_with_all_it_started(
    tmp_path: Path,
) -> None:
    """A command that outlives its time is stopped with what it started:
    nothing of it goes on working in a worktree the next run will use."""
    beat = tmp_path / "beat"
    child = f"import time\nwhile True:\n    open({str(beat)!r}, 'a').write('.'); time.sleep(0.05)"
    spawns = _python(
        "import subprocess, sys, time;"
        " subprocess.Popen([sys.executable, '-c', sys.argv[1]]); time.sleep(30)",
        child,
    )

    (done,) = await _posted(_runner(None, spawns, timeout_seconds=1.0), _run())

    assert not done.ok and "stopped after 1 seconds" in done.result
    written = beat.stat().st_size
    time.sleep(0.3)
    assert beat.stat().st_size == written


async def test_a_runner_told_to_stop_stops_its_command(tmp_path: Path) -> None:
    """Ctrl-C reaches the runner alone (its command is in a group of its
    own): the runner stops the command, at once, instead of leaving an
    agent at work with nobody to post its answer."""
    beat = tmp_path / "beat"
    beats = _python(
        "import sys, time\nwhile True:\n"
        "    open(sys.argv[1], 'a').write('.'); time.sleep(0.05)",
        str(beat),
    )
    answering = asyncio.create_task(_posted(_runner(None, beats), _run()))
    while not beat.exists():
        await asyncio.sleep(0.05)

    answering.cancel()
    with pytest.raises(asyncio.CancelledError):
        await answering

    await asyncio.sleep(0.2)
    written = beat.stat().st_size
    await asyncio.sleep(0.3)
    assert beat.stat().st_size == written


@pytest.mark.parametrize("branch", ["-m", "a b", "x..y", "../../elsewhere"])
async def test_a_branch_git_would_read_as_something_else_is_refused(
    repo: Path, tmp_path: Path, branch: str
) -> None:
    """A branch is a name, never an option: ``-m`` would rename the branch
    the repository has checked out."""
    before = _git(repo, "branch", "--show-current")
    runner = _runner(repo, WORK, worktrees=tmp_path / "kept")

    (done,) = await _posted(runner, _run(branch=branch))

    assert not done.ok and "is no branch name" in done.result
    assert _git(repo, "branch", "--show-current") == before
    assert not (tmp_path / "elsewhere").exists()


async def test_a_branch_whose_place_is_outside_the_worktrees_folder_is_refused(
    repo: Path, tmp_path: Path
) -> None:
    """A good name can still lead out: here a link in the folder does."""
    kept, outside = tmp_path / "kept", tmp_path / "outside"
    kept.mkdir()
    outside.mkdir()
    os.symlink(outside, kept / "out")

    (done,) = await _posted(_runner(repo, WORK, worktrees=kept), _run(branch="out/x"))

    assert not done.ok and "is no place under" in done.result
    assert list(outside.iterdir()) == []


async def test_a_worktree_git_will_not_make_says_why(
    repo: Path, tmp_path: Path
) -> None:
    """Git's own words, not that a command failed: here the branch is the
    one the repository itself has checked out."""
    run = _run(branch=_git(repo, "branch", "--show-current"))

    (done,) = await _posted(_runner(repo, WORK, worktrees=tmp_path / "kept"), run)

    assert not done.ok and "already" in done.result and "worktree" in done.result


async def test_a_folder_that_is_no_worktree_is_not_taken_for_one(
    repo: Path, tmp_path: Path
) -> None:
    """Something else is where the branch's worktree would go (a folder
    left behind, or the parent of another branch's): the run fails saying
    so rather than working in a folder git does not know."""
    stray = tmp_path / "kept" / "issue-9"
    stray.mkdir(parents=True)
    (stray / "leftover.txt").write_text("not a worktree\n")
    runner = _runner(repo, WORK, worktrees=tmp_path / "kept")

    (done,) = await _posted(runner, _run(branch="issue-9"))

    assert not done.ok and not (stray / "NOTES.md").exists()


async def test_a_kept_worktree_moved_off_its_branch_is_not_worked_in(
    repo: Path, tmp_path: Path
) -> None:
    """Someone took the worktree elsewhere: a follow-up asked on the branch
    would commit off it, so it says where the worktree is instead."""
    runner = _runner(repo, WORK, worktrees=tmp_path / "kept")
    await _posted(runner, _run(branch="issue-12"))
    _git(tmp_path / "kept" / "issue-12", "checkout", "-q", "--detach")

    (done,) = await _posted(runner, _run(prompt="again", branch="issue-12"))

    assert not done.ok and "not issue-12" in done.result
    assert (tmp_path / "kept" / "issue-12" / "NOTES.md").read_text().count("again") == 0


async def test_a_command_is_given_the_hooks_that_say_what_its_run_is_doing() -> None:
    """``{hooks}`` in a command is the agent's settings for the app the
    runner answers, whole in one argument; and however the runner was given
    its token, the hooks find it in the command's environment to sign with."""
    shows = _python(
        "import os, sys; print(sys.argv[1]); print(os.environ[sys.argv[2]])",
        "{hooks}",
        hooks.TOKEN_ENV,
    )

    (done,) = await _posted(_runner(None, shows), _run())

    given, token = done.result.splitlines()
    assert json.loads(given) == hooks.settings("http://app")
    assert token == "rnr_test"


async def test_a_runner_says_which_agent_it_runs() -> None:
    """The program its command starts with, by name: what a list of runs
    marks each run with."""
    asked: list[dict[str, Any]] = []
    claude = ["/usr/local/bin/claude", "-p", "{prompt}"]

    await _posted(_runner(None, claude), asked=asked)

    assert asked[0]["agent"] == "claude"
    assert _runner(None, []).agent is None  # nothing to name
