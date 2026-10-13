"""Payment-event email helpers.

One ``send_*`` public function per webhook-driven payment event, each
rendering a Jinja template from ``email_templates/`` and dispatching
through the shared ``comms.service.send_email_simple``.

Design:
- If you keep Stripe's automated receipts enabled in the dashboard
  (Settings -> Emails -> Successful payments ON), the ``invoice_paid``
  template here is a *supplement*. If you disable them, this template
  becomes THE only payment confirmation the customer gets — and the
  template carries every invoice field (receipt #, dates, plan, total,
  currency) to match.
- ``_render_and_send`` wraps **both** template render AND email
  dispatch in one try/except so a template-render bug never crashes
  a webhook handler (a missing ctx variable would otherwise bubble
  up to the webhook layer and trigger an infinite Stripe retry loop).
- Each public ``send_*`` returns a small ``EmailDeliveryResult``
  Pydantic model the caller (webhook handler) writes onto the
  relevant DB row's ``metadata_`` column via ``model_dump()``.
  Lets operators query for failed sends without grepping logs
  (``WHERE metadata->>'error' IS NOT NULL``).
- Reply-To header flows from ``settings.SUPPORT_REPLY_TO_EMAIL``
  automatically via ``send_email_simple`` — recipients reply directly
  to a real (forwarded) inbox.
- Idempotency: callers (webhook handlers in ``payment_service``)
  only invoke these helpers when a row is *freshly* created or
  updated, not on every webhook replay. The helpers themselves are
  unconditional; idempotency lives upstream where it has the DB
  context.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "email_templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


# ----------------------------------------------------------------------
# Result type
# ----------------------------------------------------------------------


class EmailDeliveryResult(BaseModel):
    """Shape returned by every public ``send_*`` helper.

    Callers serialise via ``model_dump(mode='json')`` and merge onto
    the relevant row's ``metadata_`` JSON column so failures are
    persisted + queryable without log grepping. Example query against
    a failed receipt::

        SELECT id, amount, metadata_->>'email' AS email_result
        FROM payment_transaction
        WHERE metadata_ #>> '{email,error}' IS NOT NULL;

    Exactly one of ``sent_at`` / ``error`` / ``skipped`` is populated
    per result — the ``_one_outcome`` validator enforces it so a
    construction bug fails loudly instead of silently corrupting the
    metadata column.
    """

    model_config = ConfigDict(frozen=True)

    kind: str = Field(
        description="Template slug ('subscription_started', 'invoice_paid', "
        "etc.) so an operator scanning metadata can tell at a glance "
        "which email this row's send pertained to.",
    )
    sent_at: datetime | None = Field(
        default=None,
        description="UTC timestamp the dispatch succeeded; None when "
        "the send failed or was skipped.",
    )
    error: str | None = Field(
        default=None,
        description="``<ExceptionClass>:<message>`` when the render or "
        "transport raised. None on success or skip.",
    )
    skipped: str | None = Field(
        default=None,
        description="Short reason for a deliberate skip ('no_recipient' "
        "is the common one). None on success or failure.",
    )

    @model_validator(mode="after")
    def _one_outcome(self) -> EmailDeliveryResult:
        """Catch construction bugs: each result represents exactly one
        outcome (sent / failed / skipped). The factory helpers below
        always satisfy this; the validator just guards against
        someone in the future bypassing them."""
        outcomes = sum(1 for value in (self.sent_at, self.error, self.skipped) if value)
        if outcomes != 1:
            raise ValueError(
                f"EmailDeliveryResult must have exactly one of sent_at / "
                f"error / skipped (got sent_at={self.sent_at!r}, "
                f"error={self.error!r}, skipped={self.skipped!r})"
            )
        return self

    @classmethod
    def success(
        cls, *, kind: str, sent_at: datetime | None = None
    ) -> EmailDeliveryResult:
        """Success result. Defaults ``sent_at`` to now (UTC) so callers
        don't have to import datetime just to construct one."""
        return cls(kind=kind, sent_at=sent_at or datetime.now(UTC))

    @classmethod
    def failure(cls, *, kind: str, error: str) -> EmailDeliveryResult:
        """Failure result. ``error`` is the short
        ``<ExceptionClass>:<message>`` we build in ``_render_and_send``."""
        return cls(kind=kind, error=error)

    @classmethod
    def skip(cls, *, kind: str, reason: str) -> EmailDeliveryResult:
        """Skipped result (deliberate non-send). ``reason`` is a short
        slug like ``"no_recipient"``."""
        return cls(kind=kind, skipped=reason)


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _human_date(value: datetime | None) -> str:
    """Format a ``datetime`` for receipt fields. Empty string for None
    so templates can safely render even when Stripe didn't send a date."""
    if value is None:
        return ""
    return value.strftime("%b %d, %Y")


