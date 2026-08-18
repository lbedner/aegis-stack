"""Import pipeline: batch bookkeeping + two-lane transaction dedup.

Shared by every importer (OFX/QFX, QIF, CSV). Each run creates a
``finance_import_batch`` — short-circuiting an identical re-upload by
``file_sha256`` — writes one ``finance_import_batch_row`` per record, and
inserts new transactions while counting duplicates. Writes but does not commit
(the caller owns the transaction boundary).

``finance_import_batch`` / ``_row`` carry a NOT-NULL ``owner_user_id``; in
standalone (no-auth) mode the owner is ``None``, so it's coerced to the ``0``
sentinel for those two tables (transactions stay nullable).

Matching runs three lanes, most authoritative first: a provider id
(LANE 1), a content hash (LANE 2), and finally (account, date, amount)
(LANE 3), which absorbs an EDIT made in the source app - a renamed payee
or re-categorized charge updates the existing row instead of landing as
a second copy of the same money.

Classification is a PURE READ, split into ``plan_transactions``: it decides
every row's outcome (insert / duplicate / update / skip / error) without
writing anything. ``ingest_transactions`` executes a plan; ``preview_file``
returns one untouched — so what the preview shows is by construction what a
commit would do, not a parallel re-implementation that can drift.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from datetime import date as date_cls
import hashlib
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import queries
from app.services.finance.adapters.importers.base import (
    ImportResult,
    ParsedTransaction,
    assign_import_hashes,
)
from app.services.finance.models import (
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
    FinanceTransaction,
    FinanceTransactionTag,
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _resolve_account_id(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    account_key: str | None,
    default_account_id: int | None,
) -> int | None:
    """Explicit account wins; else match the source account id; else None
    (never guess — an unresolved row is errored, not misfiled)."""
    if default_account_id is not None:
        return default_account_id
    if account_key:
        return await queries.account_id_by_provider_key(
            db, account_key=account_key, owner_user_id=owner_user_id
        )
    return None


# Best-effort (account_type, classification) inferred from an account name.
# Multi-account report exports carry no type metadata, so an auto-created
# account gets a sensible default from its name — the user refines it in the
# account editor. Rules are checked in order; the first keyword hit wins.
_ACCOUNT_KIND_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("savings",), "savings", "asset"),
    (("checking", "chequing"), "checking", "asset"),
    (("mortgage", "conventional", "fha", "heloc"), "loan", "liability"),
    (("readi cash", "line of credit", " loc ", "loc "), "loan", "liability"),
    (("loan",), "loan", "liability"),
    (
        (
            "amex",
            "american express",
            "visa",
            "mastercard",
            "discover",
            "card",
            "credit",
        ),
        "credit_card",
        "liability",
    ),
    (("401", "403b", "ira", "roth", "pension", "retirement"), "investment", "asset"),
    (("brokerage", "fund", "invest", "etf"), "brokerage", "asset"),
    (("hsa", "fsa"), "other_asset", "asset"),
    (("house", "home", "property", "condo", "real estate"), "property", "asset"),
)


def infer_account_kind(name: str) -> tuple[str, str]:
    """(account_type, classification) guessed from an account name.

    Conservative: only high-confidence keywords match; anything else falls back
    to a generic asset for the user to reclassify. Padded with spaces so short
    tokens like ``loc`` don't match inside unrelated words.
    """
    lowered = f" {(name or '').lower()} "
    for keywords, account_type, classification in _ACCOUNT_KIND_RULES:
        if any(keyword in lowered for keyword in keywords):
            return account_type, classification
    return "other_asset", "asset"


def _is_posted(txn: ParsedTransaction, today: date_cls) -> bool:
    """Money that has moved. A row the source flags as scheduled, or one
    dated in the future, has not — two signals because neither alone is
    enough: Quicken's "Overdue" scheduled rows are dated in the PAST, and
    a source with no scheduled column can still carry future rows."""
    return not (txn.is_scheduled or (txn.date is not None and txn.date > today))


_SKIP_SCHEDULED_REASON = (
    "scheduled: not yet posted. It imports normally once the payment actually clears."
)
_SKIP_REMOVED_REASON = "account was removed"
_SKIP_DELETED_REASON = "transaction was deleted"
# Skip reasons that mean "the user decided this stays out" - counted as
# ignored (not merely skipped) by ingest and the preview payload alike.
IGNORED_REASONS = (_SKIP_REMOVED_REASON, _SKIP_DELETED_REASON)

# The batch-row reason recorded when the LANE-3 edit path would have
# re-categorized a transaction the USER categorized. The user's curation
# outranks the source app's label — see plan's category_action.
CATEGORY_KEPT_NOTE = "category kept (user-set)"


class PlannedRow(BaseModel):
    """One parsed row's decided outcome. Computed without writing."""

    row_number: int
    txn: ParsedTransaction
    status: str  # 'inserted' | 'updated' | 'duplicate' | 'skipped' | 'error'
    account_key: str | None = None
    # Negative ids are placeholders for accounts the commit would create
    # (see ImportPlan.new_accounts) — planning cannot mint real rows.
    account_id: int | None = None
    reason: str | None = None
    matched_transaction_id: int | None = None
    # An in-file duplicate of a planned INSERT: the matched transaction id
    # does not exist yet, so the reference is the earlier row's number.
    duplicate_of_row: int | None = None
    # -- 'updated' rows only ------------------------------------------------
    # (field, current, incoming) for the plain label fields.
    field_changes: list[tuple[str, Any, Any]] = Field(default_factory=list)
    # What happens to the category — decided HERE, in one place, so the
    # preview and the commit cannot disagree:
    #   'set'  -> overwrite from the source's category hint
    #   'kept' -> the source disagrees but category_source == 'user';
    #             the user's own categorization is never overwritten
    #   'none' -> no hint, or it resolves to the current category
    category_action: str = "none"
    # The hint resolves (or would create) a category — stamp
    # category_source='rule' on a row that was 'unset', matching the
    # insert path's convention.
    category_stamps_rule: bool = False
    # Resolve-only preview of the category change; None + a hint on the
    # txn means the commit would CREATE the category.
    category_current_id: int | None = None
    category_new_id: int | None = None
    tags_changed: bool = False


