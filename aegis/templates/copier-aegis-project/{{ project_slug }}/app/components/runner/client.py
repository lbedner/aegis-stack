"""The runner: a process on another machine that claims runs over the
app's API, runs a command for each, and posts back what it printed.

It holds a runner token, never a session, and talks only HTTP
(``protocol``), so it runs wherever the repository and the agent's login
are (``runner run``). The command is any headless one: ``{prompt}`` in it
is replaced by the run's prompt (without it the prompt goes on stdin),
``{session}`` by the agent's session id (the run's; one made here for an
app from before it gave every run one), and ``{hooks}`` by the settings
that make the agent say what it is doing (``hooks``).

A run that asks one thing gets a fresh worktree of ``repo`` at ``ref``
(none without a repository), so the command answers from the code as it
is, never from whatever branch is checked out, and changes nothing that
stays. A run that is work names a branch: its worktree is kept (``_kept``),
and a later run of its session continues there (``_forms``). What a
coding agent answers is read for what it cost (``_read``).
"""

import asyncio
from collections.abc import Iterator
import contextlib
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from uuid import uuid4

import httpx

from app.core.log import logger

from . import hooks
from .protocol import (
    MOST_AGENT,
    RUNS,
    TIMEOUT_SECONDS,
    Answer,
    ClaimedRun,
    ClaimRequest,
    kept,
)

PLACEHOLDER = "{prompt}"
SESSION = "{session}"
HOOKS = "{hooks}"
_PLACES = re.compile("|".join(map(re.escape, (PLACEHOLDER, SESSION, HOOKS))))
# An agent that will not start or resume a session says so at once: a
# command that fails later than this was working, and is not tried again.
REFUSAL_SECONDS = 30.0
# What git is given for one step (a fetch that waits on a prompt or a dead
# network would otherwise hold the runner for good).
GIT_SECONDS = 60.0


@dataclass(frozen=True)
class Runner:
    url: str
    token: str
    actions: list[str]
    command: list[str]
    repo: Path | None = None
    ref: str = "origin/main"
    poll_seconds: float = 5.0
    timeout_seconds: float = TIMEOUT_SECONDS
    # What continues a session an agent began; without one every run runs
    # ``command``.
    resume_command: list[str] | None = None
    # Where kept worktrees go, each under its branch's name; beside the
    # repository (``<repo>-worktrees``) unless said.
    worktrees: Path | None = None

    @property
    def agent(self) -> str | None:
        """The agent this runner runs: the program its command starts, by
        name (``claude``), cut to what a run keeps of it.

        ponytail: a command that starts something else first (``npx``,
        ``sh -c``) names that; an ``--agent`` of its own when one does."""
        return Path(self.command[0]).name[:MOST_AGENT] if self.command else None

    @property
    def home(self) -> Path | None:
        """The folder kept worktrees go under; none without a repository."""
        if self.repo is None:
            return None
        beside = self.repo.parent / f"{self.repo.name}-worktrees"
        return (self.worktrees or beside).resolve()


class WorktreeRefusedError(ValueError):
    """The branch is no branch name, names a place outside the worktrees
    folder, or its worktree is on something else."""


async def run_forever(runner: Runner) -> None:
    """Claim and answer runs until stopped, looking again every
    ``poll_seconds`` while nothing waits."""
    while True:
        try:
            if await run_once(runner):
                continue
        except httpx.HTTPError as exc:
            logger.warning("The app did not answer the runner", error=str(exc))
        await asyncio.sleep(runner.poll_seconds)


async def run_once(
    runner: Runner, transport: httpx.AsyncBaseTransport | None = None
) -> bool:
    """Claim one run and answer it; False when none waits."""
    asking = ClaimRequest(
        actions=runner.actions,
        agent=runner.agent,
        worktrees=str(runner.home) if runner.home else None,
        timeout=runner.timeout_seconds,
    )
    async with httpx.AsyncClient(
        base_url=runner.url.rstrip("/"),
        headers={"Authorization": f"Bearer {runner.token}"},
        transport=transport,
        timeout=30.0,
    ) as api:
        claimed = await api.post(f"{RUNS}/claim", json=asking.model_dump())
        claimed.raise_for_status()
        if claimed.status_code == 204:
            return False
        run = ClaimedRun.model_validate(claimed.json())
        logger.info("Run claimed", run_id=run.id, action=run.action)
        answer = await _answer(runner, run)
        said = kept(answer.result, answer.ok)
        finished = await api.post(
            f"{RUNS}/{run.id}/finish",
            json=answer.model_copy(update={"result": said}).model_dump(),
        )
        finished.raise_for_status()
        return True


