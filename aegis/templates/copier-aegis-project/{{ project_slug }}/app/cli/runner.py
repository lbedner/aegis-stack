"""``runner``: the runner itself, and the tokens runners claim runs with."""

from pathlib import Path
import shlex

from rich.table import Table
import typer

from app.cli import theme
from app.components.runner import tokens as runner_tokens
from app.components.runner.client import Runner, run_forever, run_once
from app.core.config import settings
from app.core.db import get_async_session
from app.core.formatting import format_relative_time

app = typer.Typer(help="Work sent out to a coding agent: the runner and its tokens.")
tokens = typer.Typer(help="Tokens a runner on another machine claims runs with.")
app.add_typer(tokens, name="token")
console = theme.console()


@app.command()
async def run(
    command: str = typer.Option(
        ...,
        "--command",
        help="The command each run runs; {prompt} is its prompt (stdin without it)",
    ),
    action: list[str] = typer.Option(
        ["agent"], "--action", help="An action this runner runs (repeat for more)"
    ),
    repo: Path | None = typer.Option(
        None, "--repo", help="Answer from a fresh worktree of this repository"
    ),
    ref: str = typer.Option(Runner.ref, "--ref", help="What each worktree checks out"),
    url: str | None = typer.Option(None, "--url", help="The app (API_BASE_URL)"),
    token: str = typer.Option(
        ...,
        "--token",
        envvar="RUNNER_TOKEN",
        help="A runner token (runner token create)",
    ),
    once: bool = typer.Option(
        False, "--once", help="Answer one waiting run, then stop"
    ),
    poll: float = typer.Option(
        Runner.poll_seconds, "--poll", help="Seconds between looks while idle"
    ),
) -> None:
    """Claim the runs of ``--action`` the app asks and answer each with
    ``--command``, from a fresh worktree of ``--repo``, posting back what it
    printed. Runs where the repository and the agent's login are, holding a
    runner token: e.g. ``--command 'claude -p {prompt} --permission-mode plan'``."""
    found = Runner(
        url=url or settings.API_BASE_URL,
        token=token,
        actions=action,
        command=shlex.split(command),
        repo=repo.expanduser() if repo else None,
        ref=ref,
        poll_seconds=poll,
    )
    console.print(f"Answering {', '.join(action)} for {found.url}. Ctrl-C stops.")
    if once:
        console.print("Answered one." if await run_once(found) else "Nothing waits.")
        return
    await run_forever(found)


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
