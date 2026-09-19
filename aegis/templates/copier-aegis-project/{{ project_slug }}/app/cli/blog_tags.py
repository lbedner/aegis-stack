"""What the tag commands print and change."""

from rich.table import Table
import typer

from app.cli import theme
from app.cli.blog_shared import (
    _format_dt,
    _resolve_tag_id,
)
from app.i18n import t


async def _tags() -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    async with get_async_session() as session:
        service = BlogService(session)
        rows = await service.list_tags()

    if not rows:
        console.print(f"[dim]{t('blog.no_tags')}[/dim]")
        return

    table = Table(title=t("blog.tags_title", total=len(rows)))
    table.add_column(t("blog.col_id"), style="dim")
    table.add_column(t("blog.col_slug"))
    table.add_column(t("blog.col_name"))
    table.add_column(t("blog.col_created_at"))

    for tag in rows:
        table.add_row(
            str(tag.id),
            tag.slug,
            tag.name,
            _format_dt(tag.created_at),
        )

    console.print(table)


console = theme.console()


async def _tag_create(name: str, slug: str | None) -> None:
    from app.core.db import get_async_session
    from app.services.blog.schemas import BlogTagCreate
    from app.services.blog.service import BlogService

    async with get_async_session() as session:
        service = BlogService(session)
        try:
            tag = await service.create_tag(BlogTagCreate(name=name, slug=slug))
        except ValueError as e:
            console.print(f"[{theme.ERROR}]{e}[/{theme.ERROR}]")
            raise typer.Exit(1) from e

    console.print(
        f"[{theme.ACCENT}]{t('blog.tag_created', name=tag.name, slug=tag.slug)}[/{theme.ACCENT}]"
    )


async def _tag_update(slug: str, name: str | None, new_slug: str | None) -> None:
    from app.core.db import get_async_session
    from app.services.blog.schemas import BlogTagUpdate
    from app.services.blog.service import BlogService

    async with get_async_session() as session:
        service = BlogService(session)
        tag_id = await _resolve_tag_id(service, slug)
        if tag_id is None:
            console.print(
                f"[{theme.ERROR}]{t('blog.tag_not_found', slug=slug)}[/{theme.ERROR}]"
            )
            raise typer.Exit(1)
        try:
            tag = await service.update_tag(
                tag_id, BlogTagUpdate(name=name, slug=new_slug)
            )
        except ValueError as e:
            console.print(f"[{theme.ERROR}]{e}[/{theme.ERROR}]")
            raise typer.Exit(1) from e

    if tag is None:
        console.print(
            f"[{theme.ERROR}]{t('blog.tag_not_found', slug=slug)}[/{theme.ERROR}]"
        )
        raise typer.Exit(1)

    console.print(
        f"[{theme.ACCENT}]{t('blog.tag_updated', name=tag.name, slug=tag.slug)}[/{theme.ACCENT}]"
    )


async def _tag_delete(slug: str, yes: bool) -> None:
    from app.core.db import get_async_session
    from app.services.blog.service import BlogService

    if not yes:
        confirmed = typer.confirm(t("blog.confirm_delete_tag", slug=slug))
        if not confirmed:
            console.print(f"[dim]{t('blog.cancelled')}[/dim]")
            raise typer.Exit(0)

    async with get_async_session() as session:
        service = BlogService(session)
        tag_id = await _resolve_tag_id(service, slug)
        if tag_id is None:
            console.print(
                f"[{theme.ERROR}]{t('blog.tag_not_found', slug=slug)}[/{theme.ERROR}]"
            )
            raise typer.Exit(1)
        ok = await service.delete_tag(tag_id)

    if not ok:
        console.print(
            f"[{theme.ERROR}]{t('blog.tag_not_found', slug=slug)}[/{theme.ERROR}]"
        )
        raise typer.Exit(1)

    console.print(
        f"[{theme.ACCENT}]{t('blog.tag_deleted', slug=slug)}[/{theme.ACCENT}]"
    )
