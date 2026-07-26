"""Shared import primitives used by the OFX/QFX, QIF, and CSV importers.

Parsers produce ``ParsedTransaction`` records; ``import_service`` ingests them
(batch bookkeeping + two-lane dedup). House rule: amounts are integer minor
units and **negative means an outflow**. ``amount`` is sign-normalized while
``raw_amount`` / ``raw_sign_convention`` preserve the source's original form.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import hashlib
import re
import unicodedata

_PUNCTUATION = re.compile(r"[^0-9A-Za-z\s]")
_WHITESPACE = re.compile(r"\s+")


def normalize_payee(raw: str | None) -> str:
    """Uppercase, ASCII-fold, strip punctuation, collapse whitespace.

    ``"  Café   Münchén!! "`` -> ``"CAFE MUNCHEN"``. Folding via NFKD keeps the
    base letters (é -> e) so an accented and un-accented spelling of the same
    merchant collapse to one stable dedup key — the goal is a key, not a pretty
    display name.
    """
    if not raw:
        return ""
    folded = (
        unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    )
    stripped = _PUNCTUATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", stripped).strip().upper()


# A descriptor that still carries a card tail, a store number, a phone
# number or a processor prefix is not a name anybody would choose.
_DESCRIPTOR_NOISE = re.compile(r"[*#]|\d{3,}|\bXXXX|_")


def suggested_payee_name(key: str, sample: str | None) -> str:
    """A DISPLAY name for a payee group: the counterpart to
    ``normalize_payee``, which deliberately destroys exactly what a name
    needs.

    Title-casing the key is lossy in two ways that show up immediately on
    real data: the punctuation is already gone ("McDonald's" -> key
    "MCDONALD S" -> "Mcdonald S") and ``str.capitalize`` flattens interior
    capitals ("ShopRite" -> "Shoprite"). Both were confirmed live, saved
    as the payee on 368 and 183 transactions.

    The sample descriptor still has the original spelling, so it wins when
    it looks like something a person wrote: mixed case (an all-caps blob
    is the bank's, and carries no case worth keeping), short, and free of
    the store/card/phone noise banks append. Otherwise fall back to the
    title-cased key, which is what a shouty descriptor deserves.
    """
    raw = (sample or "").strip()
    if (
        raw
        and len(raw) <= 32
        and raw != raw.upper()  # mixed case -> written by a human
        and not _DESCRIPTOR_NOISE.search(raw)
    ):
        return raw
    return " ".join(word.capitalize() for word in key.split())


def to_cents(amount: Decimal | float | int | str) -> int:
    """Convert a decimal money amount to signed integer minor units (cents)."""
    return int((Decimal(str(amount)) * 100).to_integral_value())


@dataclass
class ParsedSplit:
    """One split leg of a parsed transaction (category / memo / signed cents)."""

    amount: int
    category_hint: str | None = None
    memo: str | None = None


@dataclass
class ParsedTransaction:
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
    splits: list[ParsedSplit] = field(default_factory=list)
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
    groups: dict[tuple, list[ParsedTransaction]] = defaultdict(list)
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


@dataclass
class ImportResult:
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
