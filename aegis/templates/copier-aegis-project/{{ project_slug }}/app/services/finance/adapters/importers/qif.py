"""QIF (Quicken Interchange Format) parser — dedup LANE 2 (content hash).

QIF has no stable transaction id, so rows dedup on a content hash (assigned by
``importers.base.assign_import_hashes``, shared with the CSV importer).
Investment QIF (``!Type:Invst``) is out of scope and rejected. QIF carries no
account info, so the caller must supply the target ``account_id``.

Hand-parsed rather than via a third-party library: QIF is a trivial
line-oriented record stream, and parsing the uploaded bytes directly (no
temp-file round-trip) gives exact control over the field mapping below.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.finance.adapters.importers.base import (
    ParsedSplit,
    ParsedTransaction,
)
from app.services.finance.utils import (
    to_cents,
)

# Non-investment account types we accept.
_SUPPORTED_TYPES = {"Bank", "CCard", "Cash", "Oth A", "Oth L"}


def _parse_qif_date(raw: str) -> date:
    """Parse a QIF date (US ``M/D/Y``; ``'`` marks 2000s; 2-digit years)."""
    stripped = raw.strip()
    # Quicken flags 2000s years with an apostrophe separator (e.g. ``1/5'20``);
    # detect it before normalizing the separator away.
    apostrophe_century = "'" in stripped
    normalized = stripped.replace("'", "/").replace(".", "/").replace("-", "/")
    parts = [p for p in normalized.split("/") if p]
    if len(parts) != 3:
        raise ValueError(f"unparseable QIF date: {raw!r}")
    month, day, year = (int(p) for p in parts)
    if year < 100:
        # ``'``-marked years are unambiguously 2000s; otherwise pivot on 69
        # (the POSIX ``%y`` rule: 00-68 -> 2000s, 69-99 -> 1900s) so a legacy
        # ``12/31/99`` stays in 1999 rather than becoming 2099.
        year += 2000 if apostrophe_century or year <= 68 else 1900
    return date(year, month, day)


def parse_qif(data: bytes, *, source: str = "qif") -> list[ParsedTransaction]:
    """Parse QIF bytes into ``ParsedTransaction`` records (LANE-2, id-less)."""
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()

    qif_type: str | None = None
    for line in lines:
        if line.startswith("!Type:"):
            qif_type = line[len("!Type:") :].strip()
            break
    if qif_type is not None and qif_type not in _SUPPORTED_TYPES:
        raise ValueError(
            f"Unsupported QIF type {qif_type!r}; only bank / credit-card QIF is "
            "supported (investment QIF is out of scope)."
        )

    parsed: list[ParsedTransaction] = []
    current: dict[str, Any] = {}
    splits: list[ParsedSplit] = []
    pending: dict[str, Any] = {}

    def _close_split() -> None:
        if pending:
            splits.append(
                ParsedSplit(
                    amount=pending.get("amount", 0),
                    category_hint=pending.get("category"),
                    memo=pending.get("memo"),
                )
            )
            pending.clear()

    for line in lines:
        if not line or line.startswith("!"):
            continue
        code, value = line[0], line[1:].strip()
        if code == "^":
            _close_split()
            if "date" in current and "amount" in current:
                category = current.get("category")
                is_transfer = bool(
                    category and category.startswith("[") and category.endswith("]")
                )
                parsed.append(
                    ParsedTransaction(
                        date=current["date"],
                        amount=current["amount"],
                        source=source,
                        name=current.get("payee"),
                        original_description=current.get("payee"),
                        memo=current.get("memo"),
                        check_number=current.get("check_number"),
                        category_hint=None if is_transfer else category,
                        transfer_hint=category if is_transfer else None,
                        splits=list(splits),
                        raw_amount=current["amount"],
                        raw_sign_convention="qif_signed",
                    )
                )
            current = {}
            splits = []
        elif code in ("T", "U"):  # amount (U is a Quicken duplicate of T)
            current["amount"] = to_cents(value.replace(",", ""))
        elif code == "D":
            current["date"] = _parse_qif_date(value)
        elif code == "P":
            current["payee"] = value
        elif code == "M":
            current["memo"] = value
        elif code == "N":
            current["check_number"] = value
        elif code == "L":
            current["category"] = value
        elif code == "S":  # split category — starts a new split leg
            _close_split()
            pending["category"] = value
        elif code == "E":  # split memo
            pending["memo"] = value
        elif code == "$":  # split amount
            pending["amount"] = to_cents(value.replace(",", ""))

    # Trailing record without a closing '^'.
    _close_split()
    if "date" in current and "amount" in current:
        category = current.get("category")
        is_transfer = bool(
            category and category.startswith("[") and category.endswith("]")
        )
        parsed.append(
            ParsedTransaction(
                date=current["date"],
                amount=current["amount"],
                source=source,
                name=current.get("payee"),
                original_description=current.get("payee"),
                memo=current.get("memo"),
                check_number=current.get("check_number"),
                category_hint=None if is_transfer else category,
                transfer_hint=category if is_transfer else None,
                splits=list(splits),
                raw_amount=current["amount"],
                raw_sign_convention="qif_signed",
            )
        )
    return parsed
