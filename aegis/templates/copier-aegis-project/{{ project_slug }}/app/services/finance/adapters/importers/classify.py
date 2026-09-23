"""Deciding what an import file would do, without doing any of it.

``plan_transactions`` is a PURE READ: it resolves every row to an
outcome - insert, duplicate, update, skip or error - and writes
nothing. ``preview_file`` returns a plan untouched and ``ingest``
executes one, so what the preview shows is by construction what a
commit would do rather than a parallel implementation that can drift.

Three matching lanes, most authoritative first: a provider id, a
content hash, and finally (account, date, amount) - the last absorbing
an EDIT made in the source app, so a renamed payee or re-categorized
charge updates the existing row instead of landing as a second copy of
the same money.
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
from app.services.finance.adapters.importers.plan import (
    CATEGORY_KEPT_NOTE,
    _SKIP_DELETED_REASON,
    _SKIP_REMOVED_REASON,
    _SKIP_SCHEDULED_REASON,
    IGNORED_REASONS,
    ImportPlan,
    PlannedRow,
    _ACCOUNT_KIND_RULES,
    _is_posted,
    _resolve_account_id,
    infer_account_kind,
)
from app.services.finance.models import (
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
    FinanceTransaction,
    FinanceTransactionTag,
)

async def plan_transactions(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    parsed: list[ParsedTransaction],
    default_account_id: int | None = None,
    auto_create_accounts: bool = False,
) -> ImportPlan:
    """Classify every parsed row without writing anything.

    Mirrors what ``ingest_transactions`` will do — indeed IS what it does,
    since ingest executes this plan: scheduled rows skip, LANE 1/2 hits are
    duplicates, an unambiguous LANE 3 hit is an in-place update (with the
    user-category guard applied), everything else inserts. Accounts and
    categories are resolved by lookup only; ones that would be created are
    reported on the plan, with negative placeholder account ids.
    """
    from app.services.finance.service import FinanceService

    service = FinanceService(db)
    today = current_date()

    # Held out of EVERY pass below, not just the insert. Letting scheduled
    # rows into the hash grouping would shift the within-day ordinals of
    # real transactions, changing their content hashes and breaking
    # idempotency for the whole file - a re-import would then duplicate
    # rows it had already stored.
    postable = [txn for txn in parsed if _is_posted(txn, today)]

    # Resolve each distinct account key once (single default, OFX ACCTID, or
    # a multi-account CSV's per-row account name). Lookup only: a key with
    # no account gets a negative placeholder id when auto-create applies
    # (the commit mints the real row), or None (an errored row) otherwise.
    account_by_key: dict[str | None, int | None] = {}
    new_accounts: dict[str, tuple[str, str]] = {}
    removed_keys: set[str] = set()
    placeholder_id = -1
    for txn in postable:
        key = txn.account_key
        if key in account_by_key:
            continue
        if default_account_id is not None:
            account_by_key[key] = default_account_id
            continue
        if not (auto_create_accounts and key):
            account_by_key[key] = await _resolve_account_id(
                db,
                owner_user_id=owner_user_id,
                account_key=key,
                default_account_id=None,
            )
            continue
        existing_id = await queries.live_account_id_by_name(
            db, name=key, owner_user_id=owner_user_id
        )
        if existing_id is not None:
            account_by_key[key] = existing_id
        else:
            # A soft-deleted account with this name is a standing "no":
            # the user removed it, so its rows are ignored rather than
            # the account resurrected. Re-adding the account (or a
            # rename) opts back in.
            if await queries.removed_account_exists(
                db, name=key, owner_user_id=owner_user_id
            ):
                removed_keys.add(key)
                account_by_key[key] = None
            else:
                new_accounts[key] = infer_account_kind(key)
                account_by_key[key] = placeholder_id
                placeholder_id -= 1
    touched_account_ids = {
        aid for aid in account_by_key.values() if aid is not None and aid > 0
    }

    # LANE-2 (id-less CSV/QIF) rows need a content hash keyed on the ROW's
    # resolved account, so hash per account group — this makes within-day
    # ordinals per-account and supports multi-account files. Placeholder
    # accounts hash too (deterministic ordinals); the commit restamps those
    # groups with the real id it minted. A no-op for LANE-1 rows that
    # already carry an external_id.
    hash_groups: dict[int, list[ParsedTransaction]] = defaultdict(list)
    for txn in postable:
        resolved = account_by_key.get(txn.account_key)
        if resolved is not None:
            hash_groups[resolved].append(txn)
    for resolved_id, group in hash_groups.items():
        assign_import_hashes(group, account_id=resolved_id)

    # Preload both dedup lanes for every touched account in one query, so
    # the per-row check is an in-memory dict lookup, not a SELECT. LANE 1
    # keys on ``(account_id, source, external_id)``; LANE 2 on
    # ``(account_id, import_hash)`` — mirroring FinanceService.find_transaction.
    lane1: dict[tuple[int, str, str], int] = {}
    lane2: dict[tuple[int, str], int] = {}
    # LANE 3 (edit-tolerant): (account, date, signed amount) -> existing ids.
    # The content hash covers payee/memo/check, so editing any of them in
    # the source app makes a re-export look like a NEW transaction and the
    # ledger grows a duplicate. Money and date are what a transaction IS;
    # payee, memo, and category are what it's LABELLED. So a row that misses
    # both exact lanes but lands unambiguously on this key is the same
    # transaction, edited - it updates in place.
    core_existing: dict[tuple[int, object, int], list[int]] = defaultdict(list)
    existing_by_id: dict[int, FinanceTransaction] = {}
    if touched_account_ids:
        dedup_rows = await queries.live_transactions_for_accounts(
            db, touched_account_ids
        )
        for existing in dedup_rows:
            # A reconciliation adjustment (FIN-37) is not a source-app
            # transaction: an import row landing on its (date, amount) must
            # INSERT, never "edit" the adjustment - so it joins no lane.
            if existing.external_id_source == "reconcile":
                continue
            existing_by_id[existing.id] = existing
            if existing.external_id is not None:
                lane1[(existing.account_id, existing.source, existing.external_id)] = (
                    existing.id
                )
            if existing.import_hash is not None:
                lane2[(existing.account_id, existing.import_hash)] = existing.id
            core_existing[
                (existing.account_id, existing.date_, existing.amount)
            ].append(existing.id)

    # A soft-deleted transaction's lane keys, so its exact row can be
    # refused instead of re-inserted: both dedup unique indexes are
    # partial on ``deleted_at IS NULL``, meaning nothing at the DB layer
    # stops a deleted row from coming back on the next re-import of the
    # same file. Deleting is a standing decision, like removing an
    # account - the guard makes it stick.
    deleted_lane1: set[tuple[int, str, str]] = set()
    deleted_lane2: set[tuple[int, str]] = set()
    if touched_account_ids:
        deleted_rows = await queries.deleted_transactions_for_accounts(
            db, touched_account_ids
        )
        for gone in deleted_rows:
            if gone.external_id is not None:
                deleted_lane1.add((gone.account_id, gone.source, gone.external_id))
            if gone.import_hash is not None:
                deleted_lane2.add((gone.account_id, gone.import_hash))

    def _matches_deleted(account_id: int, txn: ParsedTransaction) -> bool:
        if txn.external_id is not None:
            return (account_id, txn.source, txn.external_id) in deleted_lane1
        if txn.import_hash is not None:
            return (account_id, txn.import_hash) in deleted_lane2
        return False

    # Rows planned in THIS file also claim their lane keys, so a later
    # identical row in the same file still reads as a duplicate. Values
    # reference either an existing transaction id or an earlier planned
    # row's number (whose transaction does not exist yet).
    planned_lane1: dict[tuple[int, str, str], int] = {}
    planned_lane2: dict[tuple[int, str], tuple[str, int]] = {}

    def _duplicate_of(
        account_id: int, txn: ParsedTransaction
    ) -> tuple[int | None, int | None]:
        """(existing txn id, planned row number) — at most one is set."""
        if txn.external_id is not None:
            key1 = (account_id, txn.source, txn.external_id)
            if key1 in lane1:
                return lane1[key1], None
            if key1 in planned_lane1:
                return None, planned_lane1[key1]
            return None, None
        if txn.import_hash is not None:
            key2 = (account_id, txn.import_hash)
            if key2 in lane2:
                return lane2[key2], None
            if key2 in planned_lane2:
                kind, ref = planned_lane2[key2]
                return (ref, None) if kind == "txn" else (None, ref)
        return None, None

    # An existing row already claimed as an exact duplicate is NOT an edit
    # candidate, and neither side of a lane-3 match may be ambiguous: the
    # (account, date, amount) group must hold exactly one unmatched row on
    # each side. Anything else is left to insert - guessing which of two
    # same-day, same-amount charges was renamed would silently merge two
    # real transactions, which is worse than the duplicate it avoids.
    claimed_existing: set[int] = set()
    core_incoming: dict[tuple[int, object, int], int] = defaultdict(int)
    for candidate in postable:
        candidate_account = account_by_key.get(candidate.account_key)
        if candidate_account is None:
            continue
        matched, _ = _duplicate_of(candidate_account, candidate)
        if matched is not None:
            claimed_existing.add(matched)
            continue
        if candidate.external_id is None:
            core_incoming[(candidate_account, candidate.date, candidate.amount)] += 1

    def _edit_target(account_id: int, txn: ParsedTransaction) -> int | None:
        """The existing transaction this row is an edit OF, or None.

        Only ever id-LESS rows (CSV/QIF). When a source issues ids, the id
        is the identity: a bank re-issuing FITID F006 as F007 on the same
        day for the same amount means a second real transaction, not a
        renamed one, and merging them would lose money from the ledger.
        """
        if txn.external_id is not None:
            return None
        key = (account_id, txn.date, txn.amount)
        if core_incoming.get(key, 0) != 1:
            return None
        candidates = [
            txn_id
            for txn_id in core_existing.get(key, ())
            if txn_id not in claimed_existing
        ]
        return candidates[0] if len(candidates) == 1 else None

    # Memoize resolve-only category lookups; hints repeat heavily. A hint
    # with no alias is recorded once — the commit creates it.
    category_cache: dict[str | None, int | None] = {}
    new_category_hints: list[str] = []

    async def _resolve_category(hint: str | None) -> int | None:
        if hint not in category_cache:
            category_id = await service.resolve_category_alias(
                hint, owner_user_id=owner_user_id
            )
            if category_id is None and hint:
                new_category_hints.append(hint)
            category_cache[hint] = category_id
        return category_cache[hint]

    async def _plan_edit(
        existing: FinanceTransaction, txn: ParsedTransaction
    ) -> PlannedRow:
        row = PlannedRow(row_number=0, txn=txn, status="updated")
        for field_name, incoming in (
            ("name", txn.name),
            ("original_description", txn.original_description),
            ("memo", txn.memo),
            ("check_number", txn.check_number),
        ):
            current = getattr(existing, field_name)
            # A source that stopped carrying a field must not blank out data
            # held locally; an empty cell is the same absence, not an edit.
            if not incoming or incoming == current:
                continue
            row.field_changes.append((field_name, current, incoming))
        resolved = await _resolve_category(txn.category_hint)
        incoming_exists = resolved is not None or bool(txn.category_hint)
        row.category_current_id = existing.category_id
        row.category_new_id = resolved
        row.category_stamps_rule = incoming_exists
        if incoming_exists and resolved != existing.category_id:
            # The source app is the record of truth for LABELS — except a
            # category the user set BY HAND here. That is the user's own
            # curation; the import must never silently undo it.
            row.category_action = (
                "kept" if existing.category_source == "user" else "set"
            )
        if txn.tags and any(part.strip() for part in txn.tags.split(",")):
            # "Is there tag work to do" is all the plan needs; the commit
            # resolves the ids and replaces links only if they differ.
            row.tags_changed = True
        return row

    plan_rows: list[PlannedRow] = []
    insert_rows_by_number: dict[int, PlannedRow] = {}
    for row_number, txn in enumerate(parsed, start=1):
        # Checked before account resolution: a scheduled row must not create
        # an account either.
        if not _is_posted(txn, today):
            plan_rows.append(
                PlannedRow(
                    row_number=row_number,
                    txn=txn,
                    status="skipped",
                    account_key=txn.account_key,
                    reason=_SKIP_SCHEDULED_REASON,
                )
            )
            continue
        account_id = account_by_key.get(txn.account_key)
        if account_id is None:
            if txn.account_key in removed_keys:
                plan_rows.append(
                    PlannedRow(
                        row_number=row_number,
                        txn=txn,
                        status="skipped",
                        account_key=txn.account_key,
                        reason=_SKIP_REMOVED_REASON,
                    )
                )
                continue
            plan_rows.append(
                PlannedRow(
                    row_number=row_number,
                    txn=txn,
                    status="error",
                    account_key=txn.account_key,
                    reason="account not resolved",
                )
            )
            continue

        if _matches_deleted(account_id, txn):
            plan_rows.append(
                PlannedRow(
                    row_number=row_number,
                    txn=txn,
                    status="skipped",
                    account_key=txn.account_key,
                    account_id=account_id,
                    reason=_SKIP_DELETED_REASON,
                )
            )
            continue

        matched_id, matched_row = _duplicate_of(account_id, txn)
        if matched_id is not None or matched_row is not None:
            plan_rows.append(
                PlannedRow(
                    row_number=row_number,
                    txn=txn,
                    status="duplicate",
                    account_key=txn.account_key,
                    account_id=account_id,
                    matched_transaction_id=matched_id,
                    duplicate_of_row=matched_row,
                )
            )
            continue

        edit_target = _edit_target(account_id, txn)
        if edit_target is not None:
            claimed_existing.add(edit_target)
            row = await _plan_edit(existing_by_id[edit_target], txn)
            row.row_number = row_number
            row.account_key = txn.account_key
            row.account_id = account_id
            row.matched_transaction_id = edit_target
            plan_rows.append(row)
            # The commit restamps the row's content hash, so a later
            # identical row in this same file must dedup against it.
            if txn.import_hash is not None:
                planned_lane2[(account_id, txn.import_hash)] = ("txn", edit_target)
            continue

        await _resolve_category(txn.category_hint)
        for split in txn.splits:
            await _resolve_category(split.category_hint)
        row = PlannedRow(
            row_number=row_number,
            txn=txn,
            status="inserted",
            account_key=txn.account_key,
            account_id=account_id,
        )
        plan_rows.append(row)
        insert_rows_by_number[row_number] = row
        # Register the planned insert in the lanes so a later identical row
        # in the same file is still caught as a duplicate.
        if txn.external_id is not None:
            planned_lane1[(account_id, txn.source, txn.external_id)] = row_number
        if txn.import_hash is not None:
            planned_lane2[(account_id, txn.import_hash)] = ("row", row_number)

    return ImportPlan(
        rows=plan_rows,
        parsed=parsed,
        account_by_key=account_by_key,
        new_accounts=new_accounts,
        removed_accounts=sorted(removed_keys),
        new_category_hints=new_category_hints,
        existing_by_id=existing_by_id,
        rows_total=len(parsed),
    )
