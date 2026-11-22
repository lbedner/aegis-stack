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

from app.components.runner import branches, client, hooks, protocol
from app.components.runner.client import Runner, run_once
from app.components.runner.protocol import CLAIM, Answer, ClaimedRun
from tests._runner import PULL

PROMPT = "Then Dana asked:\n\nCan the CSV export ship this week?"


def _on_branch(prompt: str) -> str:
    """What an agent is asked for work on a branch: the prompt, then to
    commit it (``COMMIT_ASKED``)."""
    return f"{prompt}\n\n{protocol.COMMIT_ASKED}"


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
    runner: Runner,
    *runs: dict[str, Any],
    asked: list[dict[str, Any]] | None = None,
    heard: list[dict[str, Any]] | None = None,
) -> list[Answer]:
    """What ``runner`` posts back for ``runs``, claimed one at a time until
    none waits; what it sent to claim each goes in ``asked``, the lines of
    its agent's session it posted as they came in ``heard``."""
    waiting, posted = list(runs), []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer rnr_test"
        body = json.loads(request.content)
        if request.url.path.endswith("/lines"):
            assert request.url.path == protocol.LINES.format(run_id=7)
            if heard is not None:
                heard.extend(body["lines"])
            return httpx.Response(204)
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
    assert asked[0]["actions"] == ["agent", protocol.PUSH]


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
    stdin = _python(
        "import sys; said = sys.stdin.read().splitlines(); print(said[0], said[-1])"
    )

    (done,) = await _posted(_runner(None, stdin), _run())

    assert (
        done.result == f"{protocol.NO_ANSWER_ASKED} Can the CSV export ship this week?"
    )


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
    assert (where / "NOTES.md").read_text() == f"{_on_branch('first')}\n"
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
    assert notes == f"{_on_branch('first')}\nresumed {_on_branch('second')}\n"
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
            f"resumed {_on_branch('go on')}",
            id="begun-in-a-run-the-app-never-heard-from",
        ),
        pytest.param(
            True,
            _python(SAYS, "started {prompt}"),
            _python("import sys; sys.exit('No conversation found')"),
            f"started {_on_branch('go on')}",
            id="never-begun-or-kept-on-another-machine",
        ),
        pytest.param(
            True,
            _python(SAYS, "started {prompt}"),
            _agent({"is_error": True, "total_cost_usd": 0, "errors": ["None"]}, code=1),
            f"started {_on_branch('go on')}",
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
    run = _run(prompt="go on", session_id="0f0f", resume=resume, branch="issue-12")
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
    asked_of = "explain the {session} and {prompt} placeholders"

    (done,) = await _posted(_runner(None, ASKED), _run(prompt=asked_of))

    assert done.result == f"{protocol.NO_ANSWER_ASKED}\n\n{asked_of}"


# Writes to the file it is given until it is killed.
BEATING = (
    "import sys, time\nwhile True:\n"
    "    open(sys.argv[1], 'a').write('.'); time.sleep(0.05)"
)


def _beats(beat: Path, *, deaf: bool = False) -> list[str]:
    """A command that writes to ``beat`` until it is killed; ``deaf`` to an
    interrupt, it writes from another it starts, as deaf."""
    if not deaf:
        return _python(BEATING, str(beat))
    return _python(
        "import signal, subprocess, sys, time; signal.signal(signal.SIGINT, signal.SIG_IGN);"
        " subprocess.Popen([sys.executable, '-c', *sys.argv[1:]]); time.sleep(30)",
        BEATING,
        str(beat),
    )


async def _stilled(beat: Path) -> None:
    """Nothing writes to ``beat`` any more: all that did was stopped."""
    await asyncio.sleep(0.2)
    written = beat.stat().st_size
    await asyncio.sleep(0.3)
    assert beat.stat().st_size == written


async def test_a_command_out_of_time_is_stopped_with_all_it_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command that outlives its time, and its interrupt, is killed with
    what it started: nothing of it goes on working in a worktree the next
    run will use."""
    monkeypatch.setattr(client, "INTERRUPT_SECONDS", 0.2)
    beat = tmp_path / "beat"
    began = time.monotonic()

    (done,) = await _posted(
        _runner(None, _beats(beat, deaf=True), timeout_seconds=1.0), _run()
    )

    assert not done.ok and "stopped after 1 seconds" in done.result
    assert time.monotonic() - began < 5
    await _stilled(beat)


# A coding agent at work that, interrupted (as Ctrl-C would), says what its
# session cost and goes, as Claude Code does in the middle of a tool.
INTERRUPTED = _python(
    "import json, signal, sys, time\n"
    "def said(*_):\n"
    "    print(json.dumps({'type': 'result', 'subtype': 'error_during_execution',"
    " 'is_error': True, 'total_cost_usd': 0.25}), flush=True)\n"
    "    sys.exit(130)\n"
    "signal.signal(signal.SIGINT, said)\n"
    "time.sleep(30)"
)


@pytest.mark.parametrize(
    ("limits", "said"),
    [
        ({"timeout_seconds": 1.0}, "stopped after 1 seconds"),
        (
            {"quiet_seconds": 0.5, "timeout_seconds": 30.0},
            "stopped after saying nothing for 0.5 seconds",
        ),
    ],
    ids=["out of time", "quiet too long"],
)
async def test_an_agent_out_of_time_says_what_it_cost_before_it_is_stopped(
    limits: dict[str, float], said: str
) -> None:
    """Interrupted first, an agent out of time, or quiet past its quiet
    limit (stuck), writes down what its session cost, which is kept; killed
    outright, it never could."""
    (done,) = await _posted(_runner(None, INTERRUPTED, **limits), _run())

    assert not done.ok and said in done.result
    assert done.cost == 0.25


async def test_a_command_at_work_keeps_its_time_as_long_as_it_says_something() -> None:
    """Its quiet limit counts from the last line it printed: one that
    prints as it goes outlives it (up to its runner's timeout)."""
    talks = _python(
        "import time\nfor _ in range(6):\n    print('.', flush=True); time.sleep(0.2)\nprint('done')"
    )

    (done,) = await _posted(_runner(None, talks, quiet_seconds=0.5), _run())

    assert done.ok and done.result.endswith("done")


async def test_a_runner_told_to_stop_while_its_command_is_interrupted_kills_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl-C in the grace an interrupted command is given still kills it
    and all it started."""
    monkeypatch.setattr(client, "INTERRUPT_SECONDS", 30.0)
    beat = tmp_path / "beat"
    runner = _runner(None, _beats(beat, deaf=True), timeout_seconds=0.5)
    answering = asyncio.create_task(_posted(runner, _run()))
    await asyncio.sleep(1.5)  # out of time, in its grace

    answering.cancel()
    with pytest.raises(asyncio.CancelledError):
        await answering

    await _stilled(beat)


async def test_a_runner_told_to_stop_stops_its_command(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Ctrl-C reaches the runner alone (its command is in a group of its
    own): the runner stops the command, at once, instead of leaving an
    agent at work with nobody to post its answer, and says nothing is
    wrong."""
    beat = tmp_path / "beat"
    answering = asyncio.create_task(_posted(_runner(None, _beats(beat)), _run()))
    while not beat.exists():
        await asyncio.sleep(0.05)

    answering.cancel()
    with pytest.raises(asyncio.CancelledError):
        await answering

    await _stilled(beat)
    assert not [record for record in caplog.records if record.name == "asyncio"]


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


async def test_an_agent_is_never_given_the_runners_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner alone pushes and reads GitHub: its token stays out of the
    command's environment, so an agent cannot push its own work."""
    monkeypatch.setenv(protocol.GITHUB_TOKEN_ENV, "ghp_test")
    shows = _python(
        "import os, sys; print(os.environ.get(sys.argv[1], 'none'))",
        protocol.GITHUB_TOKEN_ENV,
    )

    (done,) = await _posted(_runner(None, shows), _run())

    assert done.result == "none"


@pytest.mark.parametrize("branch", [None, "issue-12"])
async def test_a_command_is_given_the_hooks_that_say_what_its_run_is_doing(
    branch: str | None,
) -> None:
    """``{hooks}`` in a command is the agent's settings for the app the
    runner answers, whole in one argument; and however the runner was given
    its token, the hooks find it in the command's environment to sign with.
    Asked is not made sure: work on a branch's also hold its agent to
    committing (``commit``)."""
    shows = _python(
        "import os, sys; print(sys.argv[1]); print(os.environ[sys.argv[2]])",
        "{hooks}",
        hooks.TOKEN_ENV,
    )

    (done,) = await _posted(_runner(None, shows), _run(branch=branch))

    given, token = done.result.splitlines()
    assert json.loads(given) == hooks.settings("http://app", commit=bool(branch))
    assert token == "rnr_test"


async def test_a_runner_says_which_agent_it_runs() -> None:
    """The program its command starts with, by name: what a list of runs
    marks each run with."""
    asked: list[dict[str, Any]] = []
    claude = ["/usr/local/bin/claude", "-p", "{prompt}"]

    await _posted(_runner(None, claude), asked=asked)

    assert asked[0]["agent"] == "claude"
    assert _runner(None, []).agent is None  # nothing to name


# Commits what it was asked as NOTES.md where it runs, and answers as a
# coding agent does.
COMMIT = _python(
    "import json, subprocess, sys; open('NOTES.md', 'a').write(sys.argv[1] + chr(10));"
    " git = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t'];"
    " subprocess.run([*git, 'add', '-A'], check=True);"
    " subprocess.run([*git, 'commit', '-qm', 'Ship the export' + chr(10) + chr(10)"
    " + 'It ships on Thursdays.'], check=True);"
    " print(json.dumps({'result': 'Committed'}))",
    "{prompt}",
)


@pytest.fixture
def github(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``repo`` as the runner's clone has it for its remote, at a place
    named like GitHub's (``acme/app``), which a push over HTTPS reaches."""
    remote = tmp_path / "github.com" / "acme" / "app.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(remote)], check=True)
    monkeypatch.setattr(branches, "GITHUB_GIT", f"{tmp_path}/github.com/{{slug}}.git")
    return remote


@pytest.fixture
def clone(github: Path, tmp_path: Path) -> Path:
    path = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(github), str(path)], check=True)
    return path


@pytest.mark.parametrize(("command", "unpushed"), [(COMMIT, 1), (WORK, 0)])
async def test_a_run_on_a_branch_says_how_many_commits_are_not_on_the_remote(
    clone: Path, tmp_path: Path, command: list[str], unpushed: int
) -> None:
    """Counted by the runner, not the agent: what is left to push."""
    runner = _runner(clone, command, worktrees=tmp_path / "kept")

    (done,) = await _posted(runner, _run(branch="issue-12-export"))

    assert done.ok and done.unpushed == unpushed


async def test_a_branch_run_out_of_time_still_says_what_is_left_to_push(
    clone: Path, tmp_path: Path
) -> None:
    """Work committed before its time ran out is counted all the same, so
    it can still be pushed."""
    commits_then_works_on = _python(
        "import subprocess, sys, time; subprocess.run(sys.argv[1:], check=True);"
        " time.sleep(30)",
        *COMMIT,
    )
    runner = _runner(
        clone, commits_then_works_on, worktrees=tmp_path / "kept", timeout_seconds=3.0
    )

    (done,) = await _posted(runner, _run(branch="issue-12-export"))

    assert not done.ok and "stopped after 3 seconds" in done.result
    assert done.unpushed == 1


async def test_one_answer_says_nothing_of_what_to_push(repo: Path) -> None:
    (done,) = await _posted(_runner(repo, ANSWER), _run())

    assert done.unpushed is None


def _on_github(
    monkeypatch: pytest.MonkeyPatch, made: int = 201
) -> list[dict[str, Any]]:
    """The runner on GitHub with a token, its API that of ``acme/app``: its
    default branch, and a pull request opened (``made`` 201) or one already
    open for the branch (422). The pull requests it was sent."""
    sent: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ghp_test"
        if request.method == "POST":
            sent.append(json.loads(request.content))
            return httpx.Response(made, json={"html_url": PULL})
        if request.url.path == "/repos/acme/app/pulls":
            assert request.url.params["head"] == "acme:issue-12-export"
            return httpx.Response(
                200, json=[{"html_url": "https://github.com/acme/app/pull/4"}]
            )
        return httpx.Response(200, json={"default_branch": "main"})

    monkeypatch.setattr(client, "GITHUB_TRANSPORT", httpx.MockTransport(handle))
    monkeypatch.setenv(protocol.GITHUB_TOKEN_ENV, "ghp_test")
    return sent


@pytest.mark.parametrize(
    ("made", "url"),
    [
        (201, PULL),
        (422, "https://github.com/acme/app/pull/4"),
    ],
)
async def test_a_push_pushes_the_branch_and_opens_its_pull_request(
    clone: Path,
    github: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    made: int,
    url: str,
) -> None:
    """The runner pushes, never the agent: the branch over HTTPS with the
    token in its environment, then a pull request for it, its commits'
    message the body and what the app asked it to close at the end. A
    branch that has one open already is that one. The repository's hooks,
    which its agent may write, are not run with the token there."""
    hook = clone / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    sent = _on_github(monkeypatch, made)
    runner = _runner(clone, COMMIT, worktrees=tmp_path / "kept")
    work = _run(branch="issue-12-export")
    push = _run(
        action=protocol.PUSH, prompt="Closes acme/app#12", branch="issue-12-export"
    )

    done, pushed = await _posted(runner, work, push)

    assert pushed.ok and pushed.result == url and pushed.unpushed == 0
    assert (
        _git(github, "log", "-1", "--format=%s", "issue-12-export") == "Ship the export"
    )
    assert sent == [
        {
            "title": "Ship the export",
            "head": "issue-12-export",
            "base": "main",
            "body": "It ships on Thursdays.\n\nCloses acme/app#12",
        }
    ]


async def test_a_branch_moved_on_github_is_caught_up_before_its_next_turn(
    clone: Path, github: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pushed, then moved on GitHub (its base merged in there, say): the
    next turn starts from GitHub's branch, so the push after it goes."""
    _on_github(monkeypatch)
    runner = _runner(clone, COMMIT, worktrees=tmp_path / "kept")
    branch = "issue-12-export"
    push = _run(action=protocol.PUSH, prompt="", branch=branch)
    await _posted(runner, _run(branch=branch), push)
    elsewhere = tmp_path / "elsewhere"
    subprocess.run(
        ["git", "clone", "-q", "-b", branch, str(github), str(elsewhere)], check=True
    )
    (elsewhere / "MAIN.md").write_text("merged")
    _git(elsewhere, "add", "-A")
    _git(elsewhere, "commit", "-qm", "Merge main")
    _git(elsewhere, "push", "-q", "origin", branch)

    done, pushed = await _posted(runner, _run(branch=branch, prompt="Again."), push)

    assert done.ok and pushed.ok, pushed.result
    said = _git(github, "log", "--format=%s", branch).splitlines()
    assert said == ["Ship the export", "Merge main", "Ship the export", "first"]


def test_git_is_told_nobody_is_there_to_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its credential prompt reads the terminal, not stdin: a fetch that
    GitHub refuses fails at once instead of waiting out ``GIT_SECONDS``."""
    given: dict[str, Any] = {}

    def ran(argv: list[str], **how: Any) -> subprocess.CompletedProcess[str]:
        given.update(how["env"] or {})
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(branches.subprocess, "run", ran)

    branches.git(Path("."), "status")

    assert given["GIT_TERMINAL_PROMPT"] == "0"


async def test_a_push_without_a_github_token_says_what_is_missing(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(protocol.GITHUB_TOKEN_ENV, raising=False)
    runner = _runner(clone, COMMIT, worktrees=tmp_path / "kept")
    push = _run(action=protocol.PUSH, prompt="", branch="issue-12-export")

    (pushed,) = await _posted(runner, push)

    assert not pushed.ok and protocol.GITHUB_TOKEN_ENV in pushed.result


@pytest.mark.parametrize(
    ("branch", "broken", "said"),
    [
        ("../clone", None, "WorktreeRefusedError"),
        (
            "issue-12-export",
            subprocess.TimeoutExpired("git push", 60),
            "TimeoutExpired",
        ),
        ("issue-12-export", OSError("no git"), "OSError"),
    ],
)
async def test_a_push_that_cannot_go_says_why_and_the_runner_goes_on(
    clone: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch: str,
    broken: Exception | None,
    said: str,
) -> None:
    """Pushed only from a worktree this runner keeps; git timing out or
    missing fails the push, never the runner."""
    monkeypatch.setenv(protocol.GITHUB_TOKEN_ENV, "ghp_test")
    if broken is not None:

        def fails(*_: Any, **__: Any) -> None:
            raise broken

        monkeypatch.setattr(branches, "push", fails)
    runner = _runner(clone, COMMIT, worktrees=tmp_path / "kept")
    work = _run(branch="issue-12-export")
    push = _run(action=protocol.PUSH, prompt="", branch=branch)

    _, pushed = await _posted(runner, work, push)

    assert not pushed.ok and said in pushed.result


# Prints what it is asked, whole.
ASKED = _python("import sys; print(sys.argv[1])", "{prompt}")


@pytest.mark.parametrize(
    ("branch", "asked"),
    [
        (None, f"{protocol.NO_ANSWER_ASKED}\n\n{PROMPT}"),
        ("issue-12", _on_branch(PROMPT)),
    ],
)
async def test_what_an_agent_is_asked_says_how_its_turn_ends(
    branch: str | None, asked: str
) -> None:
    """A question is asked to say when it has no answer. Work on a branch
    is done, not an answer: it is asked to be committed, the push left to
    its owner (a Push sends a branch's commits)."""
    (done,) = await _posted(_runner(None, ASKED), _run(branch=branch))

    assert done.result == asked


@pytest.mark.parametrize(
    ("says", "result", "unanswered"),
    [
        ("It ships Thursday.", "It ships Thursday.", False),
        ("Nothing in the notes.\n[no answer]", "Nothing in the notes.", True),
        ("Nothing in the notes.\n\n**`[no answer]`**", "Nothing in the notes.", True),
        ("[no answer]", "", True),
    ],
)
async def test_an_agent_that_says_it_has_no_answer_is_heard(
    says: str, result: str, unanswered: bool
) -> None:
    """Its mark is read off what it said, however it dressed it, and what
    it said is kept."""
    (done,) = await _posted(_runner(None, _python(SAYS, says)), _run())

    assert (done.ok, done.result, done.unanswered) == (True, result, unanswered)


# A Claude Code session as stream-json prints it, as a real one did: its
# own events, a thought, a tool called and what it gave back, what it said,
# then the result the run reads.
SESSION = [
    {"type": "system", "subtype": "init", "session_id": "0f0f"},
    {
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": ""}]},
    },
    {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Bash",
                    "input": {"command": "echo hello-from-tool"},
                }
            ]
        },
    },
    {"type": "rate_limit_event"},
    {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "hello-from-tool",
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_2",
                    "content": [
                        {"type": "text", "text": "line one"},
                        {"type": "text", "text": "line two"},
                    ],
                },
            ]
        },
    },
    {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "It printed hello."}]},
    },
    {
        "type": "result",
        "subtype": "success",
        "result": "It printed hello.",
        "total_cost_usd": 0.01,
    },
]
STREAMS = _python(
    "import sys; sys.stdout.write(sys.argv[1])",
    "".join(json.dumps(event) + "\n" for event in SESSION),
)


