"""The runner: a process on another machine that claims runs over the
app's API, runs a command for each, and posts back what it printed.

It holds a runner token, never a session, and talks only HTTP, so it runs
wherever the repository and the agent's login are (``meetings runner``).
Each run gets a fresh worktree of ``repo`` at ``ref`` (none without a
repository), so the command answers from the code as it is, never from
whatever branch is checked out, and changes nothing that stays. The
command is any headless one: ``{prompt}`` in it is replaced by the run's
prompt; without it the prompt goes on stdin.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile

import httpx

from app.core.log import logger

PLACEHOLDER = "{prompt}"
# What a result keeps of a long answer, or of why it failed.
KEEP = 20_000


@dataclass(frozen=True)
class Runner:
    url: str
    token: str
    actions: list[str]
    command: list[str]
    repo: Path | None = None
    ref: str = "origin/main"
    poll_seconds: float = 5.0
    timeout_seconds: float = 900.0


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
    async with httpx.AsyncClient(
        base_url=runner.url.rstrip("/"),
        headers={"Authorization": f"Bearer {runner.token}"},
        transport=transport,
        timeout=30.0,
    ) as api:
        claimed = await api.post(
            "/api/v1/meetings/runs/claim", json={"actions": runner.actions}
        )
        claimed.raise_for_status()
        if claimed.status_code == 204:
            return False
        run = claimed.json()
        logger.info("Run claimed", run_id=run["id"], action=run["action"])
        ok, result = await _answer(runner, run["prompt"])
        finished = await api.post(
            f"/api/v1/meetings/runs/{run['id']}/finish",
            json={"ok": ok, "result": result[-KEEP:]},
        )
        finished.raise_for_status()
        return True


async def _answer(runner: Runner, prompt: str) -> tuple[bool, str]:
    """Run the command for ``prompt``: whether it succeeded, and what it
    printed (or, failing, why)."""
    argv = [part.replace(PLACEHOLDER, prompt) for part in runner.command]
    stdin = None if any(PLACEHOLDER in part for part in runner.command) else prompt
    try:
        with _worktree(runner.repo, runner.ref) as cwd:
            done = await asyncio.to_thread(
                subprocess.run,
                argv,
                cwd=cwd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=runner.timeout_seconds,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if done.returncode != 0:
        return False, (done.stderr or done.stdout).strip() or f"exit {done.returncode}"
    return True, done.stdout.strip()


@contextmanager
def _worktree(repo: Path | None, ref: str) -> Iterator[Path | None]:
    """A fresh worktree of ``repo`` at ``ref`` (fetched first), removed
    after; no repository, no worktree."""
    if repo is None:
        yield None
        return
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "fetch", "--quiet"], capture_output=True, check=False)
    with tempfile.TemporaryDirectory(prefix="meetings-run-") as parent:
        path = Path(parent) / "worktree"
        subprocess.run(
            [*git, "worktree", "add", "--quiet", "--detach", str(path), ref],
            capture_output=True,
            text=True,
            check=True,
        )
        try:
            yield path
        finally:
            subprocess.run(
                [*git, "worktree", "remove", "--force", str(path)],
                capture_output=True,
                check=False,
            )
