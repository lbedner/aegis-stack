"""Asking the index a question."""

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
from app.cli.rag.shared import _ensure_model_ready, app, console, get_rag_service


@app.command("search", help=lazy_t("rag.help_search"))
def search_documents(
    query: Annotated[
        str,
        typer.Argument(help=lazy_t("rag.arg_query")),
    ],
    collection: Annotated[
        str,
        typer.Option("--collection", "-c", help=lazy_t("rag.opt_collection_search")),
    ] = "default",
    top_k: Annotated[
        int,
        typer.Option("--top-k", "-k", help=lazy_t("rag.opt_top_k")),
    ] = 5,
    show_content: Annotated[
        bool,
        typer.Option("--content", help=lazy_t("rag.opt_content")),
    ] = False,
) -> None:
    # Ensure embedding model is available (download if needed)
    if settings.RAG_EMBEDDING_PROVIDER == "sentence-transformers":
        _ensure_model_ready()

    rag_service = get_rag_service()

    console.print(f"\n[dim]{t('rag.searching_label')}[/dim] {query}")
    console.print(f"[dim]{t('rag.collection_label')}[/dim] {collection}")
    console.print()

    try:
        results = asyncio.run(
            rag_service.search(
                query=query,
                collection_name=collection,
                top_k=top_k,
            )
        )

        if not results:
            console.print(f"[dim]{t('rag.no_results')}[/dim]")
            console.print(f"\n[dim]{t('rag.search_hint')}[/dim]")
            return

        # Display results
        console.print(f"[{theme.ACCENT}]{t('rag.found_results', count=len(results))}[/]\n")

        for result in results:
            source = result.metadata.get("source", t("shared.unknown"))
            file_name = result.metadata.get("file_name", Path(source).name)
            score = result.score

            # Create panel for each result
            if show_content:
                content = result.content
                if len(content) > 500:
                    content = content[:500] + "..."
                panel_content = (
                    f"[dim]{t('rag.score_label')} {score:.4f}[/dim]\n\n{content}"
                )
            else:
                preview = result.content[:200].replace("\n", " ")
                if len(result.content) > 200:
                    preview += "..."
                panel_content = (
                    f"[dim]{t('rag.score_label')} {score:.4f}[/dim]\n\n{preview}"
                )

            console.print(
                Panel(
                    panel_content,
                    title=f"[bold]#{result.rank}[/bold] {file_name}",
                    subtitle=f"[dim]{source}[/dim]",
                    border_style="dim",
                )
            )
            console.print()

    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)

