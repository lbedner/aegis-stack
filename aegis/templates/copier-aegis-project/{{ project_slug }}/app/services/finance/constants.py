"""Finance service constants: provider keys, ciphertext column registry.

Enum-style value sets that back ``String`` + ``CheckConstraint`` columns are
added here as their tables land. Kept as plain string constants (not native
DB enums) so adding a value is a normal migration on both SQLite and Postgres.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

SERVICE_NAME = "finance"

# Dashboard/health component identifier (mirrors PAYMENT_COMPONENT_NAME).
FINANCE_COMPONENT_NAME = "finance"

# The analyst agent's daily note rides the insight table but is not a finding:
# it never counts toward the anomaly badge, never appears in the Insights list,
# and is never fed back to the agent as something to explain. Lives here rather
# than in the analyst module so the service layer can exclude it without
# importing (or requiring) the AI service.
ANALYST_NOTE_INSIGHT_TYPE = "analyst_note"


class Provider:
    """Connection providers. ``manual`` always ships; the rest are flag-gated."""

    PLAID = "plaid"
    SNAPTRADE = "snaptrade"
    MANUAL = "manual"


# Encrypted (AES-GCM ciphertext) columns on ``finance_connection``. Registered
# here so key-rotation tooling can find every finance secret. Encryption /
# decryption happens in the service layer with a row-bound AAD context
# ``finance_connection:{id}:{column}``.
ENCRYPTED_COLUMNS: tuple[str, ...] = (
    "access_token_encrypted",
    "api_key_encrypted",
    "api_secret_encrypted",
    "api_passphrase_encrypted",
    "refresh_token_encrypted",
)


# Accounts that bills actually draw from. Investments and property have
# balances too, but "can I cover the month" is a question about cash. Shared
# by the balance projection, the liquidity insight rules, and the analyst
# snapshot so "cash on hand" means the same thing everywhere it appears.
CASH_ACCOUNT_TYPES: frozenset[str] = frozenset(
    {"checking", "savings", "cash", "money_market"}
)


# Names a source app uses for "I did not classify this". A row can be
# uncategorized two ways: no category at all, or one of these buckets
# carried in by an import. Checking only for NULL reports zero
# uncategorized on a Quicken import that has over a thousand of them.
UNCATEGORIZED_CATEGORY_NAMES = frozenset(
    {"uncategorized", "unclassified", "other income", "misc", "miscellaneous"}
)


# --- Cadences -------------------------------------------------------------
#
# THE table. A cadence carries six independent facts, and they used to live
# in six hand-written maps across five modules: detection's canonical gaps,
# the forecast's step functions, the menus' labels, the create/update
# validator, the API schema's Literal, and the monthly-equivalent weights.
#
# They drifted, repeatedly, and every gap was found by a user rather than a
# test: the forecast could step semiannual before detection could name it,
# so a six-month insurance premium measured as "irregular" and disappeared
# from the projection; the menus were then extended but the validator was
# not, so the dropdown 422'd; the schema was missed after that, so the fix
# never reached the endpoint.
#
# Adding a cadence is now one entry here. Everything else derives.
#
# ``irregular`` and ``unknown`` are deliberately NOT in this table: they are
# what a stream stores when no cadence fits (or there is only one
# occurrence). They can be stored - the column's CheckConstraint allows them
# - but they cannot be stepped, offered in a menu, or weighed in a rollup,
# which is exactly the difference this table encodes.



@dataclass(frozen=True)
class Cadence:
    """One recurring interval, and everything that depends on it.

    ``detect_days`` is the canonical gap a measured median is matched
    against; it doubles as the ordering key. ``months`` steps by calendar
    month (so Jan 31 + 1 month is Feb 28, not Mar 3); ``days`` steps by a
    fixed count. Exactly one of the two is set.
    """

    label: str
    detect_days: int
    months: int = 0
    days: int = 0
    monthly_factor: float = 1.0
    # Days past due before a stream counts as missed. Short cadences get a
    # tighter window: a weekly charge four days late is meaningful, a
    # monthly one is not.
    grace_days: int = 5


# Ordered SHORTEST FIRST, and the order is load-bearing: a measured median
# is matched against the first band it falls in, so where two bands touch
# the shorter cadence takes the overlap.
CADENCES: dict[str, Cadence] = {
    "weekly": Cadence("Weekly", 7, days=7, monthly_factor=52 / 12, grace_days=3),
    "biweekly": Cadence(
        "Every 2 weeks", 14, days=14, monthly_factor=26 / 12, grace_days=3
    ),
    "semi_monthly": Cadence("Twice a month", 15, days=15, monthly_factor=2.0),
    "monthly": Cadence("Monthly", 30, months=1, monthly_factor=1.0),
    "bimonthly": Cadence("Every 2 months", 60, months=2, monthly_factor=0.5),
    "quarterly": Cadence("Quarterly", 90, months=3, monthly_factor=1 / 3),
    "semi_annually": Cadence("Every 6 months", 180, months=6, monthly_factor=1 / 6),
    "annually": Cadence("Yearly", 365, months=12, monthly_factor=1 / 12),
}

CADENCE_KEYS: tuple[str, ...] = tuple(CADENCES)

# The same set as a type, for request schemas. Built FROM the table rather
# than retyped: a schema listing six cadences while the service stored
# eight is how a fix at the service layer never reached the endpoint.
# Spelled out because a computed ``Literal`` is invisible to type checkers
# and to the OpenAPI schema. It is NOT a second source of truth:
# ``test_the_api_schema_accepts_exactly_these`` fails the moment this and
# ``CADENCES`` disagree, which is the drift that let the endpoint reject
# cadences the service was happy to store.
CadenceKey = Literal[
    "weekly",
    "biweekly",
    "semi_monthly",
    "monthly",
    "bimonthly",
    "quarterly",
    "semi_annually",
    "annually",
    "once",
]

# Stored when nothing fits. Not cadences: nothing can step them.
IRREGULAR_FREQUENCY = "irregular"
UNKNOWN_FREQUENCY = "unknown"

# A bill with a date but no rhythm - "pay Bob back on the 15th". Not a
# cadence either (there is no next occurrence to step to), but unlike
# irregular/unknown it is USER-STATED and fully forecastable: it projects
# exactly one occurrence and contributes nothing to any monthly rollup.
# An indefinite pause. NOT null - a null ``paused_until`` already means
# "not paused" in every consumer, so indefinite is a date that never
# arrives: comparisons, endpoints and serialization all work unchanged,
# and only display code needs to know (see pause_label).
PAUSE_INDEFINITE = date(9999, 12, 31)

ONE_TIME_FREQUENCY = "once"
ONE_TIME_LABEL = "One time"


def add_months(day: date, months: int) -> date:
    """Calendar-aware month step (Jan 31 + 1 month = Feb 28, not Mar 3)."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def step_cadence(key: str, day: date) -> date:
    """The next occurrence after ``day`` at cadence ``key``."""
    cadence = CADENCES[key]
    if cadence.months:
        return add_months(day, cadence.months)
    return day + timedelta(days=cadence.days)
