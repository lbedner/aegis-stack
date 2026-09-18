"""The vocabulary an import plan is written in.

``PlannedRow`` is one record's decided outcome and ``ImportPlan`` the
set of them, plus the account-kind rules and skip reasons both the
classifier and the executor read. Split from ``imports.py`` so the
decision (``classify``) and the write (``ingest``) share these without
either owning them.
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
    # A single-account layout previewed with no target: the client asks
    # which account the statement belongs to, then previews again.
    needs_account: bool = False
    layout: str | None = None
    account_name: str | None = None

    def count(self, status: str) -> int:
        return sum(1 for row in self.rows if row.status == status)
