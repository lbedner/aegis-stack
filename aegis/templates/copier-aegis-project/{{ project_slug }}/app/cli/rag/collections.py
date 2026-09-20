"""The collections an index is divided into."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from app.cli import theme
from app.core.config import settings
from app.core.log import suppress_logs
from app.i18n import lazy_t, t
from app.services.rag.config import get_rag_config
from app.services.rag.service import RAGService
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table
from app.cli.rag.shared import app, console, get_rag_service


@app.command("list", help=lazy_t("rag.help_list"))
def list_collections() -> None:
    rag_service = get_rag_service()

    try:
        collections = asyncio.run(rag_service.list_collections())

        if not collections:
            console.print(f"[dim]{t('rag.no_collections')}[/dim]")
            console.print(f"\n[dim]{t('rag.create_collection_hint')}[/dim]")
            return

        # Create table
        table = Table(title=t("rag.collections_title"), show_header=True)
        table.add_column(t("rag.collection_column"), style=theme.ACCENT)
        table.add_column(t("rag.documents_column"), justify="right")

        for name in collections:
            stats = asyncio.run(rag_service.get_collection_stats(name))
            count = stats.get("count", 0) if stats else 0
            table.add_row(name, str(count))

        console.print()
        console.print(table)
        console.print()

    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)


@app.command("delete", help=lazy_t("rag.help_delete"))
def delete_collection(
    collection: Annotated[
        str,
        typer.Argument(help=lazy_t("rag.arg_collection")),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help=lazy_t("rag.opt_force")),
    ] = False,
) -> None:
    rag_service = get_rag_service()

    # Confirm deletion
    if not force:
        confirm = typer.confirm(t("rag.confirm_delete", collection=collection))
        if not confirm:
            console.print(f"[dim]{t('shared.cancelled')}[/dim]")
            return

    try:
        deleted = asyncio.run(rag_service.delete_collection(collection))

        if deleted:
            console.print(f"[{theme.ACCENT}]{t('rag.deleted_collection')}[/] {collection}")
        else:
            console.print(
                f"[dim]{t('rag.collection_not_found')}[/dim] {collection}"
            )

    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)