async def _answer(runner: Runner, run: ClaimedRun) -> Answer:
    """The run's answer: what its command came back with where it ran, or
    why it could not run, and where its work is kept."""
    kept: str | None = None
    try:
        with _worktree(runner, run.branch) as cwd:
            kept = str(cwd) if cwd and run.branch else None
            answer = await _asked(runner, run, cwd)
    except subprocess.CalledProcessError as exc:  # git, saying why
        answer = Answer(ok=False, result=(exc.stderr or "").strip() or str(exc))
    except (OSError, subprocess.SubprocessError, WorktreeRefusedError) as exc:
        answer = Answer(ok=False, result=f"{type(exc).__name__}: {exc}")
    return answer.model_copy(update={"worktree": kept})


async def _asked(runner: Runner, run: ClaimedRun, cwd: Path | None) -> Answer:
    """What the run's command came back with. A session's second form
    (``_forms``) is tried only when the first refused: it failed at once,
    without an agent's answer that cost anything. A command that worked and
    then failed is not run again. Where every form refused, the answer is
    what each said, so the second refusal never hides the first."""
    refused: list[Answer] = []
    for form in _forms(runner, run):
        began = time.monotonic()
        code, printed, errors = await _ran(runner, form, run, cwd)
        said = _read(printed)
        if said is not None:
            answer = said.model_copy(update={"ok": said.ok and code == 0})
        elif code != 0:
            why = (errors or printed).strip() or f"exit {code}"
            answer = Answer(ok=False, result=why)
        else:
            answer = Answer(ok=True, result=printed.strip())
        at_once = time.monotonic() - began < REFUSAL_SECONDS
        answered = said is not None and (said.ok or bool(said.cost))
        if code == 0 or answered or not at_once:
            return answer
        refused.append(answer)
    whys = "\n".join(dict.fromkeys(answer.result for answer in refused))
    return refused[-1].model_copy(update={"result": whys})


def _forms(runner: Runner, run: ClaimedRun) -> list[list[str]]:
    """The commands to try for a run, in order. One that names a session
    has two where the runner can resume: the form the app expects (start,
    or resume once a runner took the session before), then the other, as
    whether a session is one to start or to continue is the agent's to
    say (the earlier run may never have reached it, or it is kept on
    another machine)."""
    if not run.session_id or runner.resume_command is None:
        return [runner.command]
    forms = [runner.command, runner.resume_command]
    return forms[::-1] if run.resume else forms


async def _ran(
    runner: Runner, command: list[str], run: ClaimedRun, cwd: Path | None
) -> tuple[int, str, str]:
    """``command`` run for the run where it is to run, its places filled in
    one pass (a prompt that names one is left as it was asked): its exit
    code and what it printed. It runs in a process group of its own, so
    one that outlives ``timeout_seconds``, or whose runner is told to stop,
    is stopped with everything it started, and nothing of it goes on
    working in a kept worktree. Its environment carries the runner's token,
    for the agent's hooks to sign what they post (``hooks``)."""
    said = {
        PLACEHOLDER: run.prompt,
        SESSION: run.session_id or str(uuid4()),
        HOOKS: json.dumps(hooks.settings(runner.url)),
    }
    argv = [_PLACES.sub(lambda place: said[place.group()], part) for part in command]
    takes_prompt = any(PLACEHOLDER in part for part in command)
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL if takes_prompt else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env={**os.environ, hooks.TOKEN_ENV: runner.token},
    )
    try:
        async with asyncio.timeout(runner.timeout_seconds):
            printed, errors = await process.communicate(
                None if takes_prompt else run.prompt.encode()
            )
    except (TimeoutError, asyncio.CancelledError) as exc:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        if isinstance(exc, TimeoutError):
            given = f"{runner.timeout_seconds:g} seconds"
            raise TimeoutError(f"The command was stopped after {given}") from None
        raise
    return (
        process.returncode or 0,
        printed.decode(errors="replace"),
        errors.decode(errors="replace"),
    )


