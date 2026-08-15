"""The envelope contract: a virtual sub-account wearing envelope metadata.

An envelope is a running balance living inside real cash - an allowance
the kid draws down, a house-repairs pot. Same account-as-carrier design
as ``goals.py`` (hidden manual account, balance and dated history on
``FinanceValuation``), but balances move BOTH directions and there is no
target, progress, or finish line.

The two ``metadata_`` keys below are the whole schema; this module's
accessors are their only reader/writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ENVELOPE_ACCOUNT_TYPE = "envelope"
ENVELOPE_CADENCES = ("weekly", "monthly")

_MARKER_KEY = "envelope"
_CREDIT_KEY = "envelope_monthly_credit"
_AUTO_KEY = "envelope_auto_credit"
_CADENCE_KEY = "envelope_credit_cadence"
_ENVELOPE_KEYS = (_MARKER_KEY, _CREDIT_KEY, _AUTO_KEY, _CADENCE_KEY)


@dataclass(frozen=True)
class EnvelopeMeta:
    """An account's envelope facts, parsed and validated."""

    monthly_credit: int | None = None  # cents PER PERIOD, >= 0
    auto_credit: bool = False  # the scheduler books the credit each period
    cadence: str = "monthly"  # weekly | monthly - how often the credit lands


def envelope_metadata(metadata: dict[str, Any] | None) -> EnvelopeMeta | None:
    """The account's ``EnvelopeMeta``, or ``None`` when it wears none
    (the marker key is the presence flag)."""
    if not metadata or not metadata.get(_MARKER_KEY):
        return None
    raw_credit = metadata.get(_CREDIT_KEY)
    return _validated(
        monthly_credit=int(raw_credit) if raw_credit is not None else None,
        auto_credit=bool(metadata.get(_AUTO_KEY)),
        cadence=str(metadata.get(_CADENCE_KEY, "monthly")),
    )


def set_envelope_metadata(
    metadata: dict[str, Any] | None,
    *,
    monthly_credit: int | None = None,
    auto_credit: bool = False,
    cadence: str = "monthly",
) -> dict[str, Any]:
    """A new metadata dict with the envelope keys written (neighbours kept)."""
    meta = _validated(
        monthly_credit=monthly_credit, auto_credit=auto_credit, cadence=cadence
    )
    return {
        **(metadata or {}),
        _MARKER_KEY: True,
        _CREDIT_KEY: meta.monthly_credit,
        _AUTO_KEY: meta.auto_credit,
        _CADENCE_KEY: meta.cadence,
    }


def clear_envelope_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (metadata or {}).items() if k not in _ENVELOPE_KEYS}


def _validated(
    *, monthly_credit: int | None, auto_credit: bool, cadence: str = "monthly"
) -> EnvelopeMeta:
    if monthly_credit is not None and monthly_credit < 0:
        raise ValueError(f"Monthly credit cannot be negative, got {monthly_credit}.")
    if cadence not in ENVELOPE_CADENCES:
        raise ValueError(
            f"Unknown credit cadence {cadence!r}. "
            f"Known: {', '.join(ENVELOPE_CADENCES)}."
        )
    return EnvelopeMeta(
        monthly_credit=monthly_credit, auto_credit=auto_credit, cadence=cadence
    )
