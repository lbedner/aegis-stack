"""Getting documents in and out of the index."""

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
from app.cli.rag.shared import _ensure_model_ready, app, console, format_duration, get_rag_service


@app.command("index", help=lazy_t("rag.help_index"))
def index_documents(
    path: Annotated[
        str,
        typer.Argument(help=lazy_t("rag.arg_path")),
    ],
    collection: Annotated[
        str,
        typer.Option("--collection", "-c", help=lazy_t("rag.opt_collection")),
    ] = "default",
    extensions: Annotated[
        str | None,
        typer.Option("--extensions", "-e", help=lazy_t("rag.opt_extensions")),
    ] = None,
) -> None:
    # Ensure embedding model is available (download if needed)
    if settings.RAG_EMBEDDING_PROVIDER == "sentence-transformers":
        _ensure_model_ready()

    rag_service = get_rag_service()

    # Parse extensions
    ext_list = None
    if extensions:
        ext_list = [e.strip() for e in extensions.split(",")]
        # Ensure extensions start with dot
        ext_list = [e if e.startswith(".") else f".{e}" for e in ext_list]

    console.print(f"\n[dim]{t('rag.indexing_label')}[/dim] {path}")
    console.print(f"[dim]{t('rag.collection_label')}[/dim] {collection}")
    if ext_list:
        console.print(
            f"[dim]{t('rag.extensions_label')}[/dim] {', '.join(ext_list)}"
        )
    console.print()

    try:
        with (
            suppress_logs(),
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("[dim]{task.fields[status]}"),
                console=console,
            ) as progress,
        ):
            task = progress.add_task(
                t("rag.indexing_progress"),
                total=None,
                status=t("rag.loading_documents"),
            )

            def on_progress(batch: int, total: int, chunks: int) -> None:
                progress.update(
                    task,
                    total=total,
                    completed=batch,
                    status=t(
                        "rag.batch_progress", batch=batch, total=total, chunks=chunks
                    ),
                )

            stats = asyncio.run(
                rag_service.refresh_index(
                    path=Path(path),
                    collection_name=collection,
                    extensions=ext_list,
                    progress_callback=on_progress,
                )
            )

        # Calculate total duration and stats
        total_ms = stats.load_ms + stats.chunk_ms + stats.duration_ms
        total_str = format_duration(total_ms)
        chunks_per_sec = (
            stats.documents_added / (total_ms / 1000) if total_ms > 0 else 0
        )

        # Calculate phase percentages
        def pct(phase_ms: float) -> str:
            if total_ms <= 0:
                return "0%"
            return f"{(phase_ms / total_ms) * 100:.0f}%"

        # Format extensions for display
        ext_display = (
            ", ".join(stats.extensions) if stats.extensions else t("shared.none")
        )

        # Display results with phase breakdown
        console.print(
            Panel(
                f"[{theme.ACCENT}]{t('rag.index_success', chunks=f'{stats.documents_added:,}', files=f'{stats.source_files:,}')}[/]\n\n"
                f"[dim]{t('rag.extensions_label')}[/dim] {ext_display}\n"
                f"[dim]{t('rag.duration_label')}[/dim] {total_str}\n"
                f"  [dim]{t('rag.loading_phase')}[/dim]  {format_duration(stats.load_ms)} ({pct(stats.load_ms)})\n"
                f"  [dim]{t('rag.chunking_phase')}[/dim] {format_duration(stats.chunk_ms)} ({pct(stats.chunk_ms)})\n"
                f"  [dim]{t('rag.indexing_phase')}[/dim] {format_duration(stats.duration_ms)} ({pct(stats.duration_ms)})\n"
                f"[dim]{t('rag.throughput_label')}[/dim] {chunks_per_sec:.1f} {t('rag.chunks_per_sec')}\n"
                f"[dim]{t('rag.collection_size_label')}[/dim] {stats.total_documents:,} {t('rag.chunks_unit')}",
                title=f"{t('rag.collection_title')}: {collection}",
                border_style=theme.ACCENT,
            )
        )

    except FileNotFoundError as e:
        console.print(
            f"[{theme.ERROR}]{t('shared.error')}[/] {t('rag.path_not_found', path=getattr(e, 'filename', str(e)))}"
        )
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)


