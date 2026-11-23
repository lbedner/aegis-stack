"""``audit``: the audit log (``app.components.database.audit``), newest
first, as a table, or as JSON for a script."""

import json
from typing import Annotated

import typer

from app.cli import theme
from app.components.database import audit

app = typer.Typer(help="The audit log: who did what, newest first.")
console = theme.console()


@app.command("list")
async def list_events(
    limit: Annotated[int, typer.Option("--limit", help="How many.")] = 200,
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Event types starting with this (auth.)."),
    ] = None,
    actor: Annotated[
        str | None, typer.Option("--actor", help="The actor's email or user id.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """The newest audited actions."""
    rows = await audit.recent(limit, kind=kind, actor=actor)
    if as_json:
        typer.echo(json.dumps([row.model_dump(mode="json") for row in rows]))
        return
    # The event type first, never cut: it is what --kind takes back.
    table = theme.keyed_table(
        ("Event", "When", "Actor", "Target", "Detail"),
        [row.event_type for row in rows],
    )
    for row in rows:
        table.add_row(
            row.event_type,
            row.at.strftime("%Y-%m-%d %H:%M:%S"),
            row.actor or "-",
            row.target or "-",
            row.detail or "-",
        )
    console.print(table)
