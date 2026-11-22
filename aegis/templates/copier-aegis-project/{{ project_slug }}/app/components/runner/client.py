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
coding agent answers is read for what it cost (``_read``).
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
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
import time
from typing import Any
from uuid import uuid4

import httpx

from app.core.log import logger

from . import branches, hooks
from .protocol import (
    CALLED,
    CLAIM,
    FINISH,
    GITHUB_REPO,
    GITHUB_TOKEN_ENV,
    LINES,
    MOST_AGENT,
    MOST_LINE,
    MOST_LINES,
    NO_ANSWER_ASKED,
    NO_ANSWER_MARK,
    PUSH,
    RETURNED,
    SAID,
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
# Where what an agent's session says goes: posted to its run (``run_once``).
Tell = Callable[[list[Line]], Awaitable[None]]
GITHUB_API = "https://api.github.com"
GITHUB_TRANSPORT: httpx.AsyncBaseTransport | None = None
NO_GITHUB_TOKEN = (
    f"No {GITHUB_TOKEN_ENV} where this runner runs: it pushes with a GitHub "
    "token for the repository (Contents and Pull requests, read and write)."
)


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
    origin = branches.git(
        path, "remote", "get-url", "origin", check=False
    ).stdout.strip()
    found = re.search(rf"github\.com[:/]({GITHUB_REPO})(?:\.git)?$", origin)
    if found is None:
        return Answer(ok=False, result=f"Its remote is not on GitHub: {origin}")
    slug, branch = found.group(1), run.branch
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
        code, printed, errors = await _ran(runner, form, run, cwd, tell)
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
    runner: Runner, command: list[str], run: ClaimedRun, cwd: Path | None, tell: Tell
) -> tuple[int, str, str]:
    """``command`` run for the run where it is to run, its places filled in
    one pass (a prompt that names one is left as it was asked): its exit
    code and what it printed, read as it prints it, what an agent's session
    says told as it comes (``_out``). It runs in a process group of its own, so
    one that outlives ``timeout_seconds``, or whose runner is told to stop,
    is stopped with everything it started, and nothing of it goes on
    working in a kept worktree. Its environment carries the runner's token,
    for the agent's hooks to sign what they post (``hooks``)."""
    asked = run.prompt if run.branch else f"{NO_ANSWER_ASKED}\n\n{run.prompt}"
    said = {
        PLACEHOLDER: asked,
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
        limit=LONGEST_LINE,
    )
    try:
        async with asyncio.timeout(runner.timeout_seconds):
            printed, errors, _ = await asyncio.gather(
                _out(process.stdout, tell),  # type: ignore[arg-type]
                process.stderr.read(),  # type: ignore[union-attr]
                _give(process.stdin, asked),
            )
            await process.wait()
    except BaseException as exc:  # stopped, out of time, or unreadable
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        if isinstance(exc, TimeoutError):
            given = f"{runner.timeout_seconds:g} seconds"
            raise TimeoutError(f"The command was stopped after {given}") from None
        raise
    return (process.returncode or 0, printed, errors.decode(errors="replace"))


async def _give(stdin: asyncio.StreamWriter | None, asked: str) -> None:
    """``asked`` to a command that reads its prompt from stdin."""
    if stdin is None:
        return
    # One that never reads it may have shut its end: no fault of its own.
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        stdin.write(asked.encode())
        await stdin.drain()
        stdin.close()


async def _out(stdout: asyncio.StreamReader, tell: Tell) -> str:
    """What a command printed, read a line at a time; what an agent's
    session says in it (``_heard``) told at most every ``TELL_SECONDS``,
    and the rest once it is done: by a sender of its own, in order, so the
    agent never waits on the app to go on printing."""
    batches: asyncio.Queue[list[Line] | None] = asyncio.Queue()

    async def send() -> None:
        while (batch := await batches.get()) is not None:
            await tell(batch)

    sender = asyncio.create_task(send())
    printed: list[str] = []
    heard: list[Line] = []
    told = time.monotonic()
    try:
        async for raw in stdout:
            printed.append(raw.decode(errors="replace"))
            heard += _heard(printed[-1])
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
    return "".join(printed)


def _heard(printed: str) -> list[Line]:
    """What one line of an agent's session (Claude Code's stream-json) says:
    what it said, each tool it called with what it was given, and what a
    tool gave back, each cut to ``MOST_LINE``; nothing for its own events,
    its thinking, or a line that is not one."""
    try:
        event = json.loads(printed)
    except ValueError:
        return []
    if not isinstance(event, dict) or event.get("type") not in ("assistant", "user"):
        return []
    blocks = (event.get("message") or {}).get("content")
    found: list[tuple[str, str]] = []
    for block in blocks if isinstance(blocks, list) else []:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text" and event["type"] == "assistant" and block.get("text"):
            found.append((SAID, block["text"]))
        elif kind == "tool_use":
            given = json.dumps(block.get("input"), ensure_ascii=False)
            found.append((CALLED, f"{block.get('name')} {given}"))
        elif kind == "tool_result":
            found.append((RETURNED, _text_of(block.get("content"))))
    return [Line(kind=kind, text=text[:MOST_LINE]) for kind, text in found]  # type: ignore[arg-type]


def _text_of(content: Any) -> str:
    """A tool's result as text: itself, or its text parts, a line each."""
    if isinstance(content, str):
        return content
    parts = content if isinstance(content, list) else []
    return "\n".join(p["text"] for p in parts if isinstance(p, dict) and "text" in p)


def _read(printed: str) -> Answer | None:
    """A coding agent's own answer in what a command printed (one JSON
    object, last if anything came before it, that is a ``result`` or says
    its ``total_cost_usd``): what it said, or failing why (its ``errors``,
    else the kind of failure), whether it ``is_error``, and what its
    session has cost (where that is an amount). None for anything else:
    plain output."""
    text = printed.strip()
    for candidate in (text, *reversed(text.splitlines())):
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
        yield branches.kept(runner.repo, runner.ref, runner.home, branch)
    else:
        with branches.fresh(runner.repo, runner.ref) as path:
            yield path
