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
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import hashlib
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.finance_service import FinanceService
from app.services.finance.importers.base import (
    ImportResult,
    ParsedTransaction,
    assign_import_hashes,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceImportBatch,
    FinanceImportBatchRow,
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
        query = select(FinanceAccount.id).where(
            FinanceAccount.provider_account_id == account_key,
            FinanceAccount.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceAccount.owner_user_id == owner_user_id)
        return (await db.exec(query)).first()
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


async def _resolve_account(
    db: AsyncSession,
    service: FinanceService,
    *,
    owner_user_id: int | None,
    account_key: str | None,
    default_account_id: int | None,
    auto_create: bool,
) -> int | None:
    """Resolve a row's target account.

    Explicit ``default_account_id`` always wins (single-account import). When
    ``auto_create`` is set — a multi-account CSV whose rows name their account —
    the key is an account *name*: match an existing account by name, else create
    a manual one so every row lands. Otherwise fall back to provider-id matching
    (OFX ``ACCTID``), which never guesses or creates.
    """
    if default_account_id is not None:
        return default_account_id
    if not (auto_create and account_key):
        return await _resolve_account_id(
            db,
            owner_user_id=owner_user_id,
            account_key=account_key,
            default_account_id=None,
        )
    query = select(FinanceAccount.id).where(
        FinanceAccount.name == account_key,
        FinanceAccount.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    else:
        query = query.where(FinanceAccount.owner_user_id.is_(None))
    existing = (await db.exec(query)).first()
    if existing is not None:
        return existing
    # New account: infer type/classification from the name (best-effort). The
    # user refines it in the account editor — anything unrecognized defaults to
    # a generic asset.
    account_type, classification = infer_account_kind(account_key)
    created = await service.create_manual_account(
        owner_user_id=owner_user_id,
        name=account_key,
        account_type=account_type,
        classification=classification,
    )
    return created.id


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

    ``auto_create_accounts`` routes each row to an account named by its
    ``account_key`` (a multi-account CSV), creating one when absent. Otherwise
    rows use ``default_account_id`` (single-account) or provider-id matching.
    """
    batch_owner = 0 if owner_user_id is None else owner_user_id
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Identical re-upload short-circuit: return the prior batch, all-duplicate.
    prior = (
        await db.exec(
            select(FinanceImportBatch).where(
                FinanceImportBatch.owner_user_id == batch_owner,
                FinanceImportBatch.file_sha256 == file_sha256,
            )
        )
    ).first()
    if prior is not None:
        return ImportResult(
            batch_id=prior.id,
            rows_total=prior.rows_total,
            rows_duplicate=prior.rows_total,
        )

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
    db.add(batch)
    await db.flush()

    service = FinanceService(db)

    # A row the source flags as scheduled, or one dated in the future, is
    # money that has not moved. Two signals because neither alone is
    # enough: Quicken's "Overdue" scheduled rows are dated in the PAST, and
    # a source with no scheduled column can still carry future rows.
    #
    # These rows are held out of EVERY pass below, not just the insert.
    # Letting them into the hash grouping would shift the within-day
    # ordinals of real transactions, changing their content hashes and
    # breaking idempotency for the whole file - a re-import would then
    # duplicate rows it had already stored.
    today = _utcnow().date()

    def _is_scheduled(txn: ParsedTransaction) -> bool:
        return txn.is_scheduled or (txn.date is not None and txn.date > today)

    postable = [txn for txn in parsed if not _is_scheduled(txn)]

    # Resolve each distinct account key once (single default, OFX ACCTID, or a
    # multi-account CSV's per-row account name) instead of once per row.
    account_by_key: dict[str | None, int | None] = {}
    for txn in postable:
        if txn.account_key not in account_by_key:
            account_by_key[txn.account_key] = await _resolve_account(
                db,
                service,
                owner_user_id=owner_user_id,
                account_key=txn.account_key,
                default_account_id=default_account_id,
                auto_create=auto_create_accounts,
            )
    touched_account_ids = {aid for aid in account_by_key.values() if aid is not None}

    # LANE-2 (id-less CSV/QIF) rows need a content hash keyed on the ROW's
    # resolved account, so hash per account group — this makes within-day
    # ordinals per-account and supports multi-account files. A no-op for LANE-1
    # rows that already carry an external_id.
    hash_groups: dict[int, list[ParsedTransaction]] = defaultdict(list)
    for txn in postable:
        resolved = account_by_key.get(txn.account_key)
        if resolved is not None:
            hash_groups[resolved].append(txn)
    for resolved_id, group in hash_groups.items():
        assign_import_hashes(group, account_id=resolved_id)

    # Preload both dedup lanes for every touched account in one query, so the
    # per-row check is an in-memory dict lookup, not a SELECT. LANE 1 keys on
    # ``(account_id, source, external_id)``; LANE 2 on ``(account_id,
    # import_hash)`` — mirroring ``FinanceService.find_transaction``.
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
    if touched_account_ids:
        dedup_rows = (
            await db.exec(
                select(
                    FinanceTransaction.account_id,
                    FinanceTransaction.source,
                    FinanceTransaction.external_id,
                    FinanceTransaction.import_hash,
                    FinanceTransaction.id,
                    FinanceTransaction.date_,
                    FinanceTransaction.amount,
                ).where(
                    FinanceTransaction.account_id.in_(touched_account_ids),
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
        for acc_id, src, ext_id, imp_hash, txn_id, txn_date, amount in dedup_rows:
            if ext_id is not None:
                lane1[(acc_id, src, ext_id)] = txn_id
            if imp_hash is not None:
                lane2[(acc_id, imp_hash)] = txn_id
            core_existing[(acc_id, txn_date, amount)].append(txn_id)

    def _duplicate_id(account_id: int, txn: ParsedTransaction) -> int | None:
        """In-memory two-lane dedup match (mirrors find_transaction)."""
        if txn.external_id is not None:
            return lane1.get((account_id, txn.source, txn.external_id))
        if txn.import_hash is not None:
            return lane2.get((account_id, txn.import_hash))
        return None

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
        matched = _duplicate_id(candidate_account, candidate)
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

    # Memoize category resolution: an import typically repeats a small set of
    # category strings across many rows.
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

    async def _apply_edit(existing_id: int, txn: ParsedTransaction) -> str:
        """Overwrite an existing row's LABELS from the incoming record.

        The source app is treated as the record of truth, so incoming
        values win. Date and amount are the match key and never change
        here. Returns a human-readable summary of what changed - stored
        on the batch row so an edit is auditable (and reversible by hand)
        rather than a silent overwrite.
        """
        existing = await db.get(FinanceTransaction, existing_id)
        if existing is None:
            return ""
        changes: list[str] = []
        category_id = await _category_for(txn.category_hint)
        fields: list[tuple[str, Any]] = [
            ("name", txn.name),
            ("original_description", txn.original_description),
            ("memo", txn.memo),
            ("check_number", txn.check_number),
            ("category_id", category_id),
        ]
        for field, incoming in fields:
            current = getattr(existing, field)
            # A source that simply stopped carrying a field must not blank
            # out data already held locally.
            if incoming is None or incoming == current:
                continue
            changes.append(f"{field}: {current!r} -> {incoming!r}")
            setattr(existing, field, incoming)
        if category_id is not None and existing.category_source == "unset":
            existing.category_source = "rule"
        # The content hash is derived from the fields just overwritten, so
        # it must be restamped - otherwise the NEXT import sees an unknown
        # hash and re-enters this same path forever.
        if txn.import_hash is not None:
            existing.import_hash = txn.import_hash
            existing.within_day_ordinal = txn.within_day_ordinal
            lane2[(existing.account_id, txn.import_hash)] = existing_id

        tag_ids = await _tag_ids_for(txn.tags)
        if tag_ids:
            current_tags = (
                await db.exec(
                    select(FinanceTransactionTag).where(
                        FinanceTransactionTag.transaction_id == existing_id
                    )
                )
            ).all()
            if {t.tag_id for t in current_tags} != set(tag_ids):
                for link in current_tags:
                    await db.delete(link)
                for tag_id in tag_ids:
                    db.add(
                        FinanceTransactionTag(transaction_id=existing_id, tag_id=tag_id)
                    )
                changes.append("tags updated")
        if changes:
            existing.updated_at = _utcnow()
            db.add(existing)
        return "; ".join(changes)

    inserted = updated = duplicate = error = skipped = 0
    for row_number, txn in enumerate(parsed, start=1):
        # Checked before account resolution: a scheduled row must not create
        # an account either.
        if _is_scheduled(txn):
            skipped += 1
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    row_number=row_number,
                    parsed_status="skipped",
                    reason=(
                        "scheduled: not yet posted. It imports normally once "
                        "the payment actually clears."
                    ),
                    content_hash=txn.import_hash,
                    fitid=txn.external_id,
                )
            )
            continue
        account_id = account_by_key.get(txn.account_key)
        if account_id is None:
            error += 1
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    row_number=row_number,
                    parsed_status="error",
                    reason="account not resolved",
                    content_hash=txn.import_hash,
                    fitid=txn.external_id,
                )
            )
            continue

        existing_id = _duplicate_id(account_id, txn)
        if existing_id is not None:
            duplicate += 1
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    account_id=account_id,
                    row_number=row_number,
                    parsed_status="duplicate",
                    matched_transaction_id=existing_id,
                    content_hash=txn.import_hash,
                    fitid=txn.external_id,
                )
            )
            continue

        edit_target = _edit_target(account_id, txn)
        if edit_target is not None:
            summary = await _apply_edit(edit_target, txn)
            claimed_existing.add(edit_target)
            updated += 1
            db.add(
                FinanceImportBatchRow(
                    import_batch_id=batch.id,
                    owner_user_id=batch_owner,
                    account_id=account_id,
                    row_number=row_number,
                    parsed_status="updated",
                    matched_transaction_id=edit_target,
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
        # Register the new row in the dedup maps so a later identical row in
        # the same file is still caught as a duplicate.
        if txn.external_id is not None:
            lane1[(account_id, txn.source, txn.external_id)] = created.id
        if txn.import_hash is not None:
            lane2[(account_id, txn.import_hash)] = created.id
        inserted += 1
        db.add(
            FinanceImportBatchRow(
                import_batch_id=batch.id,
                owner_user_id=batch_owner,
                account_id=account_id,
                row_number=row_number,
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
        # ``postable`` only: a scheduled row's running balance is a
        # PROJECTED figure, and taking it as the account's real balance
        # would book money that has not moved.
        balanced = [
            (txn.date, i, txn.running_balance)
            for i, txn in enumerate(postable)
            if txn.running_balance is not None
        ]
        if balanced:
            balanced.sort(key=lambda item: (item[0], item[1]))
            ending_date, _, ending_balance = balanced[-1]
            account = await db.get(FinanceAccount, default_account_id)
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
        from app.services.finance.categorize import (
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
    )


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
    from app.services.finance.importers import csv_profiles
    from app.services.finance.models import FinanceImportProfile

    profiles = list(
        (
            await db.exec(
                select(FinanceImportProfile).where(
                    FinanceImportProfile.source_format == "csv",
                    FinanceImportProfile.deleted_at.is_(None),
                )
            )
        ).all()
    )
    profile, header_index = csv_profiles.detect_profile(file_bytes, profiles)
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
    extension = _extension(file_name)
    if extension in ("ofx", "qfx"):
        from app.services.finance.importers.ofx import parse_ofx

        return await ingest_transactions(
            db,
            owner_user_id=owner_user_id,
            source_type=extension,
            file_name=file_name,
            file_bytes=file_bytes,
            parsed=parse_ofx(file_bytes, source=extension),
            default_account_id=account_id,
        )
    if extension == "qif":
        if account_id is None:
            raise ValueError("QIF import requires a target account_id.")
        from app.services.finance.importers.qif import parse_qif

        return await ingest_transactions(
            db,
            owner_user_id=owner_user_id,
            source_type="qif",
            file_name=file_name,
            file_bytes=file_bytes,
            parsed=parse_qif(file_bytes, source="qif"),
            default_account_id=account_id,
        )
    if extension == "csv":
        # Single-account layouts still require account_id; import_csv enforces
        # it after detecting the profile (a multi-account layout self-routes).
        return await import_csv(
            db,
            owner_user_id=owner_user_id,
            file_name=file_name,
            file_bytes=file_bytes,
            account_id=account_id,
        )
    raise UnsupportedFileTypeError(
        f"Unsupported file type '.{extension}'. Supported: .ofx, .qfx, .qif, .csv."
    )
