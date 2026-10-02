"""Test sends for the Overseer Comms page. A channel that is not set up
refuses with the settings it is missing; a provider error is the toast.
Mounted by ``routes/pages.py`` at ``overseer_comms.PARTIALS``."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_comms
from app.components.web_frontend.rendering import dialog, toast_response
from app.models.user import User
from app.services.auth.deps import get_optional_user
from app.services.comms.email import EmailError, send_email_simple
from app.services.comms.sms import SMSError, send_sms_simple

from .overseer_auth import signed_in

router = APIRouter(prefix=overseer_comms.PARTIALS)

DOMAIN_FORM = "pages/overseer/comms/_domain_new.html"


async def _unready(key: str) -> Response | None:
    missing = (await overseer_comms.channel(key))["missing"]
    return toast_response(" ".join(missing), "error") if missing else None


@router.post("/test-email")
async def test_email(
    to: Annotated[str, Form()], user: User | None = Depends(get_optional_user)
) -> Response:
    signed_in(user)
    if refused := await _unready("email"):
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
    if refused := await _unready("sms"):
        return refused
    try:
        await send_sms_simple(to, "Test from the Overseer: SMS is set up.")
    except SMSError as exc:
        return toast_response(str(exc), "error")
    return toast_response(f"Test SMS sent to {to}")


@router.post("/domains/{domain}/check")
async def check_domain(
    domain: str, user: User | None = Depends(get_optional_user)
) -> Response:
    """Ask Resend to check the domain's DNS now; the answer is a toast."""
    from app.services.ops.adapters.resend import ResendAdapter

    signed_in(user)
    try:
        status = await ResendAdapter().check_domain(domain)
    except Exception as exc:  # noqa: BLE001 - shown, not swallowed
        return toast_response(f"Resend could not check {domain}: {exc}", "error")
    return toast_response(
        f"{domain}: {status.status}", "ok" if status.verified else "warn"
    )


@router.get("/domains/new", response_class=HTMLResponse)
async def new_domain(
    request: Request, user: User | None = Depends(get_optional_user)
) -> Response:
    signed_in(user)
    return dialog(request, DOMAIN_FORM, errors=[], partials=overseer_comms.PARTIALS)


@router.post("/domains", response_class=HTMLResponse)
async def add_domain(
    request: Request,
    domain: Annotated[str, Form()],
    user: User | None = Depends(get_optional_user),
) -> Response:
    """Add the domain to Resend (or find it, if it is there) and show the
    DNS records it needs."""
    from app.services.ops.adapters.resend import ResendAdapter

    signed_in(user)
    try:
        added = await ResendAdapter().add_domain(domain)
    except Exception as exc:  # noqa: BLE001 - the form shows the reason
        return dialog(
            request,
            DOMAIN_FORM,
            422,
            errors=[str(exc)],
            partials=overseer_comms.PARTIALS,
        )
    return dialog(
        request,
        "pages/overseer/comms/_domain_records.html",
        domain=added.domain,
        records=added.required_records,
        check_url=f"{overseer_comms.PARTIALS}/domains/{added.domain}/check",
    )
