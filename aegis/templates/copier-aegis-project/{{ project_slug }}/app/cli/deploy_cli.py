"""``deploy``: the deployer's side of deploy history (``app.components.deploy.history``)."""

from datetime import datetime
import json
from pathlib import Path
from typing import Annotated

import typer

from app.cli import theme
from app.components.deploy import drill, history

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


@app.command()
async def event(
    sent: Annotated[
        str,
        typer.Argument(
            help="kind, outcome, summary, actor, origin, started_at, detail, as JSON."
        ),
    ],
) -> None:
    """Record one thing done to the server (aegis calls this)."""
    found = json.loads(sent)
    started = found.get("started_at")
    await history.record_event(
        found["kind"],
        found["outcome"],
        summary=found.get("summary", ""),
        actor=found.get("actor"),
        origin=found.get("origin"),
        started_at=datetime.fromisoformat(started) if started else None,
        detail=found.get("detail") or {},
    )


@app.command()
async def events(
    limit: Annotated[int, typer.Option("--limit", help="How many.")] = 50,
) -> None:
    """The recent events as JSON, newest first (the protocol's ``history``)."""
    rows = await history.recent_events(limit)
    typer.echo(json.dumps([row.model_dump(mode="json") for row in rows]))


@app.command("drill-check")
async def drill_check(
    database: Annotated[
        Path, typer.Option("--database", help="The restored database file.")
    ],
) -> None:
    """A restore drill's checks against a restored copy, as JSON on the last
    line; exits 1 when one fails (aegis deploy-restore-drill runs this)."""
    drill.read_alone()
    checks = await drill.drill_check(database)
    typer.echo(json.dumps(checks))
    if not all(check["ok"] for check in checks):
        raise typer.Exit(1)