class ImportPlan(BaseModel):
    """A read-only classification of parsed rows against the ledger."""

    rows: list[PlannedRow]
    parsed: list[ParsedTransaction]
    account_by_key: dict[str | None, int | None]
    # Account name -> inferred (account_type, classification), for accounts
    # a commit would create (multi-account files only).
    new_accounts: dict[str, tuple[str, str]]
    # Category hints with no alias — a commit creates these (the user's own
    # source-side curation; dropping them silently would discard it).
    new_category_hints: list[str]
    # Existing rows touched by the plan, keyed by id — the commit edits
    # these very objects; the preview reads date/amount/name off them.
    existing_by_id: dict[int, FinanceTransaction]
    file_name: str | None = None
    # Account names the file carries that match a REMOVED account - their
    # rows plan as skipped; deleting an account is a standing decision.
    removed_accounts: list[str] = Field(default_factory=list)
    rows_total: int = 0
    # Set when the exact file bytes were already imported: nothing to do.
    identical_batch_id: int | None = None

    def count(self, status: str) -> int:
        return sum(1 for row in self.rows if row.status == status)


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
    today = _utcnow().date()

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
            category_id = await service.resolve_category_alias(hint)
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
            # A source that simply stopped carrying a field must not blank
            # out data already held locally.
            if incoming is None or incoming == current:
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
        started_at=_utcnow(),
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
            existing.updated_at = _utcnow()
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
        today = _utcnow().date()
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
    batch.finished_at = _utcnow()
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


