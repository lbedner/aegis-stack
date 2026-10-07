"""Actions for the Overseer Payment page: refund a transaction, cancel a
subscription at period end, and make a checkout link. Mounted by
``routes/pages.py`` at ``overseer_payment.PARTIALS``; every write goes
through ``PaymentService``, so the provider sees exactly what the REST API
would send it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
import stripe

from app.components.web_frontend import overseer_payment
from app.components.web_frontend.filters import money_to_cents
from app.components.web_frontend.rendering import dialog, go_to, toast_response
from app.core.config import settings
from app.services.payment.catalog import get_catalog
from app.services.payment.constants import PriceType, RefundReason
from app.services.payment.deps import get_payment_service
from app.services.payment.service import PaymentService

router = APIRouter(prefix=overseer_payment.PARTIALS)

SUBSCRIPTIONS_PAGE = f"{overseer_payment.PAGE}/subscriptions"


def _provider_said(exc: stripe.StripeError) -> Response:
    return toast_response(exc.user_message or str(exc), "error")


@router.get("/transactions/{transaction_id}/drawer", response_class=HTMLResponse)
async def drawer(
    request: Request,
    transaction_id: int,
    service: PaymentService = Depends(get_payment_service),
) -> Response:
    """One transaction in the drawer, with the refund form when it can be."""
    context = await overseer_payment.transaction_context(service, transaction_id)
    if context is None:
        raise HTTPException(status_code=404, detail="That transaction is gone.")
    return dialog(request, "pages/overseer/payment/_drawer.html", **context)


@router.post("/transactions/{transaction_id}/refund")
async def refund(
    transaction_id: int,
    amount: Annotated[str, Form()] = "",
    original: Annotated[int, Form()] = 0,
    reason: Annotated[str, Form()] = RefundReason.DEFAULT,
    service: PaymentService = Depends(get_payment_service),
) -> Response:
    """A partial refund below the original; the whole amount (or none
    given) is a full one."""
    cents = money_to_cents(amount)
    if cents is None or cents < 0 or reason not in RefundReason.ALL:
        return toast_response("The amount is dollars and cents, like 12.50.", "error")
    try:
        done = await service.refund_transaction(
            transaction_id=transaction_id,
            amount=cents if 0 < cents < original else None,
            reason=reason,
        )
    except stripe.StripeError as exc:
        return _provider_said(exc)
    if done is None:
        raise HTTPException(status_code=404, detail="That transaction is gone.")
    return go_to(
        overseer_payment.transaction_url(transaction_id),
        f"Refund issued for #{transaction_id}",
        "#overseer-main",
    )


@router.get(
    "/subscriptions/{subscription_id}/confirm-cancel", response_class=HTMLResponse
)
async def confirm_cancel(
    request: Request,
    subscription_id: int,
) -> Response:
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title="Cancel this subscription?",
        body="It stops renewing. The customer keeps access until the period ends.",
        url=f"{overseer_payment.PARTIALS}/subscriptions/{subscription_id}/cancel",
        label="Cancel subscription",
        method="post",
        done="Subscription will cancel at period end",
    )


@router.post("/subscriptions/{subscription_id}/cancel")
async def cancel(
    subscription_id: int,
    service: PaymentService = Depends(get_payment_service),
) -> Response:
    try:
        done = await service.cancel_subscription(subscription_id)
    except stripe.StripeError as exc:
        # A ``data-api-done`` button: the failure's ``detail`` is its toast.
        raise HTTPException(
            status_code=400, detail=exc.user_message or str(exc)
        ) from None
    if done is None:
        raise HTTPException(status_code=404, detail="That subscription is gone.")
    return Response(status_code=200)


@router.post("/checkout", response_class=HTMLResponse)
async def checkout(
    request: Request,
    price: Annotated[str, Form()] = "",
    quantity: Annotated[int, Form()] = 1,
    success_url: Annotated[str, Form()] = "",
    cancel_url: Annotated[str, Form()] = "",
    service: PaymentService = Depends(get_payment_service),
) -> Response:
    """A checkout link for one catalog price. A recurring price is a
    subscription, which is always one seat."""
    try:
        # The catalog is the provider's too: a refused key fails here first.
        catalog = await get_catalog(service)
        entry = next((e for e in catalog if e.price_id == price), None)
        if entry is None:
            return toast_response("That price is not in the catalog.", "error")
        recurring = entry.price_type == PriceType.RECURRING or entry.interval is not None
        result = await service.create_checkout(
            price_id=entry.price_id,
            quantity=1 if recurring else max(1, quantity),
            mode="subscription" if recurring else "payment",
            success_url=success_url or settings.PAYMENT_SUCCESS_URL,
            cancel_url=cancel_url or settings.PAYMENT_CANCEL_URL,
        )
    except stripe.StripeError as exc:
        return _provider_said(exc)
    return dialog(
        request,
        "pages/overseer/payment/_checkout_result.html",
        result=result,
        price=overseer_payment.price_label(entry),
    )
