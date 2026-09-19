"""The embedding model: is it here, and can we fetch it."""

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
from app.cli.rag.shared import _is_model_cached, app, console, get_rag_service


@app.command("status", help=lazy_t("rag.help_status"))
def show_status() -> None:
    rag_service = get_rag_service()

    try:
        status = rag_service.get_service_status()
        collections = asyncio.run(rag_service.list_collections())

        # Check if embedding model is installed
        model_cached = _is_model_cached()
        if model_cached:
            model_status = f"[{theme.ACCENT}]{t('rag.model_installed')}[/]"
        else:
            model_status = f"[{theme.WARNING}]{t('rag.model_not_installed')}[/] [dim]({t('rag.run_install_model')})[/dim]"

        # Create status panel
        yes_no = t("shared.yes") if status.get("enabled") else t("shared.no")
        status_lines = [
            f"[dim]{t('rag.enabled_label')}[/dim] {yes_no}",
            f"[dim]{t('rag.persist_dir_label')}[/dim] {status.get('persist_directory')}",
            f"[dim]{t('rag.embedding_model_label')}[/dim] {status.get('embedding_model')}",
            f"[dim]{t('rag.model_status_label')}[/dim] {model_status}",
            f"[dim]{t('rag.chunk_size_label')}[/dim] {status.get('chunk_size')}",
            f"[dim]{t('rag.chunk_overlap_label')}[/dim] {status.get('chunk_overlap')}",
            f"[dim]{t('rag.default_top_k_label')}[/dim] {status.get('default_top_k')}",
            f"[dim]{t('rag.collections_count_label')}[/dim] {len(collections)}",
        ]

        if status.get("last_activity"):
            status_lines.append(
                f"[dim]{t('rag.last_activity_label')}[/dim] {status.get('last_activity')}"
            )

        console.print()
        console.print(
            Panel(
                "\n".join(status_lines),
                title=t("rag.status_title"),
                border_style="dim",
            )
        )
        console.print()

    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('shared.error')}[/] {e}")
        raise typer.Exit(code=1)


@app.command("install-model", help=lazy_t("rag.help_install_model"))
def install_model(
    cache_dir: Annotated[
        str | None,
        typer.Option(
            "--cache-dir",
            "-d",
            help=lazy_t("rag.opt_cache_dir"),
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help=lazy_t("rag.opt_model"),
        ),
    ] = None,
) -> None:
    # OpenAI embeddings don't require local model download
    if settings.RAG_EMBEDDING_PROVIDER == "openai":
        console.print(f"\n[dim]{t('rag.openai_no_download')}[/dim]")
        console.print(f"[dim]{t('rag.openai_key_hint')}[/dim]\n")
        return

    from sentence_transformers import SentenceTransformer

    # Determine model name
    model_name = model or settings.RAG_EMBEDDING_MODEL

    # Determine cache directory (None = use system HuggingFace cache)
    target_dir = cache_dir or settings.RAG_MODEL_CACHE_DIR

    # Check if model is already cached before downloading
    was_cached = _is_model_cached()

    console.print(f"\n[dim]{t('rag.model_label')}[/dim] {model_name}")
    if target_dir:
        console.print(
            f"[dim]{t('rag.cache_dir_label')}[/dim] {Path(target_dir).resolve()}"
        )
    else:
        console.print(
            f"[dim]{t('rag.cache_dir_label')}[/dim] [dim]({t('rag.system_hf_cache')})[/dim]"
        )
    console.print()

    try:
        # Create cache directory if specified
        if target_dir:
            target_path = Path(target_dir)
            target_path.mkdir(parents=True, exist_ok=True)

        # Download/load model with appropriate messaging
        if was_cached:
            console.print(f"[dim]{t('rag.loading_from_cache')}[/dim]")
        else:
            console.print(
                f"[{theme.ACCENT}]{t('rag.downloading_named_model', model=model_name)}[/]"
            )
            console.print()  # Blank line before tqdm progress bars

        if target_dir:
            _ = SentenceTransformer(model_name, cache_folder=str(target_path))
        else:
            _ = SentenceTransformer(model_name)

        if not was_cached:
            console.print()  # Blank line after progress bars

        # Build result message
        if was_cached:
            status_msg = f"[{theme.ACCENT}]{t('rag.model_found_in_cache')}[/]"
            title = t("rag.model_ready_title")
        else:
            status_msg = f"[{theme.ACCENT}]{t('rag.model_downloaded')}[/]"
            title = t("rag.model_install_complete_title")

        if target_dir:
            location_msg = (
                f"[dim]{t('rag.location_label')}[/dim] {Path(target_dir).resolve()}"
            )
            hint_msg = f"\n\n[dim]{t('rag.cache_dir_hint', dir=target_dir)}[/dim]"
        else:
            location_msg = f"[dim]{t('rag.location_label')}[/dim] [dim]({t('rag.system_hf_cache')})[/dim]"
            hint_msg = ""

        console.print(
            Panel(
                f"{status_msg}\n\n"
                f"[dim]{t('rag.model_label')}[/dim] {model_name}\n"
                f"{location_msg}{hint_msg}",
                title=title,
                border_style=theme.ACCENT,
            )
        )

    except Exception as e:
        console.print(
            f"[{theme.ERROR}]{t('shared.error')}[/] {t('rag.model_download_failed', error=e)}"
        )
        raise typer.Exit(code=1)

