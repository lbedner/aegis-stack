"""Test sends for the Overseer Comms page. A channel that is not set up
refuses with the settings it is missing; a provider error is the toast.
Mounted by ``routes/pages.py`` at ``overseer_comms.PARTIALS``."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form
from fastapi.responses import Response

from app.components.web_frontend import overseer_comms
from app.components.web_frontend.rendering import toast_response
from app.models.user import User
from app.services.auth.deps import get_optional_user
from app.services.comms.email import EmailError, send_email_simple
from app.services.comms.sms import SMSError, send_sms_simple

from .overseer_auth import signed_in

router = APIRouter(prefix=overseer_comms.PARTIALS)


def _unready(key: str) -> Response | None:
    missing = overseer_comms.channel(key)["missing"]
    return toast_response(" ".join(missing), "error") if missing else None


@router.post("/test-email")
async def test_email(
    to: Annotated[str, Form()], user: User | None = Depends(get_optional_user)
) -> Response:
    signed_in(user)
    if refused := _unready("email"):
        return refused
    try:
        await send_email_simple(
            to, "Test from the Overseer", text="Email is set up and sending."
        )
    except EmailError as exc:
        return toast_response(str(exc), "error")
    return toast_response(f"Test email sent to {to}")


@router.post("/test-sms")
async def test_sms(
    to: Annotated[str, Form()], user: User | None = Depends(get_optional_user)
) -> Response:
    signed_in(user)
    if refused := _unready("sms"):
        return refused
    try:
        await send_sms_simple(to, "Test from the Overseer: SMS is set up.")
    except SMSError as exc:
        return toast_response(str(exc), "error")
    return toast_response(f"Test SMS sent to {to}")
