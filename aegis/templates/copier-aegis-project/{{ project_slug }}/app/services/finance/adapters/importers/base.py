"""Shared import primitives used by the OFX/QFX, QIF, and CSV importers.

Parsers produce ``ParsedTransaction`` records; ``imports`` ingests them
(batch bookkeeping + two-lane dedup). House rule: amounts are integer minor
units and **negative means an outflow**. ``amount`` is sign-normalized while
``raw_amount`` / ``raw_sign_convention`` preserve the source's original form.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib

from pydantic import BaseModel, Field

from app.services.finance.utils import normalize_payee


class ParsedSplit(BaseModel):
    """One split leg of a parsed transaction (category / memo / signed cents)."""

    amount: int
    category_hint: str | None = None
    memo: str | None = None


class ParsedTransaction(BaseModel):
    """A source-agnostic transaction produced by a parser."""

    date: date
    amount: int  # sign-normalized cents (negative = outflow)
    source: str  # 'ofx' | 'qfx' | 'qif' | 'csv'
    external_id: str | None = None
    external_id_source: str | None = None
    import_hash: str | None = None
    within_day_ordinal: int = 0
    raw_amount: int | None = None
    raw_sign_convention: str | None = None
    name: str | None = None
    original_description: str | None = None
    memo: str | None = None
    check_number: str | None = None
    # Running account balance after this row, when the source carries one
    # (e.g. a Quicken register's ``Balance`` column). The pipeline uses the
    # latest-dated value to set the account's ``current_balance``.
    running_balance: int | None = None
    # Free-text category string (e.g. QIF ``L`` value) for alias lookup.
    category_hint: str | None = None
    # Comma-separated tag names (e.g. a Quicken report's Tags column).
    tags: str | None = None
    # A bracketed QIF ``L[Account]`` transfer marker (stored, not paired here).
    transfer_hint: str | None = None
    # The source marks this as a SCHEDULED instance, not posted money (a
    # Quicken "Scheduled"/"Overdue"/"DueToday" row). Such rows are money
    # the user expects to move, not money that moved, so the pipeline
    # records them and moves on rather than putting them in the ledger.
    is_scheduled: bool = False
    splits: list[ParsedSplit] = Field(default_factory=list)
    # Account routing hint (e.g. OFX ACCTID) — resolved against
    # finance_account.provider_account_id, else the explicit account_id param.
    account_key: str | None = None


def compute_import_hash(
    *,
    account_id: int,
    txn_date: date,
    amount_cents: int,
    payee: str | None,
    memo: str | None,
    check_number: str | None,
    within_day_ordinal: int,
) -> str:
    """LANE-2 content hash for id-less rows (QIF/CSV).

    The recipe is a stability contract — changing it silently breaks
    idempotency for every existing import, so it is pinned by a unit test.
    Fields are the account, ISO date, signed cents, normalized payee + memo,
    check number, and the within-day ordinal, joined by ``|``.
    """
    raw = (
        f"{account_id}|{txn_date.isoformat()}|{amount_cents}|"
        f"{normalize_payee(payee)}|{normalize_payee(memo)}|"
        f"{check_number or ''}|{within_day_ordinal}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assign_import_hashes(parsed: list[ParsedTransaction], *, account_id: int) -> None:
    """Set ``within_day_ordinal`` + ``import_hash`` on every LANE-2 row in place.

    Rows are grouped by ``(date, amount, normalized_payee, normalized_memo)``;
    each group is sorted by a DETERMINISTIC key (never file order) and numbered
    ``0..n`` so genuinely-identical rows stay distinct AND a re-export produces
    the same ordinals. Rows that already carry an ``external_id`` (LANE 1) are
    left untouched.
    """
    groups: dict[tuple[date, int, str, str], list[ParsedTransaction]] = defaultdict(
        list
    )
    for txn in parsed:
        if txn.external_id is not None:
            continue
        key = (
            txn.date,
            txn.amount,
            normalize_payee(txn.name),
            normalize_payee(txn.memo),
        )
        groups[key].append(txn)
    for members in groups.values():
        members.sort(key=lambda t: (t.check_number or "", t.memo or "", t.name or ""))
        for ordinal, txn in enumerate(members):
            txn.within_day_ordinal = ordinal
            txn.import_hash = compute_import_hash(
                account_id=account_id,
                txn_date=txn.date,
                amount_cents=txn.amount,
                payee=txn.name,
                memo=txn.memo,
                check_number=txn.check_number,
                within_day_ordinal=ordinal,
            )


class ImportResult(BaseModel):
    """Outcome of an import run (returned to the caller / API)."""

    batch_id: int | None = None
    rows_total: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_duplicate: int = 0
    rows_error: int = 0
    # Rows the source carried but that are not posted money (scheduled /
    # future-dated). Recorded on the batch, never put in the ledger.
    rows_skipped: int = 0
    # Rows belonging to an account the user REMOVED - deleting an account
    # is a standing decision, and a re-import must not resurrect it.
    rows_ignored: int = 0


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
