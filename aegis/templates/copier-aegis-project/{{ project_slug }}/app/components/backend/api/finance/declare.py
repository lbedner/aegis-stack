"""The "Make recurring" path: preview and declare, plus its payload builder.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.services.finance.adapters.importers import imports
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.schemas import (
    DeclareRecurring,
    ImportPreviewEdit,
    ImportPreviewResponse,
    RecurringPlanEntry,
    RecurringPlanMember,
    RecurringPlanResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


async def _preview_payload(db, plan: imports.ImportPlan) -> ImportPreviewResponse:
    """Shape an ImportPlan for the client: counts, would-create lists, and
    per-edit change strings with category NAMES (ids mean nothing to the
    person deciding whether to press Import)."""
    from sqlmodel import select

    from app.services.finance.models import FinanceAccount, FinanceCategory

    if plan.identical_batch_id is not None:
        return ImportPreviewResponse(
            file_name=plan.file_name,
            rows_total=plan.rows_total,
            identical_batch_id=plan.identical_batch_id,
            rows_duplicate=plan.rows_total,
        )
    if plan.needs_account:
        return ImportPreviewResponse(
            file_name=plan.file_name,
            rows_total=plan.rows_total,
            needs_account=True,
            layout=plan.layout,
        )

    # One pass for the names the display needs: real accounts touched by
    # the plan, and every category id an edit mentions.
    account_ids = {
        row.account_id
        for row in plan.rows
        if row.account_id is not None and row.account_id > 0
    }
    account_names: dict[int, str] = {}
    if account_ids:
        rows = (
            await db.exec(
                select(FinanceAccount.id, FinanceAccount.name).where(
                    FinanceAccount.id.in_(account_ids)
                )
            )
        ).all()
        account_names = dict(rows)
    category_ids = {
        cid
        for row in plan.rows
        if row.status == "updated"
        for cid in (row.category_current_id, row.category_new_id)
        if cid is not None
    }
    category_names: dict[int, str] = {}
    if category_ids:
        rows = (
            await db.exec(
                select(FinanceCategory.id, FinanceCategory.name).where(
                    FinanceCategory.id.in_(category_ids)
                )
            )
        ).all()
        category_names = dict(rows)

    def _account_label(row: imports.PlannedRow) -> str:
        if row.account_id is not None and row.account_id > 0:
            return account_names.get(row.account_id, f"account {row.account_id}")
        return f"{row.account_key or 'unresolved'} (new)"

    inserts_by_account: dict[str, int] = {}
    insert_dates: list[date] = []
    edits: list[ImportPreviewEdit] = []
    kept = 0
    for row in plan.rows:
        if row.status == "inserted":
            label = _account_label(row)
            inserts_by_account[label] = inserts_by_account.get(label, 0) + 1
            if row.txn.date is not None:
                insert_dates.append(row.txn.date)
            continue
        if row.status != "updated":
            continue
        existing = plan.existing_by_id[row.matched_transaction_id]
        changes = [
            f"{field}: {current!r} -> {incoming!r}"
            for field, current, incoming in row.field_changes
        ]
        if row.category_action == "set":
            current_name = category_names.get(row.category_current_id, "Uncategorized")
            new_name = (
                category_names.get(row.category_new_id)
                if row.category_new_id is not None
                else f"{row.txn.category_hint} (new)"
            )
            changes.append(f"category: {current_name!r} -> {new_name!r}")
        elif row.category_action == "kept":
            changes.append(imports.CATEGORY_KEPT_NOTE)
            kept += 1
        if row.tags_changed:
            changes.append("tags updated")
        edits.append(
            ImportPreviewEdit(
                transaction_id=existing.id,
                date=existing.date_,
                amount=existing.amount,
                name=existing.name,
                account=_account_label(row),
                changes=changes or ["no field changed"],
                category_kept=row.category_action == "kept",
            )
        )

    return ImportPreviewResponse(
        file_name=plan.file_name,
        rows_total=plan.rows_total,
        layout=plan.layout,
        account_name=plan.account_name,
        rows_inserted=plan.count("inserted"),
        rows_updated=plan.count("updated"),
        rows_duplicate=plan.count("duplicate"),
        rows_error=plan.count("error"),
        rows_skipped=sum(
            1
            for row in plan.rows
            if row.status == "skipped" and row.reason not in imports.IGNORED_REASONS
        ),
        rows_ignored=sum(
            1
            for row in plan.rows
            if row.status == "skipped" and row.reason in imports.IGNORED_REASONS
        ),
        removed_accounts=plan.removed_accounts,
        insert_date_start=min(insert_dates, default=None),
        insert_date_end=max(insert_dates, default=None),
        inserts_by_account=inserts_by_account,
        new_accounts=sorted(plan.new_accounts),
        new_categories=sorted(set(plan.new_category_hints)),
        edits=edits,
        category_kept_count=kept,
    )


@router.post(
    "/transactions/declare-recurring/preview", response_model=RecurringPlanResponse
)
async def preview_declare_recurring(
    body: DeclareRecurring,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringPlanResponse:
    """What "Make recurring" would do, without doing it.

    Worth a round trip because the write is not confined to the rows the
    user ticked: it sweeps in every sibling of the same payee and folds
    away whatever was already describing the bill. Both of those are
    surprises unless shown first, and the proposed name is only editable
    if there is somewhere to edit it.
    """
    from app.services.finance.domains.detection import plan_recurring

    plan = await plan_recurring(
        service.db,
        body.transaction_ids,
        owner_user_id=owner_user_id,
        exclude_transaction_ids=body.exclude_transaction_ids,
    )
    # (rows, total), and paginated - the default page_size would silently
    # drop account names past the 50th.
    account_rows, _ = await service.list_accounts(
        owner_user_id=owner_user_id, include_hidden=True, page_size=500
    )
    accounts = {a.id: a.name for a in account_rows}
    items = [
        RecurringPlanEntry(
            key=group.key,
            name=group.name,
            account_id=group.account_id,
            account_name=accounts.get(group.account_id),
            direction=group.direction,
            frequency=group.frequency,
            average_amount=group.average_amount,
            last_amount=group.last_amount,
            first_date=str(group.first_date) if group.first_date else None,
            last_date=str(group.last_date) if group.last_date else None,
            next_expected_date=(
                str(group.next_expected_date) if group.next_expected_date else None
            ),
            amount_is_variable=group.variable,
            occurrence_count=group.occurrence_count,
            selected_count=group.selected_count,
            selected_amount=group.selected_amount,
            absorbs=group.absorbs,
            creates_new_bill=group.creates_new_bill,
            existing_bill_name=group.existing_bill_name,
            members=[
                RecurringPlanMember(
                    id=m.id,
                    date=str(m.date_),
                    name=m.merchant_name or m.name or m.original_description or "",
                    amount=m.amount,
                )
                for m in group.members
            ],
        )
        for group in plan
    ]
    return RecurringPlanResponse(
        items=items,
        total_transactions=sum(i.occurrence_count for i in items),
    )


@router.post("/transactions/declare-recurring")
async def declare_recurring_transactions(
    body: DeclareRecurring,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> dict[str, int]:
    """Turn the selected transactions into confirmed bills or income.

    Detection can only ever guess, and it declines in exactly the cases a
    user is most certain about: fewer than three occurrences so far, or a
    cadence that matches no canonical gap. This is the override - and it
    reconciles at the same time, folding whatever else already described
    the same bill into one stream (see ``declare_recurring``).
    """
    from app.services.finance.domains.detection import declare_recurring

    if not body.transaction_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one transaction id.",
        )
    result = await declare_recurring(
        service.db,
        body.transaction_ids,
        owner_user_id=owner_user_id,
        names=body.names,
        exclude_transaction_ids=body.exclude_transaction_ids,
        categories=body.categories,
        amounts=body.amounts,
        frequencies=body.frequencies,
    )
    await service.db.commit()
    return {
        "streams": result.streams,
        "transactions": result.transactions,
        "reconciled": result.reconciled,
    }
