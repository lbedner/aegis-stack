"""Executing a plan: batch bookkeeping and the writes themselves.

``ingest_transactions`` takes what ``classify`` decided and performs
it, creating the ``finance_import_batch``, writing one
``finance_import_batch_row`` per record, and inserting or updating
transactions. Writes but does not commit - the caller owns the
transaction boundary.

An identical re-upload short-circuits on ``file_sha256`` before any of
that happens.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date as date_cls
from datetime import datetime
import hashlib
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.finance.utils import current_date
from app.services.finance.adapters.importers import queries
from app.services.finance.adapters.importers.base import (
    ImportResult,
    ParsedTransaction,
    UnsupportedFileTypeError,  # noqa: F401 — re-export; the API router catches imports.UnsupportedFileTypeError
    _extension,
    _parse_by_extension,
    assign_import_hashes,
)
from app.services.finance.adapters.importers.classify import (
    plan_transactions,
)
from app.services.finance.adapters.importers.plan import (
    CATEGORY_KEPT_NOTE,
    IGNORED_REASONS,
    PlannedRow,
    _is_posted,
)
from app.services.finance.models import (
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
    FinanceTransaction,
    FinanceTransactionTag,
)

async def _prior_batch(
    db: AsyncSession, *, batch_owner: int, file_sha256: str
) -> FinanceImportBatch | None:
    """The batch that already ingested these exact bytes, if any."""
    return await queries.prior_batch(
        db, batch_owner=batch_owner, file_sha256=file_sha256
    )


def _identical_result(prior: FinanceImportBatch) -> ImportResult:
    """An identical-bytes submission changes nothing: the prior batch IS
    the outcome, reported all-duplicate."""
    return ImportResult(
        batch_id=prior.id,
        rows_total=prior.rows_total,
        rows_duplicate=prior.rows_total,
    )


async def ingest_transactions(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    source_type: str,
    file_name: str | None,
    file_bytes: bytes,
    parsed: list[ParsedTransaction],
    default_account_id: int | None = None,
    import_profile_id: int | None = None,
    auto_create_accounts: bool = False,
) -> ImportResult:
    """Ingest parsed transactions under a reversible, deduped import batch.

    Plans first (``plan_transactions``, a pure read), then executes the plan:
    minting the accounts and categories it named, applying updates, inserting
    rows, and writing one batch row per record. ``auto_create_accounts``
    routes each row to an account named by its ``account_key`` (a
    multi-account CSV), creating one when absent. Otherwise rows use
    ``default_account_id`` (single-account) or provider-id matching.
    """
    batch_owner = 0 if owner_user_id is None else owner_user_id
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Identical re-upload short-circuit: return the prior batch, all-duplicate.
    prior = await _prior_batch(db, batch_owner=batch_owner, file_sha256=file_sha256)
    if prior is not None:
        return _identical_result(prior)

    batch = FinanceImportBatch(
        owner_user_id=batch_owner,
        source_type=source_type,
        file_name=file_name,
        file_sha256=file_sha256,
        import_profile_id=import_profile_id,
        status="processing",
        rows_total=len(parsed),
        started_at=utcnow(),
    )
    try:
        async with db.begin_nested():
            db.add(batch)
            await db.flush()
    except IntegrityError:
        # A concurrent submission of the same bytes won the insert between
        # our check and our flush (a double-clicked Import, confirmed
        # live). Land on the winner's batch instead of crashing the job.
        prior = await _prior_batch(db, batch_owner=batch_owner, file_sha256=file_sha256)
        if prior is None:
            raise
        return _identical_result(prior)

    from app.services.finance.service import FinanceService

    service = FinanceService(db)
    plan = await plan_transactions(
        db,
        owner_user_id=owner_user_id,
        parsed=parsed,
        default_account_id=default_account_id,
        auto_create_accounts=auto_create_accounts,
    )

    # Mint the accounts the plan named, then restamp the placeholder
    # groups' hashes with the real ids (ordinals are deterministic, so
    # only the account component of the hash changes).
    real_account_id: dict[int, int] = {}
    if plan.new_accounts:
        placeholder_groups: dict[int, list[ParsedTransaction]] = defaultdict(list)
        for row in plan.rows:
            if row.account_id is not None and row.account_id < 0:
                placeholder_groups[row.account_id].append(row.txn)
        for key, placeholder in plan.account_by_key.items():
            if placeholder is None or placeholder >= 0 or key is None:
                continue
            account_type, classification = plan.new_accounts[key]
            created = await service.create_manual_account(
                owner_user_id=owner_user_id,
                name=key,
                account_type=account_type,
                classification=classification,
            )
            real_account_id[placeholder] = created.id
        for placeholder, group in placeholder_groups.items():
            assign_import_hashes(group, account_id=real_account_id[placeholder])

    def _actual_account(row: PlannedRow) -> int | None:
        if row.account_id is not None and row.account_id < 0:
            return real_account_id[row.account_id]
        return row.account_id

    # Memoize category resolution: an import typically repeats a small set
    # of category strings across many rows.
    category_cache: dict[str | None, int | None] = {}

    async def _category_for(hint: str | None) -> int | None:
        if hint not in category_cache:
            category_id = await service.resolve_category_alias(hint)
            if category_id is None and hint:
                # Unknown category names are the USER'S OWN curation (e.g. a
                # Quicken tree like "Bills & Utilities:Streaming"); dropping
                # them silently discards it. Create category + alias instead.
                category = await service.get_or_create_category_from_hint(hint)
                category_id = category.id if category is not None else None
            category_cache[hint] = category_id
        return category_cache[hint]

    # A payee already named on this ledger lands already named, keyed on
    # the same four-token grouping the user confirmed when they named it.
    # A key they have since taught a second payee stops resolving; see
    # ``_remember_payee_keys``.
    #
    # Resolved for the WHOLE file in one query rather than memoized per
    # descriptor the way categories are: an import repeats a handful of
    # category strings across thousands of rows, but descriptors are
    # nearly all distinct (the card tail and date vary per swipe), so a
    # cache would miss on almost every row and make this an N+1.
    merchant_by_descriptor = await service.resolve_merchant_aliases(
        [r.txn.original_description or r.txn.name for r in plan.rows],
        owner_user_id=owner_user_id,
    )

    # Memoize tag rows the same way (Quicken tags repeat heavily).
    tag_cache: dict[str, int] = {}

    async def _tag_ids_for(raw: str | None) -> list[int]:
        if not raw:
            return []
        ids: list[int] = []
        for part in raw.split(","):
            tag_name = part.strip()
            if not tag_name:
                continue
            if tag_name not in tag_cache:
                tag = await service.get_or_create_tag(
                    tag_name, owner_user_id=owner_user_id
                )
                tag_cache[tag_name] = tag.id
            ids.append(tag_cache[tag_name])
        return ids

    async def _apply_edit(row: PlannedRow) -> str:
        """Apply a planned in-place update to the matched transaction.

        The plan decided WHAT changes (including the user-category guard);
        this only performs it. Date and amount are the match key and never
        change here. Returns a human-readable summary of what changed -
        stored on the batch row so an edit is auditable (and reversible by
        hand) rather than a silent overwrite.
        """
        txn = row.txn
        existing = plan.existing_by_id[row.matched_transaction_id]
        changes: list[str] = []
        for field_name, current, incoming in row.field_changes:
            changes.append(f"{field_name}: {current!r} -> {incoming!r}")
            setattr(existing, field_name, incoming)
        if row.category_action == "set":
            category_id = await _category_for(txn.category_hint)
            if category_id is not None and category_id != existing.category_id:
                changes.append(
                    f"category_id: {existing.category_id!r} -> {category_id!r}"
                )
                existing.category_id = category_id
        elif row.category_action == "kept":
            changes.append(CATEGORY_KEPT_NOTE)
        if row.category_stamps_rule and existing.category_source == "unset":
            existing.category_source = "rule"
        # The content hash is derived from the fields just overwritten, so
        # it must be restamped - otherwise the NEXT import sees an unknown
        # hash and re-enters this same path forever.
        if txn.import_hash is not None:
            existing.import_hash = txn.import_hash
            existing.within_day_ordinal = txn.within_day_ordinal

        if row.tags_changed:
            tag_ids = await _tag_ids_for(txn.tags)
            if tag_ids:
                current_tags = await queries.tag_links_for_transaction(db, existing.id)
                if {t.tag_id for t in current_tags} != set(tag_ids):
                    for link in current_tags:
                        await db.delete(link)
                    for tag_id in tag_ids:
                        db.add(
                            FinanceTransactionTag(
                                transaction_id=existing.id, tag_id=tag_id
                            )
                        )
                    changes.append("tags updated")
        # A preserved user category is a decision worth recording, but not
        # a mutation - only real field changes restamp updated_at.
        if [c for c in changes if c != CATEGORY_KEPT_NOTE]:
            existing.updated_at = utcnow()
            db.add(existing)
        return "; ".join(changes)

    inserted = updated = duplicate = error = skipped = ignored = 0
    created_id_by_row: dict[int, int] = {}
    for row in plan.rows:
        txn = row.txn
        if row.status == "skipped":
            if row.reason in IGNORED_REASONS:
                ignored += 1
            else:
                skipped += 1
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    row_number=row.row_number,
                    parsed_status="skipped",
                    reason=row.reason,
                    content_hash=txn.import_hash,
                    fitid=txn.external_id,
                )
            )
            continue
        if row.status == "error":
            error += 1
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    row_number=row.row_number,
                    parsed_status="error",
                    reason=row.reason,
                    content_hash=txn.import_hash,
                    fitid=txn.external_id,
                )
            )
            continue

        account_id = _actual_account(row)
        if row.status == "duplicate":
            duplicate += 1
            matched = row.matched_transaction_id
            if matched is None and row.duplicate_of_row is not None:
                matched = created_id_by_row.get(row.duplicate_of_row)
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    account_id=account_id,
                    row_number=row.row_number,
                    parsed_status="duplicate",
                    matched_transaction_id=matched,
                    content_hash=txn.import_hash,
                    fitid=txn.external_id,
                )
            )
            continue

        if row.status == "updated":
            summary = await _apply_edit(row)
            updated += 1
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    account_id=account_id,
                    row_number=row.row_number,
                    parsed_status="updated",
                    matched_transaction_id=row.matched_transaction_id,
                    reason=summary or "no field changed",
                    content_hash=txn.import_hash,
                    fitid=txn.external_id,
                )
            )
            continue

        category_id = await _category_for(txn.category_hint)
        created = await service.create_transaction(
            owner_user_id=owner_user_id,
            account_id=account_id,
            amount=txn.amount,
            txn_date=txn.date,
            name=txn.name,
            source=txn.source,
            external_id=txn.external_id,
            external_id_source=txn.external_id_source,
            import_hash=txn.import_hash,
            within_day_ordinal=txn.within_day_ordinal,
            import_batch_id=batch.id,
            raw_amount=txn.raw_amount,
            raw_sign_convention=txn.raw_sign_convention,
            original_description=txn.original_description,
            memo=txn.memo,
            check_number=txn.check_number,
            category_id=category_id,
            category_source="rule" if category_id is not None else "unset",
            merchant_id=merchant_by_descriptor.get(
                txn.original_description or txn.name or ""
            ),
            is_split=bool(txn.splits),
        )
        created_id_by_row[row.row_number] = created.id
        for sort_order, split in enumerate(txn.splits):
            await service.create_split(
                parent_transaction_id=created.id,
                owner_user_id=owner_user_id,
                amount=split.amount,
                category_id=await _category_for(split.category_hint),
                memo=split.memo,
                sort_order=sort_order,
            )
        for tag_id in await _tag_ids_for(txn.tags):
            db.add(FinanceTransactionTag(transaction_id=created.id, tag_id=tag_id))
        inserted += 1
        db.add(
            FinanceImportBatchRow(
                import_batch_id=batch.id,
                owner_user_id=batch_owner,
                account_id=account_id,
                row_number=row.row_number,
                parsed_status="inserted",
                matched_transaction_id=created.id,
                content_hash=txn.import_hash,
                fitid=txn.external_id,
            )
        )

    # If the file carried a running balance (e.g. a Quicken register's Balance
    # column), set the target account's ``current_balance`` from the latest
    # row — so net worth reflects the import without a separate valuation.
    if default_account_id is not None:
        # Posted rows only: a scheduled row's running balance is a
        # PROJECTED figure, and taking it as the account's real balance
        # would book money that has not moved.
        today = current_date()
        balanced = [
            (txn.date, i, txn.running_balance)
            for i, txn in enumerate(parsed)
            if _is_posted(txn, today) and txn.running_balance is not None
        ]
        if balanced:
            balanced.sort(key=lambda item: (item[0], item[1]))
            ending_date, _, ending_balance = balanced[-1]
            account = await queries.account_ref(db, default_account_id)
            if account is not None:
                account.current_balance = ending_balance
                account.balance_as_of = datetime(
                    ending_date.year, ending_date.month, ending_date.day
                )
                db.add(account)

    batch.rows_inserted = inserted
    batch.rows_updated = updated
    # No rows_skipped column on the batch: the skipped rows are recorded
    # individually with parsed_status="skipped" and a reason, so the count
    # stays queryable without a migration.
    batch.rows_duplicate = duplicate
    batch.rows_error = error
    batch.status = "committed"
    batch.finished_at = utcnow()
    db.add(batch)
    await db.flush()

    # Reconcile the freshly imported rows: pair internal transfers (so a
    # card payment doesn't double-count as spend), detect recurring streams,
    # and generate "wasting money" insights.
    # An edit can re-categorize a charge or rename a payee, which changes
    # what the rules see - so reconcile after updates too, not only inserts.
    if inserted or updated:
        from app.services.finance.domains.detection import (
            detect_recurring,
            detect_transfers,
            generate_insights,
            promote_curated_streams,
        )

        await detect_transfers(db, owner_user_id=owner_user_id)
        await detect_recurring(db, owner_user_id=owner_user_id)
        # Before the insight rules: a stream the user's own categorization
        # marks as a bill must pass the missed-payment commitment gate on
        # this very pass, not the next one.
        await promote_curated_streams(db, owner_user_id=owner_user_id)
        await generate_insights(db, owner_user_id=owner_user_id)

    return ImportResult(
        batch_id=batch.id,
        rows_total=len(parsed),
        rows_inserted=inserted,
        rows_updated=updated,
        rows_duplicate=duplicate,
        rows_error=error,
        rows_skipped=skipped,
        rows_ignored=ignored,
    )
