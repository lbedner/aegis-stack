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
stays. A run that is work names a branch: its worktree is kept (``branches.kept``),
and a later run of its session continues there (``_forms``). What a
coding agent answers is read for what it cost (``transcript.read``).
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
import contextlib
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Any
from uuid import uuid4

import httpx

from app.core.log import logger

from . import branches, hooks, transcript
from .protocol import (
    CLAIM,
    COMMIT_ASKED,
    FINISH,
    GITHUB_REPO,
    GITHUB_TOKEN_ENV,
    LINES,
    MOST_AGENT,
    MOST_LINES,
    NO_ANSWER_ASKED,
    NO_ANSWER_MARK,
    PUSH,
    TIMEOUT_SECONDS,
    Answer,
    ClaimedRun,
    ClaimRequest,
    Line,
    Lines,
    kept,
)

PLACEHOLDER = "{prompt}"
SESSION = "{session}"
HOOKS = "{hooks}"
_PLACES = re.compile("|".join(map(re.escape, (PLACEHOLDER, SESSION, HOOKS))))
# An agent that will not start or resume a session says so at once: a
# command that fails later than this was working, and is not tried again.
REFUSAL_SECONDS = 30.0
# How often what an agent's session says is posted while it goes, at most,
# and the longest line of it a runner reads (a tool's whole output, in
# stream-json, is one line).
TELL_SECONDS = 1.0
LONGEST_LINE = 2**24
# How long a command out of time is given, once interrupted (as Ctrl-C
# would), to go on its own: Claude Code writes down what its session cost
# (its ``result``), which a command killed outright never can.
INTERRUPT_SECONDS = 10.0
# How long a command is given to say nothing (an agent stuck, not one at
# work): each line it prints gives it that long again, up to its runner's
# ``timeout_seconds``. Longer than any one tool call of Claude Code's.
QUIET_SECONDS = 1200.0
# Where what an agent's session says goes: posted to its run (``run_once``).
Tell = Callable[[list[Line]], Awaitable[None]]
GITHUB_API = "https://api.github.com"
GITHUB_TRANSPORT: httpx.AsyncBaseTransport | None = None
NO_GITHUB_TOKEN = (
    f"No {GITHUB_TOKEN_ENV} where this runner runs: it pushes with a GitHub "
    "token for the repository (Contents and Pull requests, read and write)."
)


class OutOfTimeError(TimeoutError):
    """A command stopped ``after`` its time, or after saying nothing for its
    quiet limit, with what it ``printed`` by then (``_ran``)."""

    def __init__(self, after: str, printed: str) -> None:
        super().__init__(f"The command was stopped after {after} seconds")
        self.printed = printed


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
    quiet_seconds: float = QUIET_SECONDS
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
        actions=list(dict.fromkeys([*runner.actions, PUSH])),
        agent=runner.agent,
        worktrees=str(runner.home) if runner.home else None,
        timeout=runner.timeout_seconds,
    )
    async with _client(runner.url.rstrip("/"), runner.token, transport) as api:
        claimed = await api.post(CLAIM, json=asking.model_dump())
        claimed.raise_for_status()
        if claimed.status_code == 204:
            return False
        run = ClaimedRun.model_validate(claimed.json())
        logger.info("Run claimed", run_id=run.id, action=run.action)

        async def tell(lines: list[Line]) -> None:
            """``lines`` posted to the run; one that cannot be is lost,
            never the run (its answer still comes back)."""
            where = LINES.format(run_id=run.id)
            for start in range(0, len(lines), MOST_LINES):
                batch = Lines(lines=lines[start : start + MOST_LINES])
                try:
                    (await api.post(where, json=batch.model_dump())).raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning("Session not posted", run_id=run.id, error=str(exc))

        answer = await _answer(runner, run, tell)
        said = kept(answer.result, answer.ok)
        finished = await api.post(
            FINISH.format(run_id=run.id),
            json=answer.model_copy(update={"result": said}).model_dump(),
        )
        finished.raise_for_status()
        return True


async def _answer(runner: Runner, run: ClaimedRun, tell: Tell) -> Answer:
    """The run's answer: what its command came back with where it ran, or
    why it could not run, and where its work is kept. A push is the
    runner's own (``_pushed``), failing the same ways."""
    kept: str | None = None
    unpushed: int | None = None
    try:
        if run.action == PUSH:
            return await _pushed(runner, run)
        with _worktree(runner, run.branch) as cwd:
            kept = str(cwd) if cwd and run.branch else None
            answer = _marked(await _asked(runner, run, cwd, tell))
            if cwd and kept:
                unpushed = branches.unpushed(cwd)
    except subprocess.CalledProcessError as exc:  # git, saying why
        answer = Answer(ok=False, result=(exc.stderr or "").strip() or str(exc))
    # A worktree refused, or a line too long to read (both ValueErrors).
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        answer = Answer(ok=False, result=f"{type(exc).__name__}: {exc}")
    return answer.model_copy(update={"worktree": kept, "unpushed": unpushed})


