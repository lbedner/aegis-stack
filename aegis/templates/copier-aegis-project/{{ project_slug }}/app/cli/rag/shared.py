"""The ``rag`` Typer app, and what every command needs.

The app object lives here rather than in ``__init__`` so a command
module can import it without importing its siblings.
"""

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


app = typer.Typer(help=lazy_t("rag.help"))
console = theme.console()


def get_rag_service() -> RAGService:
    """Get RAG service instance."""
    config = get_rag_config(settings)
    return RAGService(config)


def format_duration(ms: float) -> str:
    """Format milliseconds into human-readable duration."""
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m {remaining_seconds:.0f}s"
    hours = int(minutes // 60)
    remaining_minutes = minutes % 60
    return f"{hours}h {remaining_minutes}m"


def _get_model_cache_path() -> Path:
    """Get the path where embedding model would be cached."""
    if settings.RAG_MODEL_CACHE_DIR:
        return Path(settings.RAG_MODEL_CACHE_DIR)
    # Default HuggingFace cache location
    return Path.home() / ".cache" / "huggingface" / "hub"


def _is_model_cached() -> bool:
    """Check if the embedding model is already downloaded."""
    model_name = settings.RAG_EMBEDDING_MODEL
    cache_path = _get_model_cache_path()

    # sentence-transformers caches models in hub/models--{org}--{model}
    model_dir_name = f"models--{model_name.replace('/', '--')}"
    model_path = cache_path / model_dir_name

    # Check if model directory exists and has content
    return model_path.exists() and any(model_path.iterdir())


def _ensure_model_ready() -> None:
    """Check if model/API is ready, download local model if needed."""
    # OpenAI embeddings don't require local model
    if settings.RAG_EMBEDDING_PROVIDER == "openai":
        # Early validation: check API key is configured
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            console.print()
            console.print(f"[{theme.ERROR}]{t('rag.openai_key_missing')}[/]")
            console.print(f"[dim]{t('rag.openai_key_hint')}[/dim]")
            raise typer.Exit(code=1)
        return

    # sentence-transformers: check cache and download if needed
    if _is_model_cached():
        return

    model_name = settings.RAG_EMBEDDING_MODEL
    cache_dir = settings.RAG_MODEL_CACHE_DIR

    console.print()
    console.print(f"[{theme.WARNING}]{t('rag.model_not_found')}[/]")
    console.print(f"[dim]{t('rag.model_info', model=model_name)}[/dim]")
    console.print()

    try:
        from sentence_transformers import SentenceTransformer

        console.print(f"[{theme.ACCENT}]{t('rag.downloading_model')}[/]")
        console.print()  # Blank line before tqdm progress bars

        if cache_dir:
            SentenceTransformer(model_name, cache_folder=cache_dir)
        else:
            SentenceTransformer(model_name)

        console.print()  # Blank line after progress bars
        console.print(f"[{theme.ACCENT}]{t('rag.model_downloaded')}[/]")
        console.print()
    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('rag.model_download_failed', error=e)}[/]")
        console.print(f"[dim]{t('rag.model_download_hint')}[/dim]")
        raise typer.Exit(code=1)

