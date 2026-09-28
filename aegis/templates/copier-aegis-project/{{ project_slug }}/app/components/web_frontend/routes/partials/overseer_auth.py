"""Fragments for the Overseer Authentication page: confirmations and the
add-user form. Mounted by ``routes/pages.py`` at ``overseer_auth.PARTIALS``.

Overseer calls the auth API's handlers directly, which skips their guard
dependencies, so every route here asks the API's own policy
(``may_admin_users``) before it shows or does anything to another account.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.components.backend.api.auth.admin import create_user as api_create_user
from app.components.backend.api.auth.admin import may_admin_users
from app.components.web_frontend import overseer_auth
from app.components.web_frontend.overseer_nav import find_installed, page_url
from app.components.web_frontend.rendering import dialog, dialog_done
from app.core.audit import AuditEmitter, get_audit
from app.core.db import get_async_db
from app.models.user import User, UserCreate
from app.services.auth.deps import get_optional_user, get_user_service
from app.services.auth.users import UserService

router = APIRouter(prefix=overseer_auth.PARTIALS)

USER_ACTIONS = {"activate", "deactivate", "delete"}
USERS_PAGE = page_url("services", "auth") + "/users"
NEW_USER_FORM = "pages/overseer/auth/_new_user.html"


def signed_in(user: User | None) -> User:
    if user is None:
        raise HTTPException(status_code=401)
    return user


def _admin(user: User | None) -> User:
    viewer = signed_in(user)
    if not may_admin_users(viewer):
        raise HTTPException(status_code=403)
    return viewer


@router.get("/confirm/{action}/{target}", response_class=HTMLResponse)
async def confirm(
    request: Request,
    action: str,
    target: str,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """The confirmation for an action. Its button calls the auth API."""
    viewer = _admin(user) if action in USER_ACTIONS else signed_in(user)
    item = find_installed("services", "auth")
    if item is None:
        raise HTTPException(status_code=404)
    context = await overseer_auth.confirmation(
        action, target, item.component, viewer, db
    )
    if context is None:
        raise HTTPException(status_code=404)
    return dialog(request, "pages/overseer/_confirm.html", **context)


@router.get("/users/new", response_class=HTMLResponse)
async def new_user(
    request: Request, user: User | None = Depends(get_optional_user)
) -> Response:
    """The add-user form."""
    _admin(user)
    return dialog(
        request, NEW_USER_FORM, form={}, errors=[], partials=overseer_auth.PARTIALS
    )


def _form(request: Request, form: dict[str, str], errors: list[str]) -> Response:
    """The add-user form again, with what was typed and what went wrong."""
    return dialog(
        request,
        NEW_USER_FORM,
        422,
        form=form,
        errors=errors,
        partials=overseer_auth.PARTIALS,
    )


def _messages(exc: ValidationError) -> list[str]:
    return [
        f"{str(error['loc'][-1]).replace('_', ' ').capitalize()}: {error['msg']}"
        for error in exc.errors()
    ]


@router.post("/users", response_class=HTMLResponse)
async def create_user(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    full_name: Annotated[str, Form()] = "",
    user: User | None = Depends(get_optional_user),
    user_service: UserService = Depends(get_user_service),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    """Add an account through the API's own handler; errors re-render the form."""
    viewer = _admin(user)
    form = {"email": email, "full_name": full_name}
    try:
        data = UserCreate(email=email, password=password, full_name=full_name or None)
    except ValidationError as exc:
        return _form(request, form, _messages(exc))
    try:
        await api_create_user(
            user_data=data, current_user=viewer, user_service=user_service, audit=audit
        )
    except HTTPException as exc:
        return _form(request, form, [str(exc.detail)])
    return dialog_done(USERS_PAGE, "User created")