def _detect_csv(
    file_bytes: bytes, profiles: list[FinanceImportProfile]
) -> tuple[FinanceImportProfile | None, int]:
    from app.services.finance.adapters.importers import csv_profiles

    return csv_profiles.detect_profile(file_bytes, profiles)


async def _csv_profiles(db: AsyncSession) -> list[FinanceImportProfile]:
    return await queries.csv_profiles(db)


async def import_csv(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    file_name: str | None,
    file_bytes: bytes,
    account_id: int | None = None,
) -> ImportResult:
    """Detect the CSV layout from the seeded profiles, parse, and ingest.

    A profile that maps an ``account`` column (e.g. a Quicken "All Transactions"
    report) routes rows to per-name accounts and ignores ``account_id``; every
    other layout imports into the single ``account_id`` (required). On an unknown
    header a ``failed`` batch (zero rows) is recorded and
    ``UnknownCsvLayoutError`` is raised (the API surfaces it as 422).
    """
    from app.services.finance.adapters.importers import csv_profiles

    profiles = await _csv_profiles(db)
    profile, header_index = _detect_csv(file_bytes, profiles)
    if profile is None:
        header = csv_profiles.header_preview(file_bytes)
        batch_owner = 0 if owner_user_id is None else owner_user_id
        failed = FinanceImportBatch(
            owner_user_id=batch_owner,
            source_type="csv",
            file_name=file_name,
            file_sha256=hashlib.sha256(file_bytes).hexdigest(),
            status="failed",
            rows_total=0,
            error=f"Unknown CSV layout; header {header}",
            started_at=_utcnow(),
            finished_at=_utcnow(),
        )
        db.add(failed)
        # Commit the failed batch before raising: get_async_db rolls the session
        # back on any exception, so a bare flush would discard this row and the
        # batch_id handed to the caller would reference nothing. Only the failed
        # batch is pending here, so this commit persists just that row.
        await db.commit()
        raise csv_profiles.UnknownCsvLayoutError(
            header, [p.name for p in profiles], batch_id=failed.id
        )

    parsed = csv_profiles.parse_csv(file_bytes, profile, header_index=header_index)
    multi_account = "account" in profile.column_mapping.values()
    if not multi_account and account_id is None:
        raise ValueError("CSV import requires a target account_id for this layout.")
    return await ingest_transactions(
        db,
        owner_user_id=owner_user_id,
        source_type="csv",
        file_name=file_name,
        file_bytes=file_bytes,
        parsed=parsed,
        default_account_id=None if multi_account else account_id,
        import_profile_id=profile.id,
        auto_create_accounts=multi_account,
    )


class UnsupportedFileTypeError(ValueError):
    """Raised for a file extension no importer handles."""


def _extension(file_name: str | None) -> str:
    name = (file_name or "").lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def _parse_by_extension(
    file_name: str | None, file_bytes: bytes
) -> tuple[str, list[ParsedTransaction]]:
    """(source_type, parsed rows) for OFX/QFX/QIF — the id-carrying formats
    whose parsing needs no DB state. CSV goes through profile detection
    instead. Unknown extensions raise ``UnsupportedFileTypeError``."""
    extension = _extension(file_name)
    if extension in ("ofx", "qfx"):
        from app.services.finance.adapters.importers.ofx import parse_ofx

        return extension, parse_ofx(file_bytes, source=extension)
    if extension == "qif":
        from app.services.finance.adapters.importers.qif import parse_qif

        return "qif", parse_qif(file_bytes, source="qif")
    raise UnsupportedFileTypeError(
        f"Unsupported file type '.{extension}'. Supported: .ofx, .qfx, .qif, .csv."
    )