def _marked(answer: Answer) -> Answer:
    """``answer`` with its agent's mark of having none read off it: the
    last line of what it said (``NO_ANSWER_MARK``, however it is dressed),
    which is not kept. Only a question is asked for one (``_ran``)."""
    said, _, last = answer.result.rstrip().rpartition("\n")
    if not answer.ok or last.strip(" *`_") != NO_ANSWER_MARK:
        return answer
    return answer.model_copy(update={"result": said.rstrip(), "unanswered": True})


def _client(
    url: str, token: str, transport: httpx.AsyncBaseTransport | None
) -> httpx.AsyncClient:
    """An API at ``url``, sent ``token``."""
    return httpx.AsyncClient(
        base_url=url,
        headers={"Authorization": f"Bearer {token}"},
        transport=transport,
        timeout=30.0,
    )


async def _pushed(runner: Runner, run: ClaimedRun) -> Answer:
    """The run's branch pushed from the worktree this runner keeps for it,
    and its pull request opened (or the one already open): its link. The
    title and body are the commits' not yet pushed (the latest one's, when
    all are), then the run's prompt; the token goes to git in its
    environment, never on a command line or in what is said back.

    ponytail: any of the owner's runners may claim a push; one without the
    token or the worktree says so. Claiming it by the runner that ran the
    work (its token), when owners run several."""
    token = os.environ.get(GITHUB_TOKEN_ENV)
    if not token:
        return Answer(ok=False, result=NO_GITHUB_TOKEN)
    if runner.repo is None or runner.home is None or not run.branch:
        return Answer(ok=False, result="This runner keeps no worktrees")
    path = branches.place(runner.repo, runner.home, run.branch)
    if not (path / ".git").exists():
        return Answer(ok=False, result=f"No worktree of {run.branch} on this runner")
    origin, slug = _on_github(path)
    if slug is None:
        return Answer(ok=False, result=f"Its remote is not on GitHub: {origin}")
    branch = run.branch
    branches.catch_up(path, slug, branch, token)
    said = branches.git(
        path, "log", "--reverse", "--format=%B", *branches.UNPUSHED
    ).stdout.strip()
    said = said or branches.git(path, "log", "-1", "--format=%B").stdout.strip()
    title, _, body = said.partition("\n")
    branches.push(path, slug, branch, token)
    try:
        async with _client(GITHUB_API, token, GITHUB_TRANSPORT) as github:
            about = "\n\n".join(filter(None, (body.strip(), run.prompt.strip())))
            url = await branches.pull_request(
                github, slug, branch, title.strip(), about
            )
    except httpx.HTTPError as exc:
        return Answer(ok=False, result=f"GitHub did not open it: {exc}")
    return Answer(ok=True, result=url, worktree=str(path), unpushed=0)


def _on_github(path: Path) -> tuple[str, str | None]:
    """A worktree's remote, and the repository on GitHub it is
    (``owner/name``); None for one elsewhere."""
    origin = branches.git(
        path, "remote", "get-url", "origin", check=False
    ).stdout.strip()
    found = re.search(rf"github\.com[:/]({GITHUB_REPO})(?:\.git)?$", origin)
    return origin, found.group(1) if found else None


