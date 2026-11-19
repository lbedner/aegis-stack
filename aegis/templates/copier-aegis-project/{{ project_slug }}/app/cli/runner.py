"""``runner``: the runner itself, and the tokens runners claim runs with."""

import json
from pathlib import Path
import shlex

from rich.table import Table
import typer

from app.cli import theme
from app.components.runner import hooks as agent_hooks
from app.components.runner import tokens as runner_tokens
from app.components.runner.client import Runner, run_forever, run_once
from app.core.config import settings
from app.core.db import get_async_session
from app.core.formatting import format_relative_time

app = typer.Typer(help="Work sent out to a coding agent: the runner and its tokens.")
tokens = typer.Typer(help="Tokens a runner on another machine claims runs with.")
app.add_typer(tokens, name="token")
console = theme.console()
_URL = typer.Option(None, "--url", help="The app (API_BASE_URL)")


@app.command()
async def run(
    command: str = typer.Option(
        ...,
        "--command",
        help="The command each run runs; {prompt} is its prompt (stdin without "
        "it), {session} the agent's session id, {hooks} the settings that "
        "make it say what it is doing (runner hooks)",
    ),
    resume_command: str | None = typer.Option(
        None,
        "--resume-command",
        help="The command a run runs to continue a session; --command without it",
    ),
    action: list[str] = typer.Option(
        ["agent"], "--action", help="An action this runner runs (repeat for more)"
    ),
    repo: Path | None = typer.Option(
        None, "--repo", help="Answer from a worktree of this repository"
    ),
    ref: str = typer.Option(Runner.ref, "--ref", help="What a new worktree checks out"),
    worktrees: Path | None = typer.Option(
        None,
        "--worktrees",
        help="Where a branch's worktree is kept (<repo>-worktrees beside --repo)",
    ),
    url: str | None = _URL,
    token: str = typer.Option(
        ...,
        "--token",
        envvar=agent_hooks.TOKEN_ENV,
        help="A runner token (runner token create)",
    ),
    once: bool = typer.Option(
        False, "--once", help="Answer one waiting run, then stop"
    ),
    poll: float = typer.Option(
        Runner.poll_seconds, "--poll", help="Seconds between looks while idle"
    ),
    timeout: float = typer.Option(
        Runner.timeout_seconds,
        "--timeout",
        help="Seconds a command is given before it is stopped",
    ),
) -> None:
    """Claim the runs of ``--action`` the app asks and answer each with
    ``--command``, from a fresh worktree of ``--repo`` (a kept one, for a run
    on a branch), posting back what it printed. Runs where the repository
    and the agent's login are, holding a runner token. The dev stack's own
    command is in ``scripts/entrypoint.sh``: Claude Code, read-only, in a
    session, saying what it cost."""
    found = Runner(
        url=url or settings.API_BASE_URL,
        token=token,
        actions=action,
        command=shlex.split(command),
        repo=repo.expanduser() if repo else None,
        ref=ref,
        poll_seconds=poll,
        timeout_seconds=timeout,
        resume_command=shlex.split(resume_command) if resume_command else None,
        worktrees=worktrees.expanduser() if worktrees else None,
    )
    console.print(f"Answering {', '.join(action)} for {found.url}. Ctrl-C stops.")
    if once:
        console.print("Answered one." if await run_once(found) else "Nothing waits.")
        return
    await run_forever(found)


@app.command()
def hooks(url: str | None = _URL) -> None:
    """Claude Code settings that post each step of a session to the app, so
    a run says what it is doing. The runner fills them in where its command
    says ``{hooks}`` (``--settings {hooks}``); this prints them for a
    session picked up in a terminal (``--settings`` takes a file of them),
    which signs what it posts with the runner's token (``RUNNER_TOKEN``)."""
    typer.echo(json.dumps(agent_hooks.settings(url or settings.API_BASE_URL), indent=2))


@tokens.command("create")
async def create_token(
    name: str = typer.Argument(..., help="The runner's name (its machine)"),
    owner: int | None = typer.Option(
        None, "--owner", help="Whose runs it claims (every owner's without one)"
    ),
) -> None:
    """A token for a runner. Its value is shown this once."""
    async with get_async_session() as session:
        row, value = await runner_tokens.create(session, owner, name)
    console.print(f"Runner token {row.name} ({row.hint}...), shown this once:")
    console.print(value, soft_wrap=True)


@tokens.command("list")
async def list_tokens(
    owner: int | None = typer.Option(None, "--owner", help="Whose tokens"),
) -> None:
    """The runner tokens not revoked, newest first."""
    async with get_async_session() as session:
        rows = await runner_tokens.live(session, owner)
    table = Table("Id", "Name", "Token", "Made", "Last used")
    for row in rows:
        table.add_row(
            str(row.id),
            row.name,
            f"{row.hint}...",
            format_relative_time(row.created_at),
            format_relative_time(row.last_used_at) if row.last_used_at else "never",
        )
    console.print(table)


@tokens.command("revoke")
async def revoke_token(
    token_id: int = typer.Argument(..., help="The token's id (runner token list)"),
    owner: int | None = typer.Option(None, "--owner", help="Whose token"),
) -> None:
    """Revoke a runner token: its runner is refused from now."""
    async with get_async_session() as session:
        try:
            await runner_tokens.revoke(session, token_id, owner)
        except runner_tokens.RunnerTokenNotFoundError:
            theme.fail(f"No live runner token {token_id}.")
    console.print(f"Revoked runner token {token_id}.")