@app.command("add", help=lazy_t("rag.help_add"))
def add_file(
    path: Annotated[
        str,
        typer.Argument(help=lazy_t("rag.arg_file_path")),
    ],
    collection: Annotated[
        str,
        typer.Option("--collection", "-c", help=lazy_t("rag.opt_collection")),
    ] = "default",
    show_ids: Annotated[
        bool,
        typer.Option("--show-ids", help=lazy_t("rag.opt_show_ids")),
    ] = False,
) -> None:
    # Ensure embedding model is available (download if needed)
    if settings.RAG_EMBEDDING_PROVIDER == "sentence-transformers":
        _ensure_model_ready()

    rag_service = get_rag_service()

    console.print(f"\n[dim]{t('rag.adding_label')}[/dim] {path}")
    console.print(f"[dim]{t('rag.collection_label')}[/dim] {collection}")
    console.print()

    try:
        result = asyncio.run(
            rag_service.add_file(
                path=Path(path),
                collection_name=collection,
            )
        )

        # Display result
        file_name = Path(result.file_path).name
        output = (
            f"[{theme.ACCENT}]{t('rag.added_updated')}[/] {file_name}\n"
            f"{t('rag.chunks_label')} {result.chunk_count}\n"
            f"{t('rag.hash_label')} {result.file_hash}"
        )

        if show_ids and result.chunk_ids:
            output += f"\n{t('rag.ids_label')} {', '.join(result.chunk_ids)}"

        console.print(
            Panel(
                output,
                title=f"{t('rag.collection_title')}: {collection}",
                border_style=theme.ACCENT,
            )
        )

    except FileNotFoundError as e:
        console.print(
            f"[{theme.ERROR}]{t('shared.error')}[/] {t('rag.file_not_found', path=e)}"
        )
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)


@app.command("remove", help=lazy_t("rag.help_remove"))
def remove_file(
    source_path: Annotated[
        str,
        typer.Argument(help=lazy_t("rag.arg_source_path")),
    ],
    collection: Annotated[
        str,
        typer.Option("--collection", "-c", help=lazy_t("rag.opt_collection")),
    ] = "default",
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help=lazy_t("rag.opt_force")),
    ] = False,
) -> None:
    rag_service = get_rag_service()

    # Confirm deletion
    if not force:
        confirm = typer.confirm(
            t("rag.confirm_remove", source=source_path, collection=collection)
        )
        if not confirm:
            console.print(f"[dim]{t('shared.cancelled')}[/dim]")
            return

    try:
        result = asyncio.run(
            rag_service.remove_file(
                source_path=source_path,
                collection_name=collection,
            )
        )

        if result.chunk_count > 0:
            console.print(
                f"[{theme.ACCENT}]{t('rag.removed_chunks', count=result.chunk_count)}[/] {source_path}"
            )
        else:
            console.print(f"[dim]{t('rag.no_chunks_found')}[/dim] {source_path}")
            console.print(f"[dim]{t('rag.files_hint')}[/dim]")

    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)


@app.command("files", help=lazy_t("rag.help_files"))
def list_files(
    collection: Annotated[
        str,
        typer.Option("--collection", "-c", help=lazy_t("rag.opt_collection")),
    ] = "default",
) -> None:
    rag_service = get_rag_service()

    try:
        files = asyncio.run(rag_service.list_files(collection_name=collection))

        if not files:
            console.print(
                f"[dim]{t('rag.no_files_in_collection')}[/dim] {collection}"
            )
            console.print(f"\n[dim]{t('rag.index_hint')}[/dim]")
            return

        # Create table
        table = Table(
            title=t("rag.indexed_files_title", collection=collection),
            show_header=True,
        )
        table.add_column(t("rag.file_column"), style=theme.ACCENT)
        table.add_column(t("rag.chunks_column"), justify="right")

        total_chunks = 0
        for file in files:
            table.add_row(file.source, str(file.chunks))
            total_chunks += file.chunks

        console.print()
        console.print(table)
        console.print(
            f"\n[dim]{t('rag.total_label')}[/dim] {t('rag.files_and_chunks', files=len(files), chunks=total_chunks)}"
        )
        console.print()

    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)