async def import_file(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    file_name: str | None,
    file_bytes: bytes,
    account_id: int | None = None,
) -> ImportResult:
    """Dispatch by file extension and ingest.

    ``.ofx``/``.qfx`` -> OFX (account resolvable from the file); ``.qif`` needs
    an explicit ``account_id``; ``.csv`` needs one unless the detected profile
    routes rows by an account column. Unknown extensions raise
    ``UnsupportedFileTypeError`` (HTTP 415).
    """
    if _extension(file_name) == "csv":
        # Single-account layouts still require account_id; import_csv enforces
        # it after detecting the profile (a multi-account layout self-routes).
        return await import_csv(
            db,
            owner_user_id=owner_user_id,
            file_name=file_name,
            file_bytes=file_bytes,
            account_id=account_id,
        )
    source_type, parsed = _parse_by_extension(file_name, file_bytes)
    if source_type == "qif" and account_id is None:
        raise ValueError("QIF import requires a target account_id.")
    return await ingest_transactions(
        db,
        owner_user_id=owner_user_id,
        source_type=source_type,
        file_name=file_name,
        file_bytes=file_bytes,
        parsed=parsed,
        default_account_id=account_id,
    )


async def preview_file(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    file_name: str | None,
    file_bytes: bytes,
    account_id: int | None = None,
) -> ImportPlan:
    """What ``import_file`` WOULD do, as a pure read.

    Same dispatch, same account requirements, same classification — via the
    same ``plan_transactions`` the commit executes — but nothing is written:
    no batch (not even the failed-batch record on an unknown CSV layout — the
    ``UnknownCsvLayoutError`` still raises), no accounts, no categories.
    An exact-bytes re-upload returns a plan carrying ``identical_batch_id``
    and no rows: importing it again would change nothing.
    """
    batch_owner = 0 if owner_user_id is None else owner_user_id
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()
    prior = await _prior_batch(db, batch_owner=batch_owner, file_sha256=file_sha256)
    if prior is not None:
        return ImportPlan(
            rows=[],
            parsed=[],
            account_by_key={},
            new_accounts={},
            new_category_hints=[],
            existing_by_id={},
            file_name=file_name,
            rows_total=prior.rows_total,
            identical_batch_id=prior.id,
        )

    if _extension(file_name) == "csv":
        from app.services.finance.adapters.importers import csv_profiles

        profiles = await _csv_profiles(db)
        profile, header_index = _detect_csv(file_bytes, profiles)
        if profile is None:
            raise csv_profiles.UnknownCsvLayoutError(
                csv_profiles.header_preview(file_bytes),
                [p.name for p in profiles],
                batch_id=None,
            )
        parsed = csv_profiles.parse_csv(file_bytes, profile, header_index=header_index)
        multi_account = "account" in profile.column_mapping.values()
        if not multi_account and account_id is None:
            raise ValueError("CSV import requires a target account_id for this layout.")
        plan = await plan_transactions(
            db,
            owner_user_id=owner_user_id,
            parsed=parsed,
            default_account_id=None if multi_account else account_id,
            auto_create_accounts=multi_account,
        )
    else:
        source_type, parsed = _parse_by_extension(file_name, file_bytes)
        if source_type == "qif" and account_id is None:
            raise ValueError("QIF import requires a target account_id.")
        plan = await plan_transactions(
            db,
            owner_user_id=owner_user_id,
            parsed=parsed,
            default_account_id=account_id,
        )
    plan.file_name = file_name
    return plan


async def get_import_batch(
    db: AsyncSession, batch_id: int, *, owner_user_id: int | None = None
) -> FinanceImportBatch | None:
    # finance_import_batch.owner_user_id is NOT NULL; standalone uses 0.
    batch_owner = 0 if owner_user_id is None else owner_user_id
    return await queries.import_batch_by_id(db, batch_id, batch_owner=batch_owner)


async def list_import_batches(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> list[FinanceImportBatch]:
    batch_owner = 0 if owner_user_id is None else owner_user_id
    return await queries.import_batches_page(
        db, batch_owner=batch_owner, page=page, page_size=page_size
    )


async def list_import_batch_rows(
    db: AsyncSession, batch_id: int
) -> list[FinanceImportBatchRow]:
    return await queries.import_batch_rows(db, batch_id)