async def test_an_agents_session_is_posted_as_it_goes_and_its_result_is_the_answer() -> (
    None
):
    """What it said, each tool it called with what it was given, and what
    the tool gave back, in order; its own events and thoughts are not."""
    heard: list[dict[str, Any]] = []

    (done,) = await _posted(_runner(None, STREAMS), _run(), heard=heard)

    assert (done.ok, done.result) == (True, "It printed hello.")
    assert heard == [
        {"kind": protocol.CALLED, "text": 'Bash {"command": "echo hello-from-tool"}'},
        {"kind": protocol.RETURNED, "text": "hello-from-tool"},
        {"kind": protocol.RETURNED, "text": "line one\nline two"},
        {"kind": protocol.SAID, "text": "It printed hello."},
    ]


async def test_a_command_that_prints_no_session_posts_none() -> None:
    heard: list[dict[str, Any]] = []

    await _posted(_runner(None, _python(SAYS, "Yes.")), _run(), heard=heard)

    assert heard == []


async def test_an_answer_followed_by_a_stray_line_is_still_read() -> None:
    late = _python(SAYS + "; print('a warning, late')", "Yes.")

    (done,) = await _posted(_runner(None, late), _run())

    assert (done.ok, done.result, done.cost) == (True, "Yes.", 0.1)


async def test_a_line_too_long_to_read_fails_the_run_not_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client, "LONGEST_LINE", 64)
    long = _python("print('x' * 1000)")

    first, second = await _posted(_runner(None, long), _run(), _run())

    assert not first.ok and not second.ok and "ValueError" in first.result


async def test_a_command_that_never_reads_its_prompt_still_answers() -> None:
    """A prompt too big for the pipe, written to a command that does not
    read it, is no failure of the command's."""
    deaf = _python("print('ok')")

    (done,) = await _posted(_runner(None, deaf), _run(prompt="x" * 1_000_000))

    assert (done.ok, done.result) == (True, "ok")
