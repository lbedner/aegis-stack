"""The Overseer Secrets page's set dialog: paste a value, replace or remove
a stored one; and the Test button, which asks the provider. Mounted by ``routes/pages.py`` at ``overseer_secrets.PARTIALS``
behind the admin-only Overseer gate.

Writes go through ``app.core.secrets``, whose refusals (set in ``.env``,
a read-only store, a key the provider refuses) come back as the form's
error. No answer carries the
value.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_secrets
from app.components.web_frontend.rendering import dialog, dialog_done, toast_response
from app.core import secrets
from app.models.user import User
from app.services.auth.deps import get_optional_user

from .overseer_auth import signed_in

router = APIRouter(prefix=overseer_secrets.PARTIALS)

FORM = "pages/overseer/secrets/_set.html"


async def _form(
    request: Request, name: str, errors: list[str], status_code: int = 200
) -> Response:
    row = next((r for r in await secrets.status() if r.name == name), None)
    if row is None:
        raise HTTPException(status_code=404)
    return dialog(
        request,
        FORM,
        status_code,
        row=row,
        errors=errors,
        url=f"{overseer_secrets.PARTIALS}/{name}",
        stored=row.is_set and row.source == secrets.store_name(),
        # What the provider offers, for a field shown in the clear.
        choices=await secrets.choices(name) if row.choosable and not row.secret else [],
    )


@router.get("/{name}", response_class=HTMLResponse)
async def set_form(
    request: Request, name: str, user: User | None = Depends(get_optional_user)
) -> Response:
    """The set dialog, empty whatever is stored."""
    signed_in(user)
    return await _form(request, name, [])


@router.post("/{name}", response_class=HTMLResponse)
async def save(
    request: Request,
    name: str,
    value: Annotated[str, Form()] = "",
    user: User | None = Depends(get_optional_user),
) -> Response:
    viewer = signed_in(user)
    if not value.strip():
        return await _form(request, name, ["Paste a value."], 422)
    try:
        verdict = await secrets.put(name, value.strip(), actor=viewer.email)
    except (secrets.SecretsReadOnlyError, secrets.SecretRejectedError) as exc:
        return await _form(request, name, [str(exc)], 422)
    except secrets.UnknownSecretError:
        raise HTTPException(status_code=404) from None
    if verdict is None:
        return dialog_done(overseer_secrets.url(), f"{name} saved")
    tone = overseer_secrets.VERDICT_TONES[verdict.result]
    word = "verified" if verdict.result == secrets.VERIFIED else "not verified"
    return dialog_done(
        overseer_secrets.url(), f"{name} saved, {word}. {verdict.message}", tone
    )


@router.post("/{name}/test")
async def check_key(
    name: str, user: User | None = Depends(get_optional_user)
) -> Response:
    """Check the key in effect with its provider; the answer is a toast."""
    signed_in(user)
    try:
        verdict = await secrets.test(name)
    except secrets.UnknownSecretError:
        raise HTTPException(status_code=404) from None
    return toast_response(
        verdict.message, overseer_secrets.VERDICT_TONES[verdict.result]
    )


@router.post("/{name}/remove", response_class=HTMLResponse)
async def remove(
    request: Request, name: str, user: User | None = Depends(get_optional_user)
) -> Response:
    viewer = signed_in(user)
    try:
        await secrets.delete(name, actor=viewer.email)
    except secrets.SecretsReadOnlyError as exc:
        return await _form(request, name, [str(exc)], 422)
    except secrets.UnknownSecretError:
        raise HTTPException(status_code=404) from None
    return dialog_done(overseer_secrets.url(), f"{name} removed")
