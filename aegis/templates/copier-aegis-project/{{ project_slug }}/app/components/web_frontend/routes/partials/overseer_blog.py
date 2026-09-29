"""Actions for the Overseer Blog page: create and save posts from the
editor, publish and archive from a row, and add and delete tags. Mounted
by ``routes/pages.py`` at ``overseer_blog.PARTIALS``; every write goes
through ``BlogService`` on the request's session.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from app.components.web_frontend import overseer_blog
from app.components.web_frontend.rendering import dialog, go_to, toast_response
from app.models.user import User
from app.services.auth.deps import get_optional_user
from app.services.blog.deps import get_blog_service
from app.services.blog.schemas import BlogPostCreate, BlogPostUpdate, BlogTagCreate
from app.services.blog.service import BlogService

from .overseer_auth import signed_in

router = APIRouter(prefix=overseer_blog.PARTIALS)

TAGS_PAGE = f"{overseer_blog.PAGE}/tags"


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    return f"{str(error['loc'][-1]).replace('_', ' ').capitalize()}: {error['msg']}"


@router.get("/posts/{post}/drawer", response_class=HTMLResponse)
async def drawer(
    request: Request,
    post: str,
    user: User | None = Depends(get_optional_user),
    service: BlogService = Depends(get_blog_service),
) -> Response:
    """A post's editor in the drawer, or a new draft's for ``new``."""
    signed_in(user)
    if post != overseer_blog.NEW and not post.isdigit():
        raise HTTPException(status_code=404)
    context = await overseer_blog.editor_context(
        service, None if post == overseer_blog.NEW else int(post)
    )
    if post != overseer_blog.NEW and context["post"] is None:
        raise HTTPException(status_code=404, detail="That post is gone.")
    return dialog(request, "pages/overseer/blog/_drawer.html", **context)


@router.post("/posts")
async def create_post(
    title: Annotated[str, Form()] = "",
    content: Annotated[str, Form()] = "",
    excerpt: Annotated[str, Form()] = "",
    slug: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    user: User | None = Depends(get_optional_user),
    service: BlogService = Depends(get_blog_service),
) -> Response:
    """A new draft, then its editor."""
    viewer = signed_in(user)
    try:
        payload = BlogPostCreate(
            title=title,
            slug=slug or None,
            excerpt=excerpt or None,
            content=content,
            tag_slugs=overseer_blog.parse_tags(tags),
        )
        post = await service.create_post(
            payload, author_id=viewer.id, author_name=viewer.full_name or viewer.email
        )
    except ValidationError as exc:
        return toast_response(_first_error(exc), "error")
    except ValueError as exc:
        return toast_response(str(exc), "error")
    return go_to(
        overseer_blog.editor_url(post.id), "Draft created", target="#overseer-main"
    )


@router.post("/posts/{post_id}")
async def save_post(
    post_id: int,
    title: Annotated[str, Form()] = "",
    content: Annotated[str, Form()] = "",
    excerpt: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    user: User | None = Depends(get_optional_user),
    service: BlogService = Depends(get_blog_service),
) -> Response:
    signed_in(user)
    try:
        payload = BlogPostUpdate(
            title=title,
            excerpt=excerpt or None,
            content=content,
            tag_slugs=overseer_blog.parse_tags(tags),
        )
        post = await service.update_post(post_id, payload)
    except ValidationError as exc:
        return toast_response(_first_error(exc), "error")
    except ValueError as exc:
        return toast_response(str(exc), "error")
    if post is None:
        raise HTTPException(status_code=404, detail="That post is gone.")
    return go_to(overseer_blog.editor_url(post.id), "Saved", target="#overseer-main")


@router.post("/posts/{post_id}/{action}")
async def move_post(
    post_id: int,
    action: str,
    user: User | None = Depends(get_optional_user),
    service: BlogService = Depends(get_blog_service),
) -> Response:
    """Publish or archive. The button says what happened (``data-api-done``)
    and the page reloads where it was."""
    signed_in(user)
    moves = {"publish": service.publish_post, "archive": service.archive_post}
    if action not in moves:
        raise HTTPException(status_code=404)
    if await moves[action](post_id) is None:
        raise HTTPException(status_code=404, detail="That post is gone.")
    return Response(status_code=200)


@router.post("/tags")
async def create_tag(
    name: Annotated[str, Form()] = "",
    user: User | None = Depends(get_optional_user),
    service: BlogService = Depends(get_blog_service),
) -> Response:
    signed_in(user)
    try:
        tag = await service.create_tag(BlogTagCreate(name=name))
    except ValidationError as exc:
        return toast_response(_first_error(exc), "error")
    except ValueError as exc:
        return toast_response(str(exc), "error")
    return go_to(TAGS_PAGE, f"Added {tag.name}", target="#overseer-main")


@router.get("/tags/{tag_id}/confirm-delete", response_class=HTMLResponse)
async def confirm_delete_tag(
    request: Request,
    tag_id: int,
    user: User | None = Depends(get_optional_user),
    service: BlogService = Depends(get_blog_service),
) -> Response:
    signed_in(user)
    tag = next((t for t in await service.list_tags() if t.id == tag_id), None)
    if tag is None:
        raise HTTPException(status_code=404)
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete {tag.name}?",
        body="The tag comes off every post that has it. The posts stay.",
        url=f"{overseer_blog.PARTIALS}/tags/{tag.id}",
        label="Delete",
        method="delete",
        done="Tag deleted",
    )


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    user: User | None = Depends(get_optional_user),
    service: BlogService = Depends(get_blog_service),
) -> Response:
    signed_in(user)
    if not await service.delete_tag(tag_id):
        raise HTTPException(status_code=404, detail="That tag is gone.")
    return Response(status_code=204)
