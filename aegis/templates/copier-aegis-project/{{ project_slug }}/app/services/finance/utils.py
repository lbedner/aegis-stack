"""Shared helpers for the finance domain modules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import partial
import re
from typing import Any
import unicodedata

from app.services.finance.constants import (
    CADENCE_KEYS,
    step_cadence,
)

DEFAULT_CURRENCY = "usd"


def current_period_month(today: date | None = None) -> int:
    today = today or date.today()
    return today.year * 100 + today.month


def display_cash_balance(accounts: list[Any], totals: dict[int, int]) -> int:
    """Today's spendable cash: the sidebar's own display rule - the
    authoritative ``current_balance`` when a real balance write happened,
    else the register sum. One rule, shared by the projection walk and
    the budget outlook, so "today's balance" can never mean two things."""
    balance = 0
    for account in accounts:
        current = account.current_balance
        authoritative = current is not None and (current != 0 or account.balance_as_of)
        balance += current if authoritative else totals.get(account.id, 0)
    return balance


def monthly_income(streams: list[Any]) -> tuple[int, int]:
    """(monthly-equivalent confirmed income, source count) - the one income
    figure the header, the goal allocation engine, and the verdict all
    share, so a percent-of-income goal and the Income cell can never
    disagree about what "income" means.

    The commitment vocabulary is imported inside the function on purpose:
    this module is a leaf the ledger and planning domains both import, so
    naming detection at module scope closes a cycle through them."""
    from app.services.finance.domains.detection.insights.commitments import (
        MONTHLY_FACTOR,
        is_commitment,
        is_paused,
    )

    rows = [
        (s, MONTHLY_FACTOR.get(s.frequency, 0.0))
        for s in streams
        if s.direction == "inflow"
        and not s.is_muted
        and not is_paused(s)
        and is_commitment(s)
    ]
    rows = [(s, f) for s, f in rows if f > 0]
    total = int(sum((s.expected_amount or s.average_amount or 0) * f for s, f in rows))
    return total, len(rows)


# Derived from the cadence table - see app/services/finance/constants.py.
FREQUENCY_STEPS: dict[str, Callable[[date], date]] = {
    key: partial(step_cadence, key) for key in CADENCE_KEYS
}


def utcnow() -> datetime:
    """Naive-UTC timestamp (matches the models' convention)."""
    return datetime.now(UTC).replace(tzinfo=None)


def transaction_payee_key(
    merchant_name: str | None,
    original_description: str | None,
    name: str | None,
) -> str:
    """First-4-normalized-token payee grouping key for a transaction.

    ``normalize_payee`` only folds case/accents/punctuation - it doesn't know
    a bank-generated descriptor's trailing tokens (a masked card ref,
    city/state, or date) vary per swipe even for the exact same merchant
    ("SHPRTE NTH RD&WNSW GT XXX-XXX-6086 NY 06/28" vs "...GT POUGHKEEPSIE
    NYXX8683 07/22" - same store, different card/day). The merchant name is
    reliably at the START of these descriptors; the noise is reliably
    appended at the END, so a first-N-token prefix groups them without a
    real merchant-recognition step. Verified against this app's real
    imported data: 395 Shoprite transactions were splitting into 201
    distinct "payees" under the full normalized string; a 4-token prefix
    collapses them to 6 (the genuine variants - in-store vs. Apple Pay vs.
    Google Pay). Shared by ``suggest_categories`` and the Budget goal
    parser/summary, so a payee grouping never drifts between the two.
    """
    from app.services.finance.utils import normalize_payee

    normalized = normalize_payee(merchant_name or original_description or name or "")
    return " ".join(normalized.split()[:4])


# -- payee vocabulary ---------------------------------------------------------
# These live here, not in the importer that first needed them: the payee
# key is how the whole service groups a merchant - detection rhythms,
# category inference, budget payee lines - so a domain must not have to
# import an adapter to speak it.

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
