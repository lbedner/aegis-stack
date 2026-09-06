"""The import dry run: what ``import_file`` WOULD do, as a pure read.

Split from ``imports`` so the commit pipeline and the preview each fit in
a reader's head. Same dispatch, same classification, nothing written.
"""

from __future__ import annotations

import asyncio
import hashlib

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers.base import ParsedTransaction
from app.services.finance.adapters.importers.imports import (
    ImportPlan,
    _csv_profiles,
    _detect_csv,
    _extension,
    _parse_by_extension,
    _prior_batch,
    plan_transactions,
)
from app.services.finance.models import FinanceAccount


def _asks_for_account(
    parsed: list[ParsedTransaction], *, file_name: str | None, layout: str
) -> ImportPlan:
    """The preview's answer to a single-account file with no target: not
    a 400 the client can only echo, but a plan that says which account is
    missing so the client can ask for it and preview again."""
    return ImportPlan(
        rows=[],
        parsed=parsed,
        account_by_key={},
        new_accounts={},
        new_category_hints=[],
        existing_by_id={},
        file_name=file_name,
        rows_total=len(parsed),
        needs_account=True,
        layout=layout,
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
        parsed = await asyncio.to_thread(
            csv_profiles.parse_csv, file_bytes, profile, header_index=header_index
        )
        multi_account = "account" in profile.column_mapping.values()
        layout = profile.name
        if not multi_account and account_id is None:
            return _asks_for_account(parsed, file_name=file_name, layout=layout)
        plan = await plan_transactions(
            db,
            owner_user_id=owner_user_id,
            parsed=parsed,
            default_account_id=None if multi_account else account_id,
            auto_create_accounts=multi_account,
        )
    else:
        source_type, parsed = await asyncio.to_thread(
            _parse_by_extension, file_name, file_bytes
        )
        layout = source_type.upper()
        if source_type == "qif" and account_id is None:
            return _asks_for_account(parsed, file_name=file_name, layout=layout)
        plan = await plan_transactions(
            db,
            owner_user_id=owner_user_id,
            parsed=parsed,
            default_account_id=account_id,
        )
    plan.layout = layout
    if account_id is not None:
        account = await db.get(FinanceAccount, account_id)
        plan.account_name = account.name if account is not None else None
    plan.file_name = file_name
    return plan
