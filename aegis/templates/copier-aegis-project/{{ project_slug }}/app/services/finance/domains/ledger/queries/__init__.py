"""Batched read queries for the ledger domain.

Set-shaped inputs, map-shaped outputs, so callers cannot reintroduce a
per-row query loop. Statement builders only - no business logic, no
writes.

One module per section of the ledger, matching the sibling that consumes
it: 54 of these reads have exactly one caller and it is always the
matching module. ``filters`` holds the predicate fragments more than one
section builds its WHERE out of.

The package boundary is the API. Callers say ``queries.foo(db, ...)``
whichever module ``foo`` lives in, so moving a read between sections is
never a call-site change.
"""

from app.services.finance.domains.ledger.queries import (
    accounts,
    categories,
    filters,
    merchants,
    networth,
    transactions,
    transfers,
)
from app.services.finance.domains.ledger.queries.accounts import (
    account_by_id,
    accounts_page,
    currency_by_code,
    has_nonreconcile_register,
    institution_by_provider_ref,
    latest_valuation_value,
    liability_details_by_account,
    reconcile_adjustment_on,
    register_balance_through,
    transaction_totals_by_account,
    valuation_by_key,
    valuations_for_account,
)
from app.services.finance.domains.ledger.queries.categories import (
    alias_by_normalized_global,
    all_categories,
    categorized_history,
    category_alias_ids,
    category_by_id,
    category_by_slug_global,
    category_names_by_id,
    category_spend_totals,
    category_usage_rows,
    spending_rows,
)
from app.services.finance.domains.ledger.queries.filters import (
    live_account_ids,
    transaction_search_filter,
    uncategorized_catchall_ids,
)
from app.services.finance.domains.ledger.queries.merchants import (
    icons_by_domains,
    live_merchants_by_ids,
    live_streams_by_merchants,
    live_transactions_by_merchants,
    live_transactions_for_merchant,
    merchant_by_id,
    merchant_by_normalized,
    merchant_usage_rows,
    merchants_by_ids,
    merchants_for_owner,
    payeeless_transactions,
)
from app.services.finance.domains.ledger.queries.networth import (
    account_rollup,
    balance_class_series,
    balance_snapshots_between,
    connection_rollup,
    daily_register_deltas,
    holding_quantities,
    live_accounts_for_owner,
    net_worth_series_since,
    net_worth_snapshots_between,
    priced_trade_rows,
    valuations_for_accounts,
)
from app.services.finance.domains.ledger.queries.transactions import (
    dated_amounts_in_window,
    outflow_by_account_in_window,
    dedup_match,
    live_transactions_by_ids,
    outflow_by_account_in_window,
    splits_for_parents,
    tag_by_normalized_name,
    tag_links,
    tagged_transaction_ids,
    tags_by_transaction,
    tags_with_counts,
    top_payees_over_window,
    transaction_by_id,
    transactions_by_ids,
    transactions_page,
    uncategorized_page,
)
from app.services.finance.domains.ledger.queries.transfers import (
    transfer_by_id,
    transfers_for_owner,
)

__all__ = [
    "account_by_id",
    "account_rollup",
    "accounts",
    "accounts_page",
    "alias_by_normalized_global",
    "all_categories",
    "balance_class_series",
    "balance_snapshots_between",
    "categories",
    "categorized_history",
    "category_alias_ids",
    "category_by_id",
    "category_by_slug_global",
    "category_names_by_id",
    "category_spend_totals",
    "category_usage_rows",
    "connection_rollup",
    "currency_by_code",
    "daily_register_deltas",
    "dated_amounts_in_window",
    "outflow_by_account_in_window",
    "dedup_match",
    "filters",
    "has_nonreconcile_register",
    "holding_quantities",
    "icons_by_domains",
    "institution_by_provider_ref",
    "latest_valuation_value",
    "liability_details_by_account",
    "live_account_ids",
    "live_accounts_for_owner",
    "live_merchants_by_ids",
    "live_streams_by_merchants",
    "live_transactions_by_ids",
    "live_transactions_by_merchants",
    "live_transactions_for_merchant",
    "merchant_by_id",
    "merchant_by_normalized",
    "merchant_usage_rows",
    "merchants",
    "merchants_by_ids",
    "merchants_for_owner",
    "net_worth_series_since",
    "net_worth_snapshots_between",
    "networth",
    "payeeless_transactions",
    "priced_trade_rows",
    "reconcile_adjustment_on",
    "register_balance_through",
    "spending_rows",
    "splits_for_parents",
    "tag_by_normalized_name",
    "tag_links",
    "tagged_transaction_ids",
    "tags_by_transaction",
    "tags_with_counts",
    "top_payees_over_window",
    "transaction_by_id",
    "transaction_search_filter",
    "transaction_totals_by_account",
    "transactions",
    "transactions_by_ids",
    "transactions_page",
    "transfer_by_id",
    "transfers",
    "transfers_for_owner",
    "uncategorized_catchall_ids",
    "uncategorized_page",
    "valuation_by_key",
    "valuations_for_account",
    "valuations_for_accounts",
]
