"""What the post commands print and change."""

from rich.table import Table
import typer

from app.cli import theme
from app.cli.blog_shared import (
    _PAGE_SIZE_MAX,
    _format_dt,
    _resolve_post_id,
    _status_color,
)
from app.i18n import t


async def _status() -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    async with get_async_session() as session:
        service = BlogService(session)
        summary = await service.get_health_summary()

    console.print()
    console.print(f"[bold]{t('blog.status_title')}[/bold]")
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value")

    table.add_row(t("blog.col_total_posts"), str(summary.total_posts))
    table.add_row(
        t("blog.col_drafts"),
        f"[{theme.WARNING}]{summary.draft_posts}[/{theme.WARNING}]",
    )
    table.add_row(
        t("blog.col_published"),
        f"[{theme.ACCENT}]{summary.published_posts}[/{theme.ACCENT}]",
    )
    table.add_row(
        t("blog.col_archived"),
        f"[dim]{summary.archived_posts}[/dim]",
    )
    table.add_row(t("blog.col_tags"), str(summary.tag_count))
    if summary.stale_draft_count:
        table.add_row(
            t("blog.col_stale_drafts"),
            f"[{theme.ERROR}]{summary.stale_draft_count}[/{theme.ERROR}]",
        )

    latest = summary.latest_published_post
    if latest:
        table.add_row(
            t("blog.col_latest_published"),
            f"{latest.get('title')} ([dim]{latest.get('slug')}[/dim])",
        )

    console.print(table)
    console.print()


console = theme.console()


async def _posts(status_filter: str | None, tag: str | None, limit: int) -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    page_size = min(max(limit, 1), _PAGE_SIZE_MAX)

    async with get_async_session() as session:
        service = BlogService(session)
        rows, total = await service.list_posts(
            page=1, page_size=page_size, status=status_filter, tag=tag
        )

    if not rows:
        console.print(f"[dim]{t('blog.no_posts')}[/dim]")
        return

    table = Table(title=t("blog.posts_title", total=total))
    table.add_column(t("blog.col_id"), style="dim")
    table.add_column(t("blog.col_slug"))
    table.add_column(t("blog.col_title"))
    table.add_column(t("blog.col_status"))
    table.add_column(t("blog.col_author"))
    table.add_column(t("blog.col_published_at"))

    for post in rows:
        color = _status_color(post.status)
        table.add_row(
            str(post.id),
            post.slug,
            post.title,
            f"[{color}]{post.status}[/{color}]",
            post.author_name or "[dim]-[/dim]",
            _format_dt(post.published_at),
        )

    console.print(table)


async def _post_show(slug: str) -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    async with get_async_session() as session:
        service = BlogService(session)
        post_id = await _resolve_post_id(service, slug)
        if post_id is None:
            console.print(
                f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
            )
            raise typer.Exit(1)
        post = await service.get_post(post_id)

    if post is None:
        console.print(
            f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
        )
        raise typer.Exit(1)

    color = _status_color(post.status)
    console.print()
    console.print(f"[bold]{post.title}[/bold]")
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value")

    table.add_row(t("blog.col_id"), str(post.id))
    table.add_row(t("blog.col_slug"), post.slug)
    table.add_row(t("blog.col_status"), f"[{color}]{post.status}[/{color}]")
    table.add_row(t("blog.col_author"), post.author_name or "-")
    table.add_row(t("blog.col_created_at"), _format_dt(post.created_at))
    table.add_row(t("blog.col_updated_at"), _format_dt(post.updated_at))
    table.add_row(t("blog.col_published_at"), _format_dt(post.published_at))
    if post.tags:
        table.add_row(
            t("blog.col_tags"),
            ", ".join(tag.slug for tag in post.tags),
        )
    if post.excerpt:
        table.add_row(t("blog.col_excerpt"), post.excerpt)

    console.print(table)
    console.print()
    console.print(f"[dim]{t('blog.body_hint')}[/dim]")


async def _publish(slug: str) -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    async with get_async_session() as session:
        service = BlogService(session)
        post_id = await _resolve_post_id(service, slug)
        if post_id is None:
            console.print(
                f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
            )
            raise typer.Exit(1)
        post = await service.publish_post(post_id)

    if post is None:
        console.print(
            f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
        )
        raise typer.Exit(1)

    console.print(
        f"[{theme.ACCENT}]{t('blog.published', slug=post.slug)}[/{theme.ACCENT}]"
    )


async def _archive(slug: str) -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    async with get_async_session() as session:
        service = BlogService(session)
        post_id = await _resolve_post_id(service, slug)
        if post_id is None:
            console.print(
                f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
            )
            raise typer.Exit(1)
        post = await service.archive_post(post_id)

    if post is None:
        console.print(
            f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
        )
        raise typer.Exit(1)

    console.print(
        f"[{theme.WARNING}]{t('blog.archived', slug=post.slug)}[/{theme.WARNING}]"
    )


async def _delete(slug: str, yes: bool) -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    if not yes:
        confirmed = typer.confirm(t("blog.confirm_delete_post", slug=slug))
        if not confirmed:
            console.print(f"[dim]{t('blog.cancelled')}[/dim]")
            raise typer.Exit(0)

    async with get_async_session() as session:
        service = BlogService(session)
        post_id = await _resolve_post_id(service, slug)
        if post_id is None:
            console.print(
                f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
            )
            raise typer.Exit(1)
        ok = await service.delete_post(post_id)

    if not ok:
        console.print(
            f"[{theme.ERROR}]{t('blog.post_not_found', slug=slug)}[/{theme.ERROR}]"
        )
        raise typer.Exit(1)

    console.print(f"[{theme.ACCENT}]{t('blog.deleted', slug=slug)}[/{theme.ACCENT}]")