def _money(amount_cents: int | None, currency: str | None) -> str:
    """Format a Stripe ``amount`` (in cents) as a display string.

    Falls back to a plain ``$X.YY`` when locale formatting fails (the
    bare-bones email environment doesn't always have ICU data, etc.).
    """
    cents = int(amount_cents or 0)
    cur = (currency or "usd").upper()
    whole, frac = divmod(cents, 100)
    return f"${whole}.{frac:02d} {cur}"


def _billing_settings_url() -> str:
    """URL the templates link to as the catch-all 'manage this' CTA."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/settings/billing"


def _shared_ctx() -> dict[str, Any]:
    """Variables every template needs — currently just the brand name.

    Injected here so each ``send_*`` helper stays terse and so that
    rebranding only requires changing ``PROJECT_DISPLAY_NAME`` in
    settings.
    """
    return {"project_name": settings.PROJECT_DISPLAY_NAME}


async def _render_and_send(
    *,
    template: str,
    to: str,
    subject: str,
    kind: str,
    ctx: dict[str, Any],
) -> EmailDeliveryResult:
    """Render template + dispatch + return a structured result.

    Single try/except around BOTH render and dispatch so a
    template-render error (typically a missing ctx variable) is
    treated the same as a Resend outage: log, swallow, return an
    ``EmailDeliveryResult.failure(...)``. Caller writes it onto the
    relevant metadata column.

    Returns early with a ``skip(...)`` result when ``to`` is empty —
    anonymous checkouts have no recipient to email. Caller treats
    this as a non-failure (documented behaviour for that flow).
    """
    if not to:
        logger.info("payment.email: no recipient for %s; skipping", kind)
        return EmailDeliveryResult.skip(kind=kind, reason="no_recipient")
    # Lazy import: comms is an optional dependency. If a project ships
    # payment without comms, this module still imports fine; the helpers
    # just return a clean ``skip`` result instead of crashing the
    # webhook with ``ModuleNotFoundError``.
    try:
        from app.services.comms.service import (
            EmailConfigurationError,
            send_email_simple,
        )
    except ImportError:
        logger.info(
            "payment.email: comms service not installed; skipping %s email",
            kind,
        )
        return EmailDeliveryResult.skip(kind=kind, reason="comms_not_installed")
    try:
        html = _env.get_template(template).render(**_shared_ctx(), **ctx)
        await send_email_simple(to=to, subject=subject, html=html)
    except EmailConfigurationError as exc:
        logger.warning(
            "payment.email: %s email not sent (Resend not configured). "
            "Recipient was %s. (%s)",
            kind,
            to,
            exc,
        )
        return EmailDeliveryResult.failure(
            kind=kind, error=f"EmailConfigurationError:{exc}"
        )
    except Exception as exc:  # noqa: BLE001 — intentional broad catch; same as auth pattern
        # Covers Jinja UndefinedError (missing ctx variable), Resend
        # transport errors, network blips, etc. The webhook handler
        # MUST NOT propagate; we already wrote the DB row, returning
        # 5xx to Stripe would replay-loop on a permanent bug.
        logger.error(
            "payment.email: failed to send %s email to %s: %s",
            kind,
            to,
            exc,
        )
        return EmailDeliveryResult.failure(
            kind=kind, error=f"{type(exc).__name__}:{exc}"
        )
    return EmailDeliveryResult.success(kind=kind)


# ----------------------------------------------------------------------
# Public API — one function per webhook-driven event.
#
# All callers come from ``payment_service`` webhook handlers. Each
# helper accepts the minimum facts that came back from Stripe (plan,
# amount, period, dates) plus the user's email address; the rest
# (URLs, formatting) is derived here so callers stay terse.
#
# Each returns an EmailDeliveryResult the handler tags onto metadata_.
# ----------------------------------------------------------------------


async def send_subscription_started(
    *,
    to: str,
    plan_name: str,
    period_start: datetime | None,
    period_end: datetime | None,
    amount_cents: int | None,
    currency: str | None,
) -> EmailDeliveryResult:
    """Welcome / first-charge confirmation for a new subscription."""
    return await _render_and_send(
        template="subscription_started.html",
        to=to,
        subject=f"You're on {plan_name}",
        kind="subscription_started",
        ctx={
            "plan_name": plan_name,
            "period_start_human": _human_date(period_start),
            "period_end_human": _human_date(period_end),
            "amount_formatted": _money(amount_cents, currency),
            "billing_settings_url": _billing_settings_url(),
            "cta_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/app",
        },
    )


async def send_subscription_updated(
    *,
    to: str,
    plan_name: str,
    period_start: datetime | None,
    period_end: datetime | None,
    amount_cents: int | None,
    currency: str | None,
) -> EmailDeliveryResult:
    """Plan-change confirmation (tier up, tier down, cycle change)."""
    return await _render_and_send(
        template="subscription_updated.html",
        to=to,
        subject=f"You're now on {plan_name}",
        kind="subscription_updated",
        ctx={
            "plan_name": plan_name,
            "period_start_human": _human_date(period_start),
            "period_end_human": _human_date(period_end),
            "amount_formatted": _money(amount_cents, currency),
            "billing_settings_url": _billing_settings_url(),
            "cta_url": _billing_settings_url(),
        },
    )


async def send_subscription_canceled(
    *,
    to: str,
    plan_name: str,
    period_end: datetime | None,
) -> EmailDeliveryResult:
    """Cancellation acknowledgement. The plan stays active until
    ``period_end``; this is the "we got the request" email, not the
    "your access has ended" email (which fires later when the period
    actually closes — handled by a future scheduled job, not here)."""
    return await _render_and_send(
        template="subscription_canceled.html",
        to=to,
        subject=f"Your {plan_name} subscription was canceled",
        kind="subscription_canceled",
        ctx={
            "plan_name": plan_name,
            "period_end_human": _human_date(period_end),
            "billing_settings_url": _billing_settings_url(),
            "cta_url": _billing_settings_url(),
        },
    )


async def send_invoice_paid(
    *,
    to: str,
    plan_name: str,
    invoice_number: str,
    amount_cents: int | None,
    currency: str | None,
    charged_at: datetime | None,
    period_start: datetime | None,
    period_end: datetime | None,
    hosted_invoice_url: str | None,
) -> EmailDeliveryResult:
    """The receipt — see template note. If you've disabled Stripe's
    default receipts, this is the only payment confirmation the
    customer gets."""
    return await _render_and_send(
        template="invoice_paid.html",
        to=to,
        subject=f"Receipt: {_money(amount_cents, currency)} for {plan_name}",
        kind="invoice_paid",
        ctx={
            "plan_name": plan_name,
            "invoice_number": invoice_number or "—",
            "amount_formatted": _money(amount_cents, currency),
            "currency_code": (currency or "usd").upper(),
            "charged_at_human": _human_date(charged_at),
            "period_start_human": _human_date(period_start),
            "period_end_human": _human_date(period_end),
            "billing_settings_url": _billing_settings_url(),
            # Stripe's hosted invoice page is the PDF download surface;
            # fall back to in-app billing if Stripe didn't include one.
            "cta_url": hosted_invoice_url or _billing_settings_url(),
        },
    )


async def send_payment_failed(
    *,
    to: str,
    plan_name: str,
    amount_cents: int | None,
    currency: str | None,
    attempted_at: datetime | None,
    update_payment_url: str | None,
) -> EmailDeliveryResult:
    """Dunning email. Stripe retries automatically; this just gives
    the customer a heads-up + an "update your card" CTA."""
    return await _render_and_send(
        template="payment_failed.html",
        to=to,
        subject="Action required: we couldn't charge your card",
        kind="payment_failed",
        ctx={
            "plan_name": plan_name,
            "amount_formatted": _money(amount_cents, currency),
            "charged_at_human": _human_date(attempted_at),
            "billing_settings_url": _billing_settings_url(),
            "cta_url": update_payment_url or _billing_settings_url(),
        },
    )


async def send_refund_processed(
    *,
    to: str,
    amount_cents: int | None,
    currency: str | None,
    refunded_at: datetime | None,
    original_charge_at: datetime | None,
    invoice_number: str,
) -> EmailDeliveryResult:
    """Refund acknowledgement. Refunds typically post to the customer's
    bank statement within a week — this email is the immediate receipt
    of the refund event."""
    return await _render_and_send(
        template="refund_processed.html",
        to=to,
        subject=f"Refund of {_money(amount_cents, currency)}",
        kind="refund_processed",
        ctx={
            "amount_formatted": _money(amount_cents, currency),
            "refunded_at_human": _human_date(refunded_at),
            "original_charge_date_human": _human_date(original_charge_at),
            "invoice_number": invoice_number or "—",
            "billing_settings_url": _billing_settings_url(),
            "cta_url": _billing_settings_url(),
        },
    )


async def send_trial_ending_soon(
    *,
    to: str,
    plan_name: str,
    trial_end: datetime | None,
    amount_cents: int | None,
    currency: str | None,
) -> EmailDeliveryResult:
    """Reminder fired ~3 days before a trial converts to a paid charge.

    Stripe sends ``customer.subscription.trial_will_end`` exactly once
    per trial, so this helper is invoked once per subscription. The
    template tells the customer the exact date their card will be
    charged and how much, plus a billing link in case they want to
    cancel or switch cards before then.
    """
    return await _render_and_send(
        template="trial_ending_soon.html",
        to=to,
        subject=f"Your {plan_name} trial ends soon",
        kind="trial_ending_soon",
        ctx={
            "plan_name": plan_name,
            "trial_end_human": _human_date(trial_end),
            "amount_formatted": _money(amount_cents, currency),
            "billing_settings_url": _billing_settings_url(),
            "cta_url": _billing_settings_url(),
        },
    )
