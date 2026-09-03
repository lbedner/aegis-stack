"""Recurring stream, projection, and insight shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.services.finance.constants import CadenceKey

if TYPE_CHECKING:
    from app.services.finance.models import (
        FinanceInsight,
        FinanceRecurringStream,
    )


class RecurringStreamResponse(BaseModel):
    """A detected recurring stream (subscription, bill, or paycheck)."""

    id: int
    account_id: int | None
    name: str
    direction: str  # inflow | outflow
    frequency: str
    average_amount: int | None  # cents (magnitude)
    last_amount: int | None
    amount_is_variable: bool
    currency: str
    next_expected_date: date | None
    last_date: date | None  # last transaction actually matched to this stream
    occurrence_count: int
    status: str
    confidence: int | None
    is_subscription: bool
    is_muted: bool
    # Paused while this date is ahead: out of the forecast, the Bills
    # total, the verdict and every nag until then - and back by itself
    # the day it passes. ``pause_note`` is the why, for the future
    # reader who forgot.
    paused_until: date | None = None
    pause_note: str | None = None
    # A card/loan payment stream: charged by the cash forecast, excluded
    # from the Bills total (the swipes already counted), tagged in the UI
    # so "it's a transfer" and "it's a payment" stop being a riddle.
    is_payment: bool = False
    is_user_confirmed: bool
    source: str  # "derived" (detector) | "provider" | "user" (hand-entered)
    expected_amount: int | None  # cents; set for declared bills/income
    # Display names, resolved by the list endpoint in one query each; None
    # on single-row responses (create/update), where the UI reloads the list.
    account_name: str | None = None
    category_name: str | None = None
    # The category set ON THE BILL, if any - distinct from category_name,
    # which falls back to the one inferred from its transactions. The edit
    # dialog needs the id to prefill its dropdown, and needs it empty when
    # the shown name is only an inference.
    category_id: int | None = None
    # Also list-endpoint-only (same reasoning as above): a favicon guess
    # (merchant_icon.py) and the "fresh"/"overdue"/"stale" recency read
    # (categorize.insights.stream_staleness) - both need context (today,
    # the lookback floor) the single-row create/update/mute endpoints have
    # no reason to compute for a response the UI immediately discards.
    # Base64 PNG, inlined by the list endpoint - see merchant_icon.py
    # for why the bytes travel rather than a URL.
    icon_b64: str | None = None
    staleness: str = "fresh"

    @classmethod
    def from_row(
        cls,
        row: FinanceRecurringStream,
        *,
        account_name: str | None = None,
        category_name: str | None = None,
        icon_b64: str | None = None,
        staleness: str = "fresh",
        is_payment: bool = False,
    ) -> RecurringStreamResponse:
        return cls(
            id=row.id,
            account_id=row.account_id,
            name=row.name,
            direction=row.direction,
            frequency=row.frequency,
            average_amount=row.average_amount,
            last_amount=row.last_amount,
            amount_is_variable=row.amount_is_variable,
            currency=row.currency,
            next_expected_date=row.next_expected_date,
            last_date=row.last_date,
            occurrence_count=row.occurrence_count,
            status=row.status,
            confidence=row.confidence,
            is_subscription=row.is_subscription,
            is_muted=row.is_muted,
            paused_until=row.paused_until,
            pause_note=(row.metadata_ or {}).get("pause_note"),
            is_payment=is_payment,
            is_user_confirmed=row.is_user_confirmed,
            source=row.source,
            expected_amount=row.expected_amount,
            category_id=row.category_id,
            account_name=account_name,
            category_name=category_name,
            icon_b64=icon_b64,
            staleness=staleness,
        )


class RecurringStreamCreate(BaseModel):
    """A hand-entered bill (outflow) or income (inflow) stream."""

    name: str
    direction: Literal["inflow", "outflow"]
    frequency: CadenceKey
    expected_amount: int  # cents (magnitude)
    next_expected_date: date
    account_id: int | None = None
    is_subscription: bool = False


class RecurringAttach(BaseModel):
    """Reconcile one transaction with the bill it paid."""

    transaction_id: int


class RecurringPause(BaseModel):
    """Pause a stream until a date, with an optional why."""

    until: date
    note: str | None = Field(default=None, max_length=500)


class RecurringStreamUpdate(BaseModel):
    """Edits to a stream's declared facts; omitted fields stay as they are."""

    name: str | None = None
    frequency: CadenceKey | None = None
    expected_amount: int | None = None  # cents (magnitude)
    next_expected_date: date | None = None
    # Stated about the BILL and stops there - its transactions keep the
    # categories they have (see FinanceService.update_recurring).
    category_id: int | None = None
    # Which account it is paid from. A hand-entered bill can be created
    # without one, and then it cannot reach the forecast at all.
    account_id: int | None = None


class RecurringCategorize(BaseModel):
    """Set one category across several bills at once."""

    stream_ids: list[int]
    category_id: int


class RecurringListResponse(BaseModel):
    items: list[RecurringStreamResponse]
    total: int
    monthly_cost: int  # cents — monthly-equivalent of recurring outflows


