"""The Overseer Secrets page's set dialog: paste a value, replace or remove
a stored one; and the Test button, which asks the provider. Mounted by ``routes/pages.py`` at ``overseer_secrets.PARTIALS``
behind Overseer's gate (``overseer_access``).

Writes go through ``app.core.secrets``, whose refusals (set in ``.env``,
a read-only store, a key the provider refuses) come back as the form's
error. No answer carries the
value.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_secrets, overseer_settings
from app.components.web_frontend.overseer_access import overseer_actor
from app.components.web_frontend.rendering import dialog, dialog_done, toast_response
from app.core import saved_settings, secrets
from app.services.shared.deps import Actor

router = APIRouter(prefix=overseer_secrets.PARTIALS)

FORM = "pages/overseer/secrets/_set.html"


def _home(name: str) -> str:
    """The page a dialog returns to: Settings for a setting, else Secrets."""
    if secrets.is_setting(name):
        return overseer_settings.ITEM.url
    return overseer_secrets.url()


async def _form(
    request: Request, name: str, errors: list[str], status_code: int = 200
) -> Response:
    row = await secrets.status_of(name)
    if row is None:
        raise HTTPException(status_code=404)
    offered = await secrets.choices(name) if row.choosable and not row.secret else []
    return dialog(
        request,
        FORM,
        status_code,
        row=row,
        errors=errors,
        url=f"{overseer_secrets.PARTIALS}/{name}",
        stored=row.is_set and row.source == secrets.store_name(),
        # What the provider offers, for a field shown in the clear: a hint
        # list for provider config, the only values for a setting.
        choices=offered if not row.setting else [],
        picks=[{"id": v, "name": label} for v, label in offered] if row.setting else [],
    )


@router.get("/{name}", response_class=HTMLResponse)
async def set_form(request: Request, name: str) -> Response:
    """The set dialog, empty whatever is stored."""
    return await _form(request, name, [])


@router.post("/{name}", response_class=HTMLResponse)
async def save(
    request: Request,
    name: str,
    value: Annotated[str, Form()] = "",
    actor: Actor = Depends(overseer_actor),
) -> Response:
    if not value.strip():
        return await _form(request, name, ["Paste a value."], 422)
    try:
        verdict = await secrets.put(name, value.strip(), actor=actor.label)
    except (secrets.SecretsReadOnlyError, secrets.SecretRejectedError) as exc:
        return await _form(request, name, [str(exc)], 422)
    except secrets.UnknownSecretError:
        raise HTTPException(status_code=404) from None
    if verdict is None:
        return dialog_done(_home(name), saved_settings.saved(name))
    return dialog_done(
        _home(name),
        saved_settings.saved(name, verdict.result, verdict.message),
        overseer_secrets.VERDICT_TONES[verdict.result],
    )


@router.post("/{name}/test")
async def check_key(name: str) -> Response:
    """Check the key in effect with its provider; the answer is a toast."""
    try:
        verdict = await secrets.test(name)
    except secrets.UnknownSecretError:
        raise HTTPException(status_code=404) from None
    return toast_response(
        verdict.message, overseer_secrets.VERDICT_TONES[verdict.result]
    )


@router.post("/{name}/remove", response_class=HTMLResponse)
async def remove(
    request: Request, name: str, actor: Actor = Depends(overseer_actor)
) -> Response:
    try:
        await secrets.delete(name, actor=actor.label)
    except secrets.SecretsReadOnlyError as exc:
        return await _form(request, name, [str(exc)], 422)
    except secrets.UnknownSecretError:
        raise HTTPException(status_code=404) from None
    return dialog_done(_home(name), saved_settings.removed(name))
