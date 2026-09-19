"""Rules about what the accounts themselves report.

card_overdue, min_payment_gap, high_apr_carry, credit_utilization and
cash_runway. These read the provider's own liability detail rather
than inferring from transactions: a card in trouble is flagged by code
reading what the institution said, never by a model noticing.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import CASH_ACCOUNT_TYPES
from app.services.finance.domains.detection import queries
from app.services.finance.domains.detection.insights.formatting import (
    card_apr_bps,
    format_apr,
    format_usd,
    month_key,
)
from app.services.finance.domains.detection.insights.rules.shared import (
    HIGH_APR_BPS,
    HIGH_APR_MIN_BALANCE,
    MIN_PAYMENT_LOOKAHEAD_DAYS,
    RUNWAY_DAYS,
    UTILIZATION_CRITICAL,
    UTILIZATION_WARNING,
    create_insight_if_new,
)
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.models import (
    FinanceAccount,
    FinanceLiabilityDetail,
)
from app.services.shared.queries import owner_clause


async def _liquid_cash(db: AsyncSession, owner_user_id: int | None) -> int:
    """Spendable cash across the owner's live cash accounts, in cents.

    ``available_balance`` (what the bank will actually let out the door)
    beats ``current_balance`` when present.
    """
    accounts = await queries.account_rows_where(
        db,
        [
            owner_clause(FinanceAccount.owner_user_id, owner_user_id),
            FinanceAccount.deleted_at.is_(None),
            FinanceAccount.classification == "asset",
            FinanceAccount.account_type.in_(CASH_ACCOUNT_TYPES),
            FinanceAccount.is_closed.is_(False),
            FinanceAccount.is_hidden.is_(False),
        ],
    )
    total = 0
    for account in accounts:
        balance = account.available_balance
        if balance is None:
            balance = account.current_balance or 0
        total += balance
    return total


def _carried_balance(detail: FinanceLiabilityDetail) -> int | None:
    """The balance actually accruing interest, when the data can prove one.

    The provider's ``balance_subject_to_apr`` is authoritative. Without it, a
    statement that was not paid in full is the fallback proof. A card paid in
    full every month returns None and is never flagged, whatever its APR.
    """
    subject = sum(
        entry.get("balance_subject_to_apr") or 0 for entry in detail.aprs or []
    )
    if subject > 0:
        return subject
    statement = detail.last_statement_balance or 0
    paid = detail.last_payment_amount
    if statement > 0 and paid is not None and paid < statement:
        return statement - paid
    return None


async def _credit_cards(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    today: date,
) -> int:
    """The predefined credit checks: past due, minimum vs cash, APR, limit.

    All four read the account row and the provider's own liability detail
    (statement, minimum payment, due date, APRs). Silence is the default: an
    account with no detail row and no credit limit has nothing to check, and
    a card that is paid in full never trips the APR rule.
    """
    accounts = await queries.account_rows_where(
        db,
        [
            owner_clause(FinanceAccount.owner_user_id, owner_user_id),
            FinanceAccount.deleted_at.is_(None),
            FinanceAccount.classification == "liability",
            FinanceAccount.is_closed.is_(False),
            FinanceAccount.is_hidden.is_(False),
        ],
    )
    if not accounts:
        return 0
    details = await ledger_queries.liability_details_by_account(
        db, [account.id for account in accounts]
    )
    cash = await _liquid_cash(db, owner_user_id)
    month = month_key(today).replace("-", "")

    created = 0
    for account in accounts:
        # A card near its limit needs only the account row.
        limit = account.credit_limit or 0
        balance = abs(account.current_balance or 0)
        if limit > 0 and balance > 0:
            utilization = balance / limit
            if utilization >= UTILIZATION_WARNING:
                pct = int(round(utilization * 100))
                if await create_insight_if_new(
                    db,
                    owner_user_id=store_owner,
                    insight_type="credit_utilization",
                    dedup_key=f"utilization:{account.id}:{month}",
                    severity=(
                        "critical" if utilization >= UTILIZATION_CRITICAL else "warning"
                    ),
                    title=f"{account.name} is at {pct}% of its limit",
                    body=(
                        f"{format_usd(balance)} of the {format_usd(limit)} limit "
                        f"on {account.name} is in use."
                    ),
                    detected_amount=balance,
                    related_account_id=account.id,
                ):
                    created += 1

        detail = details.get(account.id)
        if detail is None:
            continue

        if detail.is_overdue:
            due = detail.next_payment_due_date
            minimum = detail.minimum_payment_amount
            body = f"The institution reports {account.name} as past due."
            if minimum:
                body += f" The minimum payment is {format_usd(minimum)}."
            if await create_insight_if_new(
                db,
                owner_user_id=store_owner,
                insight_type="card_overdue",
                dedup_key=f"card_overdue:{account.id}:{due.isoformat() if due else month}",
                severity="critical",
                title=f"{account.name} is past due",
                body=body,
                detected_amount=minimum,
                related_account_id=account.id,
            ):
                created += 1

        minimum = detail.minimum_payment_amount or 0
        due = detail.next_payment_due_date
        if (
            minimum > 0
            and due is not None
            and today <= due <= today + timedelta(days=MIN_PAYMENT_LOOKAHEAD_DAYS)
            and minimum > cash
        ):
            if await create_insight_if_new(
                db,
                owner_user_id=store_owner,
                insight_type="min_payment_gap",
                dedup_key=f"min_gap:{account.id}:{due.isoformat()}",
                severity="critical",
                title=f"Minimum payment on {account.name} exceeds your cash",
                body=(
                    f"{format_usd(minimum)} is due {due} on {account.name}, but "
                    f"your cash accounts hold {format_usd(cash)} - short "
                    f"{format_usd(minimum - cash)}."
                ),
                detected_amount=minimum,
                related_account_id=account.id,
            ):
                created += 1

        apr = card_apr_bps(detail)
        carried = _carried_balance(detail)
        if (
            apr is not None
            and apr >= HIGH_APR_BPS
            and carried is not None
            and carried >= HIGH_APR_MIN_BALANCE
        ):
            monthly_interest = carried * apr // 10_000 // 12
            if await create_insight_if_new(
                db,
                owner_user_id=store_owner,
                insight_type="high_apr_carry",
                dedup_key=f"high_apr:{account.id}:{month}",
                severity="warning",
                title=(f"{account.name} is carrying a balance at {format_apr(apr)}"),
                body=(
                    f"About {format_usd(carried)} on {account.name} is accruing "
                    f"interest at {format_apr(apr)} - roughly "
                    f"{format_usd(monthly_interest)} a month."
                ),
                detected_amount=carried,
                related_account_id=account.id,
            ):
                created += 1
    return created


async def _cash_runway(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    today: date,
) -> int:
    """Scheduled bills walk the cash balance below zero inside the window.

    Reuses the same projection the Forecast surface renders, so the alert and
    the chart can never disagree about when the money runs out. An already
    negative balance is account state, not a forecast, and stays silent here.
    """
    from app.services.finance.service import FinanceService

    projection = await FinanceService(db).project_balances(
        owner_user_id=owner_user_id, days=RUNWAY_DAYS, today=today
    )
    if projection.start_balance <= 0:
        # Negative is account state, not a forecast; zero is indistinguishable
        # from "no balance data yet", and a rule that cannot tell "broke" from
        # "unknown" must stay silent.
        return 0
    crossing = next((p for p in projection.points if p.balance < 0), None)
    if crossing is None:
        return 0
    if await create_insight_if_new(
        db,
        owner_user_id=store_owner,
        insight_type="cash_runway",
        # One alert per month: the exact crossing date shifts with every sync
        # and re-keying on it would raise the same alarm daily.
        dedup_key=f"cash_runway:{month_key(today).replace('-', '')}",
        severity="critical",
        title=f"Cash is projected to run out on {crossing.date}",
        body=(
            f"You have {format_usd(projection.start_balance)} in cash today; "
            f"after {crossing.name} ({format_usd(crossing.amount)}) on "
            f"{crossing.date} the projected balance is "
            f"-{format_usd(crossing.balance)}."
        ),
        detected_amount=crossing.balance,
        related_stream_id=crossing.stream_id,
    ):
        return 1
    return 0
