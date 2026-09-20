"""The end-to-end run: drive a checkout through and watch it land."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
import typer

from app.cli import theme
from app.i18n import t

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.payment.models import PaymentSubscription, PaymentTransaction

console = theme.console()


async def _e2e(
    *,
    user_email: str,
    primary_price: str,
    secondary_price: str,
    cleanup: bool,
    skip_existing: bool,
) -> None:
    """Async implementation of the e2e command - orchestrates the full
    lifecycle and writes a per-leg pass/fail summary to stdout."""
    import asyncio as _asyncio

    from sqlmodel import select
    import stripe

    from app.core.config import settings
    from app.core.db import get_async_session
    from app.models.user import User
    from app.services.payment.models import (
        PaymentCustomer,
        PaymentTransaction,
    )
    from app.services.payment.service import PaymentService

    primary = primary_price
    secondary = secondary_price
    if not primary or not secondary or primary == secondary:
        console.print(
            f"[{theme.ERROR}]FAIL[/] need two distinct price ids "
            "(--primary-price and --secondary-price are required)."
        )
        raise typer.Exit(1)

    # Mirror the ``trigger`` command's guard: e2e creates real
    # subscriptions, refunds, and cancels via the Stripe API. Run it
    # against a live key by accident and you'll bill real customers
    # and ship real receipt emails - the sk_test_ prefix check is
    # the line of defence between "smoke test" and "incident".
    api_key = settings.STRIPE_SECRET_KEY or ""
    if not api_key:
        console.print(f"[{theme.ERROR}]{t('payment.stripe_secret_missing')}[/]")
        raise typer.Exit(1)
    if not api_key.startswith("sk_test_"):
        console.print(f"[{theme.ERROR}]{t('payment.refuse_live_key')}[/]")
        raise typer.Exit(1)

    stripe.api_key = api_key

    # Outcomes - one row per leg; we print the table at the end.
    results: list[tuple[str, str, str]] = []  # (leg, status, detail)

    def _step(leg: str, ok: bool, detail: str = "") -> None:
        status = f"[{theme.ACCENT}]PASS[/]" if ok else f"[{theme.ERROR}]FAIL[/]"
        results.append((leg, status, detail))
        console.print(f"  {status} {leg}{(' - ' + detail) if detail else ''}")

    async with get_async_session() as session:
        # ---- Resolve user + customer ----
        user_row = await session.exec(select(User).where(User.email == user_email))
        user = user_row.first()
        if user is None:
            console.print(f"[{theme.ERROR}]FAIL[/] no user with email {user_email}")
            raise typer.Exit(1)

        cust_row = await session.exec(
            select(PaymentCustomer).where(PaymentCustomer.user_id == user.id)
        )
        customer = cust_row.first()
        if customer is None:
            console.print(
                f"[{theme.ERROR}]FAIL[/] user {user_email} has no PaymentCustomer row. "
                "Run one real checkout in the browser first to create it."
            )
            raise typer.Exit(1)

        provider_customer_id = customer.provider_customer_id
        service = PaymentService(session)

        console.print()
        console.print(
            f"[bold]e2e money[/bold] user={user_email} customer={provider_customer_id}"
        )
        console.print()

        # ---- Pre-flight: clear any existing active subscription ----
        existing_active = await service.get_active_subscription_for_user(
            user.id  # type: ignore[arg-type]
        )
        if existing_active is not None:
            if skip_existing:
                _step(
                    "preflight: existing active sub blocks test",
                    False,
                    f"sub_id={existing_active.id} provider_sub_id="
                    f"{existing_active.provider_subscription_id}. "
                    "Re-run without --skip-existing to auto-cancel.",
                )
                _summarize(results)
                raise typer.Exit(1)
            try:
                stripe.Subscription.delete(
                    existing_active.provider_subscription_id,
                    invoice_now=False,
                    prorate=False,
                )
                # Webhook needs a beat to flip the local row.
                await _asyncio.sleep(2)
                _step("preflight: canceled prior active sub", True)
            except Exception as exc:
                _step("preflight: cancel prior sub", False, str(exc))
                _summarize(results)
                raise typer.Exit(1)

        # ---- 1. Subscribe (primary price) ----
        try:
            pm = stripe.PaymentMethod.create(type="card", card={"token": "tok_visa"})
            stripe.PaymentMethod.attach(pm.id, customer=provider_customer_id)
            stripe.Customer.modify(
                provider_customer_id,
                invoice_settings={"default_payment_method": pm.id},
            )
            sub = stripe.Subscription.create(
                customer=provider_customer_id,
                items=[{"price": primary}],
                metadata={"source": "e2e_cli"},
            )
            _step(
                "subscribe: stripe.Subscription.create",
                sub.status == "active",
                f"status={sub.status} sub_id={sub.id}",
            )
        except Exception as exc:
            _step("subscribe: stripe.Subscription.create", False, str(exc))
            _summarize(results)
            raise typer.Exit(1)

        # Wait for webhook chain to settle.
        local_sub = await _wait_for_sub(session, sub.id, expected_status="active")
        if local_sub is None:
            _step(
                "subscribe: webhook -> DB row",
                False,
                "no payment_subscription row materialized after 8s",
            )
            _summarize(results)
            if cleanup:
                try:
                    stripe.Subscription.delete(sub.id)
                except Exception:
                    pass
            raise typer.Exit(1)
        _step(
            "subscribe: webhook -> DB row",
            True,
            f"row id={local_sub.id} plan_name='{local_sub.plan_name}'",
        )

        # Welcome email tag.
        email_tag = (local_sub.metadata_ or {}).get("email") or {}
        _step(
            "subscribe: subscription_started email tagged",
            email_tag.get("kind") == "subscription_started"
            and (
                email_tag.get("sent_at") is not None
                or email_tag.get("skipped") is not None
            ),
            f"kind={email_tag.get('kind')} sent_at={email_tag.get('sent_at')} "
            f"skipped={email_tag.get('skipped')}",
        )

        # Initial invoice receipt tag.
        receipt_txn = await _latest_invoice_txn(session, provider_customer_id)
        receipt_tag = (receipt_txn.metadata_ or {}).get("email") if receipt_txn else {}
        _step(
            "subscribe: invoice_paid email tagged on receipt txn",
            bool(receipt_txn) and receipt_tag.get("kind") == "invoice_paid",
            f"txn id={receipt_txn.id if receipt_txn else None} "
            f"kind={receipt_tag.get('kind') if receipt_tag else None}",
        )

        # ---- 2. Plan change ----
        try:
            await service.change_subscription_plan(
                local_sub.id,  # type: ignore[arg-type]
                new_price_id=secondary,
                user_id=user.id,  # type: ignore[arg-type]
            )
            await session.commit()
            _step("plan_change: service.change_subscription_plan", True)
        except Exception as exc:
            _step("plan_change: service.change_subscription_plan", False, str(exc))

        # Wait for sub.updated webhook to flip plan_name.
        await _asyncio.sleep(2)
        await session.refresh(local_sub)
        for _ in range(6):
            await session.refresh(local_sub)
            new_email = (local_sub.metadata_ or {}).get("email") or {}
            if new_email.get("kind") == "subscription_updated":
                break
            await _asyncio.sleep(1)
        new_email = (local_sub.metadata_ or {}).get("email") or {}
        _step(
            "plan_change: subscription_updated email tagged",
            new_email.get("kind") == "subscription_updated",
            f"kind={new_email.get('kind')} sent_at={new_email.get('sent_at')}",
        )

        # ---- 3. Refund ----
        if receipt_txn is not None:
            try:
                refund_row = await service.refund_transaction(
                    receipt_txn.id,  # type: ignore[arg-type]
                    user_id=user.id,  # type: ignore[arg-type]
                )
                # Commit so the synchronous email tag written inside
                # refund_transaction is visible to (a) the polling
                # sessions below and (b) the inbound webhook handler,
                # which would otherwise see the old txn.status and
                # re-fire the email -> race -> tag overwrite. Under
                # READ COMMITTED, only committed writes cross sessions.
                await session.commit()
                _step(
                    "refund: service.refund_transaction",
                    refund_row is not None,
                    f"refund txn id={refund_row.id if refund_row else None}",
                )
            except Exception as exc:
                _step("refund: service.refund_transaction", False, str(exc))

            # Wait for charge.refunded webhook (status flip + email).
            # Stripe's refund webhook can take 20-30s in test mode.
            # Critical: open a NEW session each iteration. The webhook
            # handler commits in its own session, but our long-lived
            # session has an implicit transaction open across all the
            # polled SELECTs - under READ COMMITTED that gives us a
            # snapshot frozen at the first iteration, never seeing the
            # webhook's committed updates. Fresh session per iteration
            # = fresh transaction = correct visibility.
            from typing import Any

            from sqlmodel import select as _select

            refund_email: dict[str, Any] = {}
            txn_id = receipt_txn.id
            for _ in range(45):
                async with get_async_session() as poll_session:
                    fresh = await poll_session.exec(
                        _select(PaymentTransaction).where(
                            PaymentTransaction.id == txn_id
                        )
                    )
                    fresh_txn = fresh.first()
                    refund_email = (
                        (fresh_txn.metadata_ if fresh_txn else None) or {}
                    ).get("email") or {}
                if refund_email.get("kind") == "refund_processed":
                    break
                await _asyncio.sleep(1)
            _step(
                "refund: refund_processed email tagged",
                refund_email.get("kind") == "refund_processed",
                f"kind={refund_email.get('kind')} "
                f"sent_at={refund_email.get('sent_at')} "
                f"skipped={refund_email.get('skipped')}",
            )
        else:
            _step("refund: skipped (no receipt txn found)", False)

        # ---- 4. Cancel ----
        if cleanup:
            try:
                stripe.Subscription.delete(
                    local_sub.provider_subscription_id,
                    invoice_now=False,
                    prorate=False,
                )
                await _asyncio.sleep(2)
                await session.refresh(local_sub)
                _step(
                    "cleanup: stripe cancel + DB flipped",
                    local_sub.status == "canceled",
                    f"local status={local_sub.status}",
                )
                cancel_email = (local_sub.metadata_ or {}).get("email") or {}
                _step(
                    "cleanup: subscription_canceled email tagged",
                    cancel_email.get("kind") == "subscription_canceled",
                    f"kind={cancel_email.get('kind')} "
                    f"sent_at={cancel_email.get('sent_at')}",
                )
            except Exception as exc:
                _step("cleanup: stripe cancel", False, str(exc))

    _summarize(results)
    failures = sum(1 for _, status, _ in results if "FAIL" in status)
    if failures:
        raise typer.Exit(1)


async def _wait_for_sub(
    session: AsyncSession,
    provider_subscription_id: str,
    *,
    expected_status: str,
) -> PaymentSubscription | None:
    """Poll the DB for a ``payment_subscription`` row matching
    ``provider_subscription_id`` with ``status == expected_status``.

    Stripe delivers webhook events 50-500ms after our API call returns,
    so a sync check right after ``stripe.Subscription.create`` will miss
    the row. Polls every 500ms for up to 8s and returns the row when it
    matches, or None when the timeout expires.
    """
    import asyncio as _asyncio

    from sqlmodel import select

    from app.services.payment.models import PaymentSubscription

    for _ in range(16):
        result = await session.exec(
            select(PaymentSubscription).where(
                PaymentSubscription.provider_subscription_id == provider_subscription_id
            )
        )
        row = result.first()
        if row is not None and row.status == expected_status:
            return row
        await _asyncio.sleep(0.5)
    return None


async def _latest_invoice_txn(
    session: AsyncSession, provider_customer_id: str
) -> PaymentTransaction | None:
    """Most recent invoice-keyed ``payment_transaction`` for the customer.

    The receipt email's ``email`` metadata tag and the refund flow both
    live on this row; the e2e checker uses it to assert each event
    after a subscribe.
    """
    from sqlmodel import select

    from app.services.payment.models import PaymentCustomer, PaymentTransaction

    cust_row = await session.exec(
        select(PaymentCustomer).where(
            PaymentCustomer.provider_customer_id == provider_customer_id
        )
    )
    customer = cust_row.first()
    if customer is None:
        return None
    txn_row = await session.exec(
        select(PaymentTransaction)
        .where(
            PaymentTransaction.customer_id == customer.id,
            PaymentTransaction.provider_transaction_id.like("in_%"),  # type: ignore[attr-defined]
        )
        .order_by(PaymentTransaction.created_at.desc())  # type: ignore[attr-defined]
    )
    return txn_row.first()


def _summarize(results: list[tuple[str, str, str]]) -> None:
    """Render the leg-by-leg pass/fail table at the end of the e2e run."""
    console.print()
    table = Table(title="e2e money - summary", show_header=True)
    table.add_column("Status", width=6)
    table.add_column("Leg")
    table.add_column("Detail", style="dim")
    for leg, status, detail in results:
        table.add_row(status, leg, detail)
    console.print(table)