def _read(printed: str) -> Answer | None:
    """A coding agent's own answer in what a command printed (one JSON
    object, last if anything came before it, that is a ``result`` or says
    its ``total_cost_usd``): what it said, or failing why (its ``errors``,
    else the kind of failure), whether it ``is_error``, and what its
    session has cost (where that is an amount). None for anything else:
    plain output."""
    text = printed.strip()
    for candidate in (text, text.rpartition("\n")[2]):
        try:
            said = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(said, dict) and (
            said.get("type") == "result" or "total_cost_usd" in said
        ):
            break
    else:
        return None
    cost = said.get("total_cost_usd")
    why = "\n".join(map(str, said.get("errors") or [])) or said.get("subtype")
    numbered = (
        isinstance(cost, int | float)
        and not isinstance(cost, bool)
        and math.isfinite(cost)
        and cost >= 0
    )
    return Answer(
        ok=not said.get("is_error"),
        result=str(said.get("result") or why or ""),
        cost=cost if numbered else None,
    )


@contextmanager
def _worktree(runner: Runner, branch: str | None) -> Iterator[Path | None]:
    """Where a run runs: the kept worktree of its ``branch``, a fresh one
    removed after, or (no repository) nowhere of its own."""
    if runner.repo is None or runner.home is None:
        yield None
    elif branch:
        yield _kept(runner.repo, runner.ref, runner.home, branch)
    else:
        with _fresh(runner.repo, runner.ref) as path:
            yield path


def _git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """``git`` in ``repo``, with nobody to ask and ``GIT_SECONDS`` to
    answer; a refusal raises with what git said."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=check,
        timeout=GIT_SECONDS,
    )


def _fetch(repo: Path) -> None:
    """What the remote has now, where it can be reached in time."""
    with contextlib.suppress(subprocess.TimeoutExpired):
        _git(repo, "fetch", "--quiet", check=False)


def _add(repo: Path, *how: str) -> None:
    """A worktree of ``repo`` added as ``how`` says, any that were deleted
    by hand forgotten first."""
    _git(repo, "worktree", "prune", check=False)
    _git(repo, "worktree", "add", "--quiet", *how)


def _has(repo: Path, ref: str) -> bool:
    return (
        _git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0
    )


def _kept(repo: Path, ref: str, home: Path, branch: str) -> Path:
    """The worktree kept for ``branch`` under ``home``: found there, still
    on it, or made the first time, on the branch as the repository or its
    remote has it, else on a new one from ``ref``. ``branch`` is the app's
    word: only a branch name is taken (never an option to git), and only
    for a place under ``home``."""
    if _git(repo, "check-ref-format", "--branch", branch, check=False).returncode:
        raise WorktreeRefusedError(f"{branch!r} is no branch name")
    path = (home / branch).resolve()
    if not path.is_relative_to(home):
        raise WorktreeRefusedError(f"{branch!r} is no place under {home}")
    if (path / ".git").exists():
        on = _git(path, "symbolic-ref", "--short", "--quiet", "HEAD", check=False)
        if on.stdout.strip() != branch:
            raise WorktreeRefusedError(
                f"{path} is on {on.stdout.strip() or 'no branch'}, not {branch}"
            )
        return path
    _fetch(repo)
    there = _has(repo, f"refs/heads/{branch}") or _has(
        repo, f"refs/remotes/origin/{branch}"
    )
    _add(
        repo,
        *(
            [str(path), branch]
            if there
            else ["--no-track", "-b", branch, str(path), ref]
        ),
    )
    return path


@contextmanager
def _fresh(repo: Path, ref: str) -> Iterator[Path]:
    """A fresh worktree of ``repo`` at ``ref``, removed after."""
    _fetch(repo)
    with tempfile.TemporaryDirectory(prefix="runner-run-") as parent:
        path = Path(parent) / "worktree"
        _add(repo, "--detach", str(path), ref)
        try:
            yield path
        finally:
            _git(repo, "worktree", "remove", "--force", str(path), check=False)
