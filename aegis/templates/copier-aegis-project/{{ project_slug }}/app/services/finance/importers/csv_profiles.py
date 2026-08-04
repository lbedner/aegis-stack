"""CSV import driven by ``finance_import_profile`` rows (data, not code).

Chase-CC / Chase-checking / AMEX layouts are auto-detected by header signature;
AMEX's inverted sign is handled by the profile's ``amount_sign_convention``,
not an if-statement. Rows are id-less, so they use LANE 2 — the same content
hash as QIF (assigned by the pipeline), ``source='csv'``.
"""

from __future__ import annotations

from collections.abc import Callable
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import io
from typing import TYPE_CHECKING

from app.services.finance.importers.base import ParsedTransaction, to_cents

if TYPE_CHECKING:
    from app.services.finance.models import FinanceImportProfile


class UnknownCsvLayoutError(ValueError):
    """Raised when no profile matches an uploaded CSV's header row."""

    def __init__(
        self,
        header: list[str],
        available: list[str],
        *,
        batch_id: int | None = None,
    ) -> None:
        self.header = header
        self.available = available
        self.batch_id = batch_id
        super().__init__(
            f"No import profile matches CSV header {header}. "
            f"Available profiles: {available}."
        )


def _read_rows(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def header_preview(data: bytes) -> list[str]:
    """First non-empty row — for a helpful 'unknown layout' error message."""
    for row in _read_rows(data):
        if any(cell.strip() for cell in row):
            return [cell.strip() for cell in row]
    return []


def _row_matches(row: list[str], profile: FinanceImportProfile) -> bool:
    trimmed = [cell.strip() for cell in row]
    signature = [cell.strip() for cell in profile.header_signature]
    if trimmed == signature:
        return True
    # set-equality fallback (same columns, reordered) — length-guarded so a
    # short preamble line can't accidentally match.
    return len(trimmed) == len(signature) and set(trimmed) == set(signature)


def _row_contains(row: list[str], profile: FinanceImportProfile) -> bool:
    """The row carries every signature column, plus extras.

    Vendors ADD columns: Quicken's "All Transactions" report grew a
    ``Scheduled`` column, and an exact-length match rejected the whole
    file. Parsing addresses columns by name, so extras are harmless -
    only detection was brittle. Requiring the FULL signature to be
    present is its own guard: a two-cell preamble row can never contain
    eight header names.
    """
    signature = {cell.strip() for cell in profile.header_signature if cell.strip()}
    if len(signature) < 3:
        return False  # too weak a signature to match loosely
    return signature <= {cell.strip() for cell in row}


def detect_profile(
    data: bytes, profiles: list[FinanceImportProfile]
) -> tuple[FinanceImportProfile | None, int]:
    """Find the header row + matching profile.

    Scans every row (not just the first) so a title/preamble before the real
    header — as Quicken Mac's "report" CSV exports produce — is skipped.
    Exact matches win over "signature present, with extra columns" ones, so
    a newly-added vendor column can't steer a file to a looser profile.
    Returns ``(profile, header_row_index)`` or ``(None, -1)``.
    """
    rows = _read_rows(data)
    for index, row in enumerate(rows):
        for profile in profiles:
            if _row_matches(row, profile):
                return profile, index
    for index, row in enumerate(rows):
        for profile in profiles:
            if _row_contains(row, profile):
                return profile, index
    return None, -1


def _parse_amount_cents(raw: str) -> int:
    """Parse a money cell to signed cents. ``$``/thousands stripped;
    ``(45.00)`` (accounting negative) -> -4500. Always exact via Decimal."""
    cleaned = raw.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return 0
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        cents = to_cents(Decimal(cleaned))
    except InvalidOperation:
        return 0
    return -abs(cents) if negative else cents


def _row_amount(get: Callable[[str], str | None], profile: FinanceImportProfile) -> int:
    convention = profile.amount_sign_convention
    if convention == "split_debit_credit":
        debit = get("debit")
        credit = get("credit")
        debit_cents = _parse_amount_cents(debit) if debit else 0
        credit_cents = _parse_amount_cents(credit) if credit else 0
        return credit_cents - abs(debit_cents)  # debit outflow, credit inflow
    cents = _parse_amount_cents(get("amount") or "")
    if convention == "outflow_positive":  # AMEX: charges positive -> negate
        return -cents
    return cents  # outflow_negative: trust the source sign


def _parse_date(raw: str, date_format: str) -> date:
    return datetime.strptime(raw.strip(), date_format).date()


def parse_csv(
    data: bytes, profile: FinanceImportProfile, *, header_index: int = 0
) -> list[ParsedTransaction]:
    """Parse CSV bytes into ``ParsedTransaction`` records per ``profile``.

    ``header_index`` is where the column header lives (from ``detect_profile``);
    everything before it (title/preamble) and blank rows are skipped.
    """
    rows = _read_rows(data)
    if header_index >= len(rows):
        return []
    header = [cell.strip() for cell in rows[header_index]]
    index_of = {name: i for i, name in enumerate(header)}
    mapping = profile.column_mapping  # csv column -> canonical field

    parsed: list[ParsedTransaction] = []
    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue

        def get(canonical: str, _row: list[str] = row) -> str | None:
            for csv_column, canon in mapping.items():
                if canon == canonical and csv_column in index_of:
                    idx = index_of[csv_column]
                    return _row[idx] if idx < len(_row) else None
            return None

        date_raw = get("date")
        if not date_raw:
            continue
        cents = _row_amount(get, profile)
        check_number = get("check_number")
        # Running balance is a raw signed figure (not an inflow/outflow), so it
        # is parsed directly, never through the amount sign convention.
        balance_raw = get("balance")
        running_balance = (
            _parse_amount_cents(balance_raw)
            if balance_raw and balance_raw.strip()
            else None
        )
        # Multi-account exports (e.g. a Quicken "All Transactions" report) name
        # the owning account per row; it routes the pipeline's account resolver.
        account_raw = get("account")
        account_key = (
            account_raw.strip() if account_raw and account_raw.strip() else None
        )
        # Any non-empty value in a mapped "scheduled" column marks a row the
        # source considers not-yet-posted. Quicken uses several ("Scheduled",
        # "Overdue", "DueToday"), so the VALUE is not interpreted - its
        # presence is the signal, which keeps unknown vocabularies working.
        scheduled_raw = get("scheduled")
        parsed.append(
            ParsedTransaction(
                is_scheduled=bool(scheduled_raw and scheduled_raw.strip()),
                date=_parse_date(date_raw, profile.date_format),
                amount=cents,
                source="csv",
                name=get("name"),
                original_description=get("name"),
                memo=get("memo"),
                check_number=check_number.strip() if check_number else None,
                category_hint=get("category"),
                tags=get("tags"),
                raw_amount=cents,
                raw_sign_convention=profile.amount_sign_convention,
                running_balance=running_balance,
                account_key=account_key,
            )
        )
    return parsed
