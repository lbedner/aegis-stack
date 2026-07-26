"""Finance service constants: provider keys, ciphertext column registry.

Enum-style value sets that back ``String`` + ``CheckConstraint`` columns are
added here as their tables land. Kept as plain string constants (not native
DB enums) so adding a value is a normal migration on both SQLite and Postgres.
"""

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
