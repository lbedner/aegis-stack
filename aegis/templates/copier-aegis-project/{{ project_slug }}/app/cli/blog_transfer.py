"""Posts out to disk, and posts back in."""

from rich.table import Table
import typer

from app.cli import theme
from app.i18n import t
from app.services.blog.constants import ImportConflictPolicy


async def _export(path: str, fmt: str, status_filter: str | None) -> None:
    from pathlib import Path

    from app.core.db import get_async_session
    from app.services.blog.serialization import (
        post_to_markdown,
        posts_to_json,
    )
    from app.services.blog.service import BlogService

    if fmt not in ("markdown", "json"):
        console.print(
            f"[{theme.ERROR}]{t('blog.export_bad_format', fmt=fmt)}[/{theme.ERROR}]"
        )
        raise typer.Exit(2)

    async with get_async_session() as session:
        service = BlogService(session)
        posts = await service.export_posts(status=status_filter)

    if not posts:
        console.print(f"[dim]{t('blog.no_posts')}[/dim]")
        return

    target = Path(path)
    if fmt == "json":
        target.write_text(posts_to_json(posts), encoding="utf-8")
        console.print(
            f"[{theme.ACCENT}]{t('blog.exported_json', count=len(posts), path=target)}[/{theme.ACCENT}]"
        )
        return

    target.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for post in posts:
        base = post.slug or "post"
        name = f"{base}.md"
        counter = 1
        while name in seen:
            counter += 1
            name = f"{base}-{counter}.md"
        seen.add(name)
        (target / name).write_text(post_to_markdown(post), encoding="utf-8")

    console.print(
        f"[{theme.ACCENT}]{t('blog.exported_markdown', count=len(posts), path=target)}[/{theme.ACCENT}]"
    )


console = theme.console()


async def _import(path: str, on_conflict: ImportConflictPolicy) -> None:
    from pathlib import Path

    from app.core.db import get_async_session
    from app.services.blog.schemas import ImportedPost
    from app.services.blog.serialization import (
        json_to_posts,
        markdown_to_post,
        zip_to_posts,
    )
    from app.services.blog.service import BlogService

    source = Path(path)
    if not source.exists():
        console.print(
            f"[{theme.ERROR}]{t('blog.import_path_missing', path=path)}[/{theme.ERROR}]"
        )
        raise typer.Exit(1)

    posts: list[ImportedPost] = []
    if source.is_dir():
        for md_path in sorted(source.rglob("*.md")):
            text = md_path.read_text(encoding="utf-8")
            posts.append(markdown_to_post(text, fallback_slug=md_path.stem))
    elif source.suffix.lower() == ".zip":
        posts = zip_to_posts(source.read_bytes())
    elif source.suffix.lower() == ".json":
        posts = json_to_posts(source.read_text(encoding="utf-8"))
    elif source.suffix.lower() in (".md", ".markdown"):
        posts = [
            markdown_to_post(
                source.read_text(encoding="utf-8"), fallback_slug=source.stem
            )
        ]
    else:
        console.print(
            f"[{theme.ERROR}]{t('blog.import_bad_type', path=path)}[/{theme.ERROR}]"
        )
        raise typer.Exit(2)

    if not posts:
        console.print(f"[dim]{t('blog.import_empty')}[/dim]")
        return

    async with get_async_session() as session:
        service = BlogService(session)
        result = await service.import_posts(posts, on_conflict=on_conflict)

    table = Table(title=t("blog.import_summary_title"))
    table.add_column(t("blog.col_kind"), style="dim")
    table.add_column(t("blog.col_count"), justify="right")
    table.add_row(
        t("blog.col_created"),
        f"[{theme.ACCENT}]{result.created}[/{theme.ACCENT}]",
    )
    table.add_row(t("blog.col_updated"), str(result.updated))
    table.add_row(
        t("blog.col_skipped"),
        f"[{theme.WARNING}]{result.skipped}[/{theme.WARNING}]",
    )
    table.add_row(
        t("blog.col_failed"),
        f"[{theme.ERROR}]{result.failed}[/{theme.ERROR}]",
    )
    console.print(table)

    if result.errors:
        console.print()
        for err in result.errors:
            console.print(
                f"  [{theme.ERROR}]{err.slug or '(unknown)'}[/{theme.ERROR}]: {err.message}"
            )
