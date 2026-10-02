"""Context for the Overseer Payment page's sections.

The Flet payment modal's tabs: the account at a glance with 30 days of
revenue and the provider's state, then every transaction, subscription
and dispute, and a checkout made against the live catalog. Reads go
through ``PaymentService`` on the request's session; the provider's
health is the payment health check's cached probe, so a page view never
costs a Stripe call. Registered only in projects with the payment service
(see ``overseer_sections``).
"""

from datetime import UTC, datetime
from typing import Any

from app.core import secrets
from app.core.config import settings
from app.core.formatting import format_relative_time
from app.services.payment.catalog import get_catalog
from app.services.payment.constants import (
    DisputeStatus,
    RefundReason,
    SubscriptionStatus,
    TransactionStatus,
    TransactionType,
)
from app.services.payment.health import cached_provider_health
from app.services.payment.models import (
    PaymentDispute,
    PaymentSubscription,
    PaymentTransaction,
)
from app.services.payment.providers.base import CatalogEntry
from app.services.payment.service import PaymentService
from app.services.system.models import ComponentStatus

from .filters import cents_to_input, dollars, money
from .overseer_nav import SectionRequest, page_url
from .rendering import (
    chart,
    drawer_state,
    page_number,
    pager,
    status_cell,
    with_query,
)

SECTIONS = (
    (None, {"overview": "Overview"}),
    (
        "Activity",
        {
            "transactions": "Transactions",
            "subscriptions": "Subscriptions",
            "disputes": "Disputes",
        },
    ),
    ("Actions", {"checkout": "Checkout"}),
)

PAGE = page_url("services", "payment")
PARTIALS = "/partials/overseer/payment"
PAGE_SIZE = 25
REVENUE_DAYS = 30

TONES = {
    TransactionStatus.SUCCEEDED: "ok",
    TransactionStatus.PENDING: "warn",
    TransactionStatus.FAILED: "error",
    TransactionStatus.CANCELED: "error",
    SubscriptionStatus.ACTIVE: "ok",
    SubscriptionStatus.TRIALING: "accent",
    SubscriptionStatus.PAST_DUE: "warn",
    SubscriptionStatus.INCOMPLETE: "warn",
    SubscriptionStatus.UNPAID: "error",
    DisputeStatus.NEEDS_RESPONSE: "error",
    DisputeStatus.WARNING_ISSUED: "warn",
    DisputeStatus.LOST: "error",
    DisputeStatus.WON: "ok",
    DisputeStatus.WARNING_CLOSED: "ok",
}
REFUNDABLE_STATUSES = {
    TransactionStatus.SUCCEEDED,
    TransactionStatus.PARTIALLY_REFUNDED,
}
REFUNDABLE_TYPES = {TransactionType.CHARGE, TransactionType.SUBSCRIPTION}
TRANSACTION_CHIPS = (
    (None, "All"),
    (TransactionStatus.SUCCEEDED, "Succeeded"),
    (TransactionStatus.PENDING, "Pending"),
    (TransactionStatus.FAILED, "Failed"),
    (TransactionStatus.REFUNDED, "Refunded"),
)
SUBSCRIPTION_CHIPS = (
    (None, "All"),
    (SubscriptionStatus.ACTIVE, "Active"),
    (SubscriptionStatus.TRIALING, "Trialing"),
    (SubscriptionStatus.PAST_DUE, "Past due"),
    (SubscriptionStatus.CANCELED, "Canceled"),
)
DISPUTE_CHIPS = ((None, "All"), ("open", "Open"))
REASONS = [{"id": r, "name": RefundReason.LABELS[r]} for r in RefundReason.ALL]
DRAWER_PARAM = "transaction"


def transaction_url(transaction_id: int, **filters: str | None) -> str:
    """The transactions list with this one open in the drawer."""
    return with_query(
        f"{PAGE}/transactions", **filters, **{DRAWER_PARAM: str(transaction_id)}
    )


def status(value: str) -> dict[str, str]:
    """A status badge: ``partially_refunded`` reads "Partially refunded"."""
    return status_cell(value.replace("_", " ").capitalize(), TONES.get(value, "muted"))