class DeclareRecurring(BaseModel):
    """Mark the selected transactions as a recurring bill or income.

    Cadence, amount, direction and next date are all measured from the
    transactions themselves, the same way detection measures them, so
    there is nothing here for the caller to get wrong or for the two paths
    to disagree about. ``names`` is the one exception, because a bill's
    NAME cannot be measured: it is keyed by ``RecurringPlanGroup.key`` from
    the preview, and anything left out keeps the name the preview proposed.
    """

    transaction_ids: list[int]
    names: dict[str, str] = Field(default_factory=dict)
    # Category for the bills this creates, keyed the same way as ``names``.
    # Set on the STREAM only - the transactions rolling into it keep
    # whatever categories they already carry.
    categories: dict[str, int] = Field(default_factory=dict)
    # What the bill actually costs, keyed like ``names``. Stating it pins
    # the stream fixed-amount, beating a median taken over whatever the
    # sweep rounded up.
    amounts: dict[str, int] = Field(default_factory=dict)
    # The cadence, keyed like ``names``. Measuring it only works for the
    # six canonical gaps detection knows: a semiannual premium measures as
    # "irregular", which the forecast cannot step, so the bill never
    # appears in it. A label the forecast cannot step is ignored.
    frequencies: dict[str, str] = Field(default_factory=dict)
    # Rows unticked in the preview. They stay out of the bill AND stay out
    # of it afterwards: a confirmed bill owns its membership, so detection
    # will not quietly re-add them on its next pass.
    exclude_transaction_ids: list[int] = Field(default_factory=list)


class RecurringPlanMember(BaseModel):
    """One transaction that would roll up into a planned bill."""

    id: int
    date: str
    name: str
    amount: int


class RecurringPlanEntry(BaseModel):
    """One bill the selection would produce. Everything the confirm step
    needs to show what is about to happen before it happens."""

    key: str
    name: str
    account_id: int
    account_name: str | None = None
    direction: str
    frequency: str
    average_amount: int
    last_amount: int
    first_date: str | None = None
    last_date: str | None = None
    next_expected_date: str | None = None
    amount_is_variable: bool = False
    # ``occurrence_count`` is the roll-up; ``selected_count`` is what the
    # user actually ticked. Showing both is the point of the preview.
    occurrence_count: int
    selected_count: int
    # Median of the rows actually ticked - what the Amount field prefills
    # with, since it is the only figure the user can vouch for.
    selected_amount: int = 0
    # Streams already describing this bill that would fold into it.
    absorbs: list[str] = Field(default_factory=list)
    # True when this becomes a SECOND bill for a payee that already has a
    # confirmed one on this account (Anthropic: a subscription and API
    # usage), rather than being merged into it.
    creates_new_bill: bool = False
    existing_bill_name: str | None = None
    members: list[RecurringPlanMember] = Field(default_factory=list)


class RecurringPlanResponse(BaseModel):
    items: list[RecurringPlanEntry]
    total_transactions: int = 0


class ProjectionPoint(BaseModel):
    """One scheduled occurrence in the projected-balance walk.

    Either a recurring stream or a budget drawdown - the everyday spending
    nobody bills you for. A budget point has no ``stream_id``.
    """

    date: date
    stream_id: int | None = None
    name: str
    direction: str  # inflow | outflow
    amount: int  # signed cents (+income, -bill)
    balance: int  # projected running balance after this occurrence, cents
    account: str | None = None  # account name, when the stream is account-bound
    category: str | None = None  # category name, when the stream carries one
    # When this occurrence was DUE, when that is not where it lands. An
    # overdue bill is applied to today, because the money has not left
    # yet, but the row still says which day it was owed.
    due_date: date | None = None


class ProjectionResponse(BaseModel):
    """Today's cash balance walked forward through scheduled bills/income."""

    as_of: date
    horizon_days: int
    start_balance: int  # cents
    upcoming_total: int  # signed cents — net of everything in the window
    end_balance: int  # cents
    points: list[ProjectionPoint]
    total: int


class InsightResponse(BaseModel):
    """A rule-based "wasting money" insight."""

    id: int
    insight_type: str
    severity: str
    title: str
    body: str | None
    detected_amount: int | None
    related_stream_id: int | None
    related_transaction_id: int | None
    related_category_id: int | None
    status: str
    # Analyst notes record which model wrote them here; rule findings leave it
    # empty. The Notes tab shows it so a re-tuned model is visible in the UI.
    metadata: dict[str, Any] = {}

    @classmethod
    def from_row(cls, row: FinanceInsight) -> InsightResponse:
        return cls(
            id=row.id,
            insight_type=row.insight_type,
            severity=row.severity,
            title=row.title,
            body=row.body,
            detected_amount=row.detected_amount,
            related_stream_id=row.related_stream_id,
            related_transaction_id=row.related_transaction_id,
            related_category_id=row.related_category_id,
            status=row.status,
            metadata=row.metadata_ or {},
        )


class InsightListResponse(BaseModel):
    items: list[InsightResponse]
    total: int


class RecurringRescanResult(BaseModel):
    """A detection sweep: rhythms found, plus stale streams pruned."""

    detected: int
    pruned: int


class RecurringCategorizeResult(BaseModel):
    updated: int