async def _asked(
    runner: Runner, run: ClaimedRun, cwd: Path | None, tell: Tell
) -> Answer:
    """What the run's command came back with. A session's second form
    (``_forms``) is tried only when the first refused: it failed at once,
    without an agent's answer that cost anything. A command that worked and
    then failed is not run again. Where every form refused, the answer is
    what each said, so the second refusal never hides the first."""
    refused: list[Answer] = []
    for form in _forms(runner, run):
        began = time.monotonic()
        try:
            code, printed, errors = await _ran(runner, form, run, cwd, tell)
        except OutOfTimeError as exc:  # failed, but what it cost is kept
            said = transcript.read(exc.printed)
            return Answer(ok=False, result=str(exc), cost=said.cost if said else None)
        said = transcript.read(printed)
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
    runner: Runner, command: list[str], run: ClaimedRun, cwd: Path | None, tell: Tell
) -> tuple[int, str, str]:
    """``command`` run for the run where it is to run, its places filled in
    one pass (a prompt that names one is left as it was asked): its exit
    code and what it printed, read as it prints it, what an agent's session
    says told as it comes (``_out``). It runs in a process group of its own, so
    one that outlives ``timeout_seconds``, says nothing for
    ``quiet_seconds``, or whose runner is told to stop, is stopped with
    everything it started, and nothing of it goes on working in a kept
    worktree; one out of time is interrupted first (``_interrupted``).
    Its environment carries the runner's token,
    for the agent's hooks to sign what they post (``hooks``), and never
    its GitHub token: the runner alone pushes."""
    asked = (
        f"{run.prompt}\n\n{COMMIT_ASKED}"
        if run.branch
        else f"{NO_ANSWER_ASKED}\n\n{run.prompt}"
    )
    said = {
        PLACEHOLDER: asked,
        SESSION: run.session_id or str(uuid4()),
        HOOKS: json.dumps(hooks.settings(runner.url, commit=bool(run.branch))),
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
        env={k: v for k, v in os.environ.items() if k != GITHUB_TOKEN_ENV}
        | {hooks.TOKEN_ENV: runner.token},
        limit=LONGEST_LINE,
    )
    printed: list[str] = []
    silence = asyncio.timeout(runner.quiet_seconds)

    def alive() -> None:
        """A line printed: as long again to print the next."""
        # Not once its time is up (what it prints as it goes is still read).
        with contextlib.suppress(RuntimeError):
            silence.reschedule(asyncio.get_running_loop().time() + runner.quiet_seconds)

    async def reads() -> list[Any]:
        return await asyncio.gather(
            _out(process.stdout, tell, printed, alive),  # type: ignore[arg-type]
            process.stderr.read(),  # type: ignore[union-attr]
            _give(process.stdin, asked),
        )

    # A task, so one cancelled when the runner is told to stop goes quietly.
    reading = asyncio.create_task(reads())
    try:
        async with asyncio.timeout(runner.timeout_seconds), silence:
            _, errors, _ = await asyncio.shield(reading)
            await process.wait()
    except TimeoutError:
        await _interrupted(process, reading)
        after = (
            f"saying nothing for {runner.quiet_seconds:g}"
            if silence.expired()
            else f"{runner.timeout_seconds:g}"
        )
        raise OutOfTimeError(after, "".join(printed)) from None
    finally:  # stopped (in its grace too), out of time, or unreadable
        if process.returncode is None:
            _signal(process, signal.SIGKILL)
        reading.cancel()
    return (process.returncode or 0, "".join(printed), errors.decode(errors="replace"))


async def _interrupted(
    process: asyncio.subprocess.Process, reading: asyncio.Task[list[Any]]
) -> None:
    """A command out of time interrupted first, with all it started, and
    given ``INTERRUPT_SECONDS`` to go (an agent says what it cost), then
    killed, and what it printed read to the end where that comes in time."""
    _signal(process, signal.SIGINT)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), INTERRUPT_SECONDS)
    _signal(process, signal.SIGKILL)
    # Its pipes close with it, so what it printed is read to the end.
    with contextlib.suppress(TimeoutError, ValueError):
        await asyncio.wait_for(reading, INTERRUPT_SECONDS)


def _signal(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
    """``sig`` sent to ``process`` and all it started (its group)."""
    # Gone already: Linux says no such group, macOS that it is not ours.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, sig)


async def _give(stdin: asyncio.StreamWriter | None, asked: str) -> None:
    """``asked`` to a command that reads its prompt from stdin."""
    if stdin is None:
        return
    # One that never reads it may have shut its end: no fault of its own.
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        stdin.write(asked.encode())
        await stdin.drain()
        stdin.close()


async def _out(
    stdout: asyncio.StreamReader,
    tell: Tell,
    printed: list[str],
    alive: Callable[[], None],
) -> None:
    """What a command prints, read a line at a time into ``printed`` (so
    what was read is kept whatever stops the reading), each one saying it
    is still ``alive``; what an agent's session says in it (``transcript.heard``)
    told at most every ``TELL_SECONDS``, and the rest once it is done: by a
    sender of its own, in order, so the agent never waits on the app to go
    on printing."""
    batches: asyncio.Queue[list[Line] | None] = asyncio.Queue()

    async def send() -> None:
        while (batch := await batches.get()) is not None:
            await tell(batch)

    sender = asyncio.create_task(send())
    heard: list[Line] = []
    told = time.monotonic()
    try:
        async for raw in stdout:
            alive()
            printed.append(raw.decode(errors="replace"))
            heard += transcript.heard(printed[-1])
            if heard and time.monotonic() - told >= TELL_SECONDS:
                batches.put_nowait(heard)
                heard, told = [], time.monotonic()
    except BaseException:
        sender.cancel()
        raise
    if heard:
        batches.put_nowait(heard)
    batches.put_nowait(None)
    await sender


@contextmanager
def _worktree(runner: Runner, branch: str | None) -> Iterator[Path | None]:
    """Where a run runs: the kept worktree of its ``branch``, a fresh one
    removed after, or (no repository) nowhere of its own."""
    if runner.repo is None or runner.home is None:
        yield None
    elif branch:
        path = branches.kept(runner.repo, runner.ref, runner.home, branch)
        if slug := _on_github(path)[1]:  # moved on there since: from there
            branches.catch_up(path, slug, branch, os.environ.get(GITHUB_TOKEN_ENV))
        yield path
    else:
        with branches.fresh(runner.repo, runner.ref) as path:
            yield path