def price_label(entry: CatalogEntry) -> str:
    """``Pro - $10.00 / month``."""
    per = f" / {entry.interval}" if entry.interval else ""
    return f"{entry.product_name} - {money(entry.amount, entry.currency)}{per}"


def _chips(
    chips: tuple[tuple[str | None, str], ...], chosen: str | None, path: str
) -> list[dict[str, Any]]:
    return [
        {"label": label, "url": with_query(path, status=key), "active": key == chosen}
        for key, label in chips
    ]


def _chosen(
    query: dict[str, str], chips: tuple[tuple[str | None, str], ...]
) -> str | None:
    wanted = query.get("status") or None
    return wanted if wanted in {key for key, _ in chips} else None


def _provider(summary: Any, unset: bool) -> dict[str, Any]:
    """The provider card; an unset key reads as "Not configured", not as a
    test-mode account that happens to be down."""
    mode = "Not configured" if unset else ("Test" if summary.is_test_mode else "Live")
    return {
        "healthy": summary.healthy,
        "facts": [
            ("Provider", summary.provider_display_name),
            ("Mode", mode),
            ("Status", "Connected" if summary.healthy else "Disconnected"),
            ("API version", summary.api_version),
            ("Details", None if summary.healthy else summary.health_message),
        ],
    }


