"""``deploy``: the deployer's side of deploy history (``app.components.deploy.history``)."""

import json
from typing import Annotated

import typer

from app.cli import theme
from app.components.deploy import history

app = typer.Typer(help="Deploy history, written by aegis deploy.")
console = theme.console()


@app.command()
async def record(
    build: Annotated[str, typer.Option("--build", help="The BUILD_ID deployed.")],
    by: Annotated[str | None, typer.Option("--by", help="Who deployed.")] = None,
    from_: Annotated[
        str | None, typer.Option("--from", help="The machine deployed from.")
    ] = None,
    health: Annotated[
        str | None, typer.Option("--health", help="passed or failed.")
    ] = None,
    backup: Annotated[
        str | None, typer.Option("--backup", help="Backup taken before it.")
    ] = None,
    rolled_back: Annotated[
        bool,
        typer.Option(
            "--rolled-back", help="It was rolled back to the build running now."
        ),
    ] = False,
) -> None:
    """Record a deploy of BUILD (aegis deploy calls this)."""
    await history.record_deploy(
        build,
        deployed_by=by,
        deployed_from=from_,
        health=health,
        backup=backup,
        rolled_back=rolled_back,
    )
    console.print(f"[{theme.ACCENT}]✓[/] Recorded deploy of {build}")


@app.command("history")
async def show_history(
    limit: Annotated[int, typer.Option("--limit", help="How many.")] = 50,
) -> None:
    """The recent deploys as JSON, newest first (the protocol's ``history``)."""
    rows = await history.recent(limit)
    typer.echo(json.dumps([row.model_dump(mode="json") for row in rows]))
