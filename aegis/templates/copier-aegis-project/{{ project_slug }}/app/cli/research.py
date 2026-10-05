"""``research``: watches and what they found, from the terminal.

Watches added here have no owner, the way a project without auth keeps
everything; ``refresh`` with no id runs every owner's watches, as the
nightly job does.
"""

import json

from rich.table import Table
import typer

from app.cli import theme
from app.core.db import get_async_session
from app.core.formatting import format_relative_time
from app.services.research.refresh import refresh_every_watch
from app.services.research.registry import installed_sources
from app.services.research.service import ResearchService

app = typer.Typer(help="Outside posts and threads, collected by saved searches.")
console = theme.console()


@app.command()
async def sources() -> None:
    """The sources installed in this project (each one a plugin)."""
    sources = installed_sources()
    if not sources:
        console.print(
            "[dim]No sources installed (aegis-stack-hackernews is one).[/dim]"
        )
    for source in sources:
        console.print(f"{source.name}  {source.title}")


@app.command()
async def watches() -> None:
    """The saved searches and when each last ran."""
    async with get_async_session() as session:
        rows = await ResearchService(session, owner_user_id=None).list_watches()
    table = Table(title="Watches")
    for column in ("ID", "Source", "Name", "Query", "Last refresh"):
        table.add_column(column)
    for w in rows:
        table.add_row(
            str(w.id),
            w.source,
            w.name,
            json.dumps(w.query),
            format_relative_time(w.refreshed_at),
        )
    console.print(table)


@app.command()
async def add(
    source: str = typer.Argument(..., help="The source, e.g. hn"),
    name: str = typer.Argument(..., help="A name for the watch"),
    query: str = typer.Argument(
        ..., help='The source\'s query, as JSON: \'{"q": "fastapi"}\''
    ),
    threads: bool = typer.Option(
        False, "--threads", help="Read each story's comments too"
    ),
) -> None:
    """Save a search on a source."""
    async with get_async_session() as session:
        watch = await ResearchService(session, owner_user_id=None).add_watch(
            source, name, json.loads(query), with_threads=threads
        )
    console.print(f"Watch {watch.id} saved. Run it: research refresh {watch.id}")


@app.command()
async def refresh(
    watch_id: int | None = typer.Argument(
        None, help="One watch; every watch when left out"
    ),
) -> None:
    """Run a watch's search now, or every watch's."""
    async with get_async_session() as session:
        if watch_id is None:
            found = await refresh_every_watch(session)
            console.print(
                f"Refreshed {len(found)} watches, {sum(found.values())} items found."
            )
            return
        count = await ResearchService(session, owner_user_id=None).refresh_watch(
            watch_id
        )
    console.print(f"Watch {watch_id} found {count} items.")


@app.command()
async def search(
    text: str = typer.Argument(..., help="Words in a title or a body"),
    source: str | None = typer.Option(None, "--source", "-s"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Search what the watches found."""
    async with get_async_session() as session:
        items = await ResearchService(session, owner_user_id=None).search(
            text, source=source, limit=limit
        )
    table = Table(title=f"{len(items)} items")
    for column in ("ID", "Source", "Score", "Comments", "Title or text"):
        table.add_column(column)
    for item in items:
        table.add_row(
            str(item.id),
            item.source,
            str(item.score or ""),
            str(item.comment_count or ""),
            (item.title or item.text or "")[:80],
        )
    console.print(table)