def _revenue(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Revenue as a running total, so the line reads as growth."""
    running, values = 0.0, []
    for point in points:
        running += dollars(point["amount_cents"])
        values.append(round(running, 2))
    labels = [datetime.fromisoformat(p["date"]).strftime("%b %d") for p in points]
    return chart(labels, "Revenue", values, money=True)


async def _overview(service: PaymentService) -> dict[str, Any]:
    summary = await service.get_status_summary(
        provider_health=await cached_provider_health(service)
    )
    return {
        "figures": [
            {"label": "Transactions", "value": f"{summary.total_transactions:,}"},
            {"label": "Revenue", "value": money(summary.total_revenue_cents)},
            {"label": "Active subscriptions", "value": summary.active_subscriptions},
            {
                "label": "Open disputes",
                "value": summary.open_disputes,
                "tone": "error" if summary.open_disputes else None,
            },
        ],
        "provider": _provider(summary, not await secrets.get("STRIPE_SECRET_KEY")),
        "revenue": _revenue(await service.get_revenue_timeseries(REVENUE_DAYS)),
    }


def refundable(t: PaymentTransaction) -> bool:
    return t.status in REFUNDABLE_STATUSES and t.type in REFUNDABLE_TYPES


def _transaction_row(t: PaymentTransaction, **filters: str | None) -> dict[str, Any]:
    return {
        "id": {"label": f"#{t.id}", "url": transaction_url(t.id or 0, **filters)},
        "type": t.type.capitalize(),
        "status": status(t.status),
        "amount": t.amount,
        "currency": t.currency.upper(),
        "description": t.description,
        "created": format_relative_time(t.created_at),
    }


async def _transactions(
    service: PaymentService, query: dict[str, str], path: str
) -> dict[str, Any]:
    chosen = _chosen(query, TRANSACTION_CHIPS)
    page = page_number(query.get("page"))
    rows, total = await service.get_transactions(
        page=page, page_size=PAGE_SIZE, status=chosen
    )
    params = {"status": chosen} if chosen else {}
    wanted = query.get(DRAWER_PARAM) or ""
    return drawer_state(
        DRAWER_PARAM,
        f"{PARTIALS}/transactions/{wanted}/drawer" if wanted.isdigit() else None,
    ) | {
        "chips": _chips(TRANSACTION_CHIPS, chosen, path),
        "rows": [_transaction_row(t, status=chosen) for t in rows],
        "pager": pager(path, page, PAGE_SIZE, total, **params),
    }


def _subscription_row(
    s: PaymentSubscription, customers: dict[int, Any]
) -> dict[str, Any]:
    customer = customers.get(s.customer_id)
    cancellable = s.status == SubscriptionStatus.ACTIVE and not s.cancel_at_period_end
    return {
        "customer": ((customer.metadata_ or {}).get("name") or customer.email)
        if customer
        else None,
        "plan": s.plan_name,
        "status": status(s.status),
        "ends": ("Ends " if s.cancel_at_period_end else "Renews ")
        + s.current_period_end.strftime("%b %d, %Y")
        if s.status != SubscriptionStatus.CANCELED
        else None,
        "updated": format_relative_time(s.updated_at),
        "cancel_url": f"{PARTIALS}/subscriptions/{s.id}/confirm-cancel"
        if cancellable
        else None,
    }


async def _subscriptions(
    service: PaymentService, query: dict[str, str], path: str
) -> dict[str, Any]:
    chosen = _chosen(query, SUBSCRIPTION_CHIPS)
    subs = await service.get_subscriptions(status=chosen)
    customers = await service.get_customers(s.customer_id for s in subs)
    return {
        "chips": _chips(SUBSCRIPTION_CHIPS, chosen, path),
        "rows": [_subscription_row(s, customers) for s in subs],
    }


def _due(dispute: PaymentDispute) -> dict[str, str] | None:
    """When the evidence is due, as a badge: red inside three days."""
    if dispute.evidence_due_by is None or dispute.status not in DisputeStatus.OPEN:
        return None
    due = dispute.evidence_due_by.replace(tzinfo=dispute.evidence_due_by.tzinfo or UTC)
    days = (due - datetime.now(UTC)).days
    label = due.strftime("%b %d") + (f" ({days}d)" if days >= 0 else " (past)")
    return status_cell(label, "error" if days < 3 else "warn")


async def _disputes(
    service: PaymentService, query: dict[str, str], path: str
) -> dict[str, Any]:
    chosen = _chosen(query, DISPUTE_CHIPS)
    return {
        "chips": _chips(DISPUTE_CHIPS, chosen, path),
        "rows": [
            {
                "id": d.id,
                "transaction": d.transaction_id,
                "status": status(d.status),
                "reason": (d.reason or "").replace("_", " ") or None,
                "amount": d.amount,
                "currency": d.currency.upper(),
                "due": _due(d),
            }
            for d in await service.get_disputes(status=chosen)
        ],
    }


async def _checkout(service: PaymentService) -> dict[str, Any]:
    if not await secrets.get("STRIPE_SECRET_KEY"):
        return {"missing": "STRIPE_SECRET_KEY"}
    entries = await get_catalog(service)
    return {
        "prices": [{"id": e.price_id, "name": price_label(e)} for e in entries],
        "success_url": settings.PAYMENT_SUCCESS_URL,
        "cancel_url": settings.PAYMENT_CANCEL_URL,
    }


async def transaction_context(
    service: PaymentService, transaction_id: int
) -> dict[str, Any] | None:
    """The drawer's context for one transaction, or None when it is gone."""
    t = await service.get_transaction_by_id(transaction_id)
    if t is None:
        return None
    customer = (await service.get_customers([t.customer_id])).get(t.customer_id or 0)
    return {
        "txn": t,
        "status": status(t.status),
        "facts": [
            ("Type", t.type.capitalize()),
            ("Amount", money(t.amount, t.currency)),
            (
                "Customer",
                ((customer.metadata_ or {}).get("name") or customer.email)
                if customer
                else None,
            ),
            ("Email", customer.email if customer else None),
            ("Description", t.description),
            ("Provider ID", t.provider_transaction_id),
            ("Created", format_relative_time(t.created_at)),
            ("Updated", format_relative_time(t.updated_at)),
        ],
        "refund": {
            "url": f"{PARTIALS}/transactions/{t.id}/refund",
            "amount": cents_to_input(t.amount),
            "reasons": REASONS,
            "reason": RefundReason.DEFAULT,
        }
        if refundable(t)
        else None,
    }


async def section_context(
    section: str, payment: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    service = PaymentService(req.db)
    context: dict[str, Any] = {"partials": PARTIALS}
    query = dict(req.query)
    if section == "overview":
        return context | await _overview(service)
    if section == "transactions":
        return context | await _transactions(service, query, req.path)
    if section == "subscriptions":
        return context | await _subscriptions(service, query, req.path)
    if section == "disputes":
        return context | await _disputes(service, query, req.path)
    return context | await _checkout(service)
