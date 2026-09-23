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
from app.services.finance.models import (
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
    FinanceTransaction,
    FinanceTransactionTag,
)

from app.services.finance.adapters.importers.plan import (  # noqa: F401
    CATEGORY_KEPT_NOTE,
    IGNORED_REASONS,
    ImportPlan,
    PlannedRow,
    infer_account_kind,
)
from app.services.finance.adapters.importers.classify import (  # noqa: F401
    plan_transactions,
)
from app.services.finance.adapters.importers.ingest import (  # noqa: F401
    ingest_transactions,
)
from app.services.shared.queries import stored_owner


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
        batch_owner = stored_owner(owner_user_id)
        # No file hash on a failed batch: the hash dedups files that were
        # ingested (uq_finance_importbatch_file), and carrying it here made
        # the second try of the same unknown bytes an IntegrityError.
        failed = FinanceImportBatch(
            owner_user_id=batch_owner,
            source_type="csv",
            file_name=file_name,
            file_sha256=None,
            status="failed",
            rows_total=0,
            error=f"Unknown CSV layout; header {header}",
            started_at=utcnow(),
            finished_at=utcnow(),
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

    parsed = await asyncio.to_thread(
        csv_profiles.parse_csv, file_bytes, profile, header_index=header_index
    )
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
    source_type, parsed = await asyncio.to_thread(
        _parse_by_extension, file_name, file_bytes
    )
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


async def get_import_batch(
    db: AsyncSession, batch_id: int, *, owner_user_id: int | None = None
) -> FinanceImportBatch | None:
    # finance_import_batch.owner_user_id is NOT NULL; standalone uses 0.
    batch_owner = stored_owner(owner_user_id)
    return await queries.import_batch_by_id(db, batch_id, batch_owner=batch_owner)


async def list_import_batches(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> list[FinanceImportBatch]:
    batch_owner = stored_owner(owner_user_id)
    return await queries.import_batches_page(
        db, batch_owner=batch_owner, page=page, page_size=page_size
    )


async def list_import_batch_rows(
    db: AsyncSession, batch_id: int
) -> list[FinanceImportBatchRow]:
    return await queries.import_batch_rows(db, batch_id)


# The preview lives in its own module; re-exported so callers keep saying
# ``imports.preview_file`` (the API router and the service facade both do).
from app.services.finance.adapters.importers.preview import (  # noqa: E402
    preview_file as preview_file,
)
