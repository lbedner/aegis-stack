"""Module boundaries inside the finance service's domain packages.

Behavioural tests cannot see this: every call reaches the same function
through the ``FinanceService`` facade whether the domain lives in one
1,000-line module or four small ones. So a later change that folds a
domain back together, or lands a new function in whichever file was open
at the time, passes the whole suite. These assertions are the only place
the split is stated, and they fail on the drift rather than on a name.
"""

from __future__ import annotations

from datetime import date
import inspect
from types import FunctionType

from app.services.finance import models
from app.services.finance.adapters.providers import connections
from app.services.finance.domains.detection import insights
from app.services.finance.domains.detection import recurring as detection_recurring
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning import budgets, recurring
from app.services.finance.domains.planning import queries as planning_queries
from app.services.finance.domains.planning.recurring import forecast
from app.services.finance.service import FinanceService

# Public function -> the submodule that must DEFINE it. Membership is the
# claim being made: streams own the row's lifecycle, matching owns the
# reconcile shortlist, forecast owns walking money forward, queries owns
# the reads. A function answering to two of those belongs to neither.
RECURRING_OWNERS = {
    "list_recurring": "streams",
    "create_recurring_stream": "streams",
    "get_recurring": "streams",
    "update_recurring": "streams",
    "delete_recurring": "streams",
    "mute_recurring": "streams",
    "unmute_recurring": "streams",
    "pause_recurring": "streams",
    "resume_recurring": "streams",
    "confirm_recurring": "streams",
    "attach_transaction_to_stream": "streams",
    "transfer_stream_ids": "streams",
    "payment_stream_ids": "streams",
    "stream_category_names": "streams",
    "recurring_match_candidates": "matching",
    "project_balances": "forecast",
    "goal_drawdowns": "forecast",
    "budget_drawdowns": "forecast",
}

# Reads that only the recurring domain issues. They sat in the shared
# planning/queries.py, which is what let the domain's own file grow
# without ever looking like it had.
RECURRING_QUERIES = {
    "all_live_streams",
    "active_streams",
    "stream_by_id",
    "stream_members",
    "stream_slot_clash",
    "stream_member_category_votes",
    "stream_stored_category_names",
    "transfer_flagged_stream_ids",
    "payment_flagged_stream_ids",
    "stray_payee_rows",
    "candidate_rows",
}


BUDGET_OWNERS = {
    "get_or_create_budget": "lines",
    "spend_for_target": "lines",
    "upsert_budget_line": "lines",
    "delete_budget_line": "lines",
    "suggest_budget_lines": "suggestions",
    "dismissal_markers": "suggestions",
    "list_dismissed_suggestions": "suggestions",
    "dismiss_budget_suggestions": "suggestions",
    "restore_budget_suggestions": "suggestions",
    "budget_summary": "summary",
    "uncovered_spending_rate": "uncovered",
    "uncovered_spend_filters": "uncovered",
    "budget_stat_details": "summary",
    "plan_budget_trims": "summary",
    "budget_month_outlook": "outlook",
    "parse_budget_goal": "outlook",
    "month_bounds": "queries",
}

# Reads against the budget tables, plus the outflow fetches only the
# budget surfaces issue. ``spend_filters``/``spend_by_*`` stay in the
# shared planning/queries.py - three domains ask for those.
BUDGET_QUERIES = {
    "month_bounds",
    "monthly_budget",
    "budget_lines_for_period",
    "budget_lines_with_category",
    "dismissal_marker_lines",
    "budget_line_for_target",
    "budget_line_by_id",
    "allocated_budget_lines",
    "categorized_outflow_history",
    "outflow_tuples",
    "sum_amount_where",
    "grouped_category_totals_where",
}

# The auto-budget gates. service.py mirrors them onto the facade, so
# they are API whether or not the underscore says so.
BUDGET_GATES = {
    "_BUDGET_LOOKBACK_MONTHS",
    "_BUDGET_MIN_MONTHS",
    "_BUDGET_UNUSUAL_BAND",
    "_BUDGET_MAX_UNUSUAL_MONTHS",
    "_BUDGET_MIN_AMOUNT",
    "_BUDGET_BILLED_SHARE",
}


def test_each_recurring_function_is_defined_by_its_owning_module() -> None:
    for name, owner in RECURRING_OWNERS.items():
        fn = getattr(recurring, name)
        assert (
            fn.__module__ == f"app.services.finance.domains.planning.recurring.{owner}"
        ), f"{name} is defined in {fn.__module__}, not the {owner} module"


def test_recurring_package_re_exports_its_whole_public_api() -> None:
    """Callers reach the domain as ``recurring.foo`` and must keep doing
    so - the package boundary is the API, the submodules are not."""
    for name in RECURRING_OWNERS:
        assert name in recurring.__all__, f"{name} missing from recurring.__all__"


def test_stream_reads_moved_out_of_the_shared_planning_queries() -> None:
    for name in RECURRING_QUERIES:
        assert hasattr(recurring.queries, name), (
            f"{name} is not in the recurring package's queries module"
        )
        assert not isinstance(getattr(planning_queries, name, None), FunctionType), (
            f"{name} is recurring-only and must not stay in planning/queries.py"
        )


def test_each_budget_function_is_defined_by_its_owning_module() -> None:
    for name, owner in BUDGET_OWNERS.items():
        fn = getattr(budgets, name)
        assert (
            fn.__module__ == f"app.services.finance.domains.planning.budgets.{owner}"
        ), f"{name} is defined in {fn.__module__}, not the {owner} module"


def test_budget_package_re_exports_its_whole_public_api() -> None:
    for name in BUDGET_OWNERS:
        assert name in budgets.__all__, f"{name} missing from budgets.__all__"
    for gate in BUDGET_GATES:
        assert gate in budgets.__all__, f"{gate} missing from budgets.__all__"


def test_budget_reads_moved_out_of_the_shared_planning_queries() -> None:
    for name in BUDGET_QUERIES:
        assert hasattr(budgets.queries, name), (
            f"{name} is not in the budgets package's queries module"
        )
        assert not isinstance(getattr(planning_queries, name, None), FunctionType), (
            f"{name} is budget-only and must not stay in planning/queries.py"
        )


def test_the_forecast_reads_month_bounds_through_the_package_boundary() -> None:
    """``budget_drawdowns`` reached into ``budgets._month_bounds`` - a
    private name across a domain boundary, which is how a helper ends up
    frozen by a caller that was never supposed to see it."""
    assert not hasattr(budgets, "_month_bounds")
    assert budgets.month_bounds(202608) == (date(2026, 8, 1), date(2026, 9, 1))
    assert "budgets._month_bounds" not in inspect.getsource(forecast)


INSIGHT_OWNERS = {
    "is_commitment": "commitments",
    "is_paused": "commitments",
    "not_paused_clause": "commitments",
    "commitment_rollup": "commitments",
    "stream_staleness": "commitments",
    "format_usd": "formatting",
    "format_apr": "formatting",
    "card_apr_bps": "formatting",
    "month_key": "formatting",
    "month_start_before": "formatting",
    "days_in_month": "formatting",
    "month_is_complete": "formatting",
    "pace_day": "formatting",
    "generate_insights": "rules",
    "create_insight_if_new": "rules",
    "monthly_category_spend": "rules",
    "live_account_ids": "rules",
}


def test_each_insight_function_is_defined_by_its_owning_module() -> None:
    for name, owner in INSIGHT_OWNERS.items():
        fn = getattr(insights, name)
        assert (
            fn.__module__ == f"app.services.finance.domains.detection.insights.{owner}"
        ), f"{name} is defined in {fn.__module__}, not the {owner} module"


def test_the_commitment_vocabulary_stays_importable_without_the_rules() -> None:
    """The whole point of the split. ``commitments`` may name constants and
    models and nothing else: the moment it reaches for the database, the
    planning domain, or the rules, every caller that imports it at module
    scope goes back to deferring the import inside a function."""
    source = inspect.getsource(insights.commitments)
    for forbidden in ("planning", "ledger", "AsyncSession", "detection.queries"):
        assert forbidden not in source, (
            f"commitments.py now depends on {forbidden}; the callers that "
            "import it at module scope will cycle"
        )


def test_the_vocabulary_is_imported_at_module_scope_by_its_callers() -> None:
    """A regression here is silent: a deferred import still works, it just
    quietly re-establishes the cycle this split removed."""
    from app.services.finance.domains.planning.budgets import outlook, suggestions
    from app.services.finance.domains.planning.recurring import forecast

    for module in (forecast, outlook, suggestions):
        source = inspect.getsource(module)
        for line in source.splitlines():
            if "from app.services.finance.domains.detection" in line:
                assert not line.startswith(" "), (
                    f"{module.__name__} defers a detection import again: {line.strip()}"
                )


CONNECTION_OWNERS = {
    "create_plaid_connection": "plaid_sync",
    "sync_plaid_connection": "plaid_sync",
    "process_plaid_webhook": "plaid_sync",
    "refresh_webhook_urls": "plaid_sync",
    "fire_sandbox_webhook": "plaid_sync",
    "complete_hosted_link": "plaid_sync",
    "relink_connection": "plaid_sync",
    "start_snaptrade_connect": "snaptrade_sync",
    "complete_snaptrade_connect": "snaptrade_sync",
    "sync_snaptrade_connection": "snaptrade_sync",
    "disconnect_connection": "registry",
    "sync_owner_connections": "registry",
    "sync_one_connection": "registry",
    "list_provider_connections": "common",
    "list_plaid_connections": "common",
    "get_connection": "common",
}


def test_each_connection_function_is_defined_by_its_owning_module() -> None:
    for name, owner in CONNECTION_OWNERS.items():
        fn = getattr(connections, name)
        expected = f"app.services.finance.adapters.providers.connections.{owner}"
        assert fn.__module__ == expected, (
            f"{name} is defined in {fn.__module__}, not the {owner} module"
        )


def test_the_two_providers_never_import_each_other() -> None:
    """The property that makes a third aggregator cheap. Only ``registry``
    may name both; the moment one provider's module reaches for the other,
    every future provider has to be threaded through both of them."""
    plaid_source = inspect.getsource(connections.plaid_sync)
    snaptrade_source = inspect.getsource(connections.snaptrade_sync)
    assert "snaptrade" not in plaid_source.lower().replace("snaptrade_connect", "")
    assert "PlaidClient" not in snaptrade_source
    assert "plaid_sync" not in snaptrade_source


def test_dispatch_across_providers_lives_only_in_the_registry() -> None:
    registry_source = inspect.getsource(connections.registry)
    assert "PlaidClient" in registry_source
    assert "SnapTradeClient" in registry_source


# The ledger's reads, by the sibling that consumes them. 54 of these have
# exactly one caller and it is always the matching module - which is what
# made a 1,383-line shared file the wrong shape for them.
LEDGER_QUERY_OWNERS = {
    "account_by_id": "accounts",
    "account_rollup": "networth",
    "accounts_page": "accounts",
    "alias_by_normalized_global": "categories",
    "all_categories": "categories",
    "balance_class_series": "networth",
    "balance_snapshots_between": "networth",
    "categorized_history": "categories",
    "category_alias_ids": "categories",
    "category_by_id": "categories",
    "category_by_slug_global": "categories",
    "category_names_by_id": "categories",
    "category_spend_totals": "categories",
    "category_usage_rows": "categories",
    "connection_rollup": "networth",
    "currency_by_code": "accounts",
    "daily_register_deltas": "networth",
    "dated_amounts_in_window": "transactions",
    "dedup_match": "transactions",
    "has_nonreconcile_register": "accounts",
    "holding_quantities": "networth",
    "icons_by_domains": "merchants",
    "institution_by_provider_ref": "accounts",
    "latest_valuation_value": "accounts",
    "liability_details_by_account": "accounts",
    "live_account_ids": "filters",
    "live_accounts_for_owner": "networth",
    "live_merchants_by_ids": "merchants",
    "live_streams_by_merchants": "merchants",
    "live_transactions_by_ids": "transactions",
    "live_transactions_by_merchants": "merchants",
    "live_transactions_for_merchant": "merchants",
    "merchant_by_id": "merchants",
    "merchant_by_normalized": "merchants",
    "merchant_usage_rows": "merchants",
    "merchants_by_ids": "merchants",
    "merchants_for_owner": "merchants",
    "net_worth_series_since": "networth",
    "net_worth_snapshots_between": "networth",
    "payeeless_transactions": "merchants",
    "priced_trade_rows": "networth",
    "reconcile_adjustment_on": "accounts",
    "register_balance_through": "accounts",
    "spending_rows": "categories",
    "splits_for_parents": "transactions",
    "tag_by_normalized_name": "transactions",
    "tag_links": "transactions",
    "tagged_transaction_ids": "transactions",
    "tags_by_transaction": "transactions",
    "tags_with_counts": "transactions",
    "top_payees_over_window": "transactions",
    "transaction_by_id": "transactions",
    "transaction_search_filter": "filters",
    "transaction_totals_by_account": "accounts",
    "transactions_by_ids": "transactions",
    "transactions_page": "transactions",
    "transfer_by_id": "transfers",
    "transfers_for_owner": "transfers",
    "uncategorized_catchall_ids": "filters",
    "uncategorized_page": "transactions",
    "valuation_by_key": "accounts",
    "valuations_for_account": "accounts",
    "valuations_for_accounts": "networth",
}


def test_each_ledger_read_is_defined_by_its_owning_module() -> None:
    for name, owner in LEDGER_QUERY_OWNERS.items():
        fn = getattr(ledger_queries, name)
        expected = f"app.services.finance.domains.ledger.queries.{owner}"
        assert fn.__module__ == expected, (
            f"{name} is defined in {fn.__module__}, not the {owner} module"
        )


def test_the_ledger_queries_package_re_exports_every_read() -> None:
    """Callers say ``ledger_queries.foo(...)`` and must keep saying it - the
    split is internal to the package, not a change of address."""
    for name in LEDGER_QUERY_OWNERS:
        assert name in ledger_queries.__all__, f"{name} missing from __all__"


def test_the_dead_snapshot_read_is_gone() -> None:
    assert not hasattr(ledger_queries, "balance_snapshots_since")


DETECTION_OWNERS = {
    "detect_recurring": "detect",
    "RecurringDetectionResult": "detect",
    "plan_recurring": "declare",
    "declare_recurring": "declare",
    "RecurringPlanGroup": "declare",
    "DeclareRecurringResult": "declare",
}


def test_each_detection_symbol_is_defined_by_its_owning_module() -> None:
    for name, owner in DETECTION_OWNERS.items():
        obj = getattr(detection_recurring, name)
        expected = f"app.services.finance.domains.detection.recurring.{owner}"
        assert obj.__module__ == expected, (
            f"{name} is defined in {obj.__module__}, not the {owner} module"
        )


def test_the_cadence_judgement_needs_no_database() -> None:
    """``cadence`` is the half you can reason about without a ledger: gaps
    in, a label out. Once it can query, every threshold argument turns into
    a fixture argument."""
    source = inspect.getsource(detection_recurring.cadence)
    for forbidden in ("AsyncSession", "select(", "detection import queries", "await "):
        assert forbidden not in source, f"cadence.py now does I/O: {forbidden}"


def test_declare_reuses_the_detect_pass_rather_than_its_own_writers() -> None:
    """A declared bill and a detected one must be written by the same code,
    or they drift."""
    source = inspect.getsource(detection_recurring.declare)
    assert "recurring.detect import" in source
    assert "_upsert_stream" in source


# The facade's 137 delegating methods, by the mixin that must define them.
# Each mixin sits opposite exactly one domain area, so "where does the
# facade expose budgets" has one answer instead of a line number.
SERVICE_OWNERS = {
    "account_rollup": "networth",
    "account_transaction_totals": "accounts",
    "add_valuation": "accounts",
    "asset_liability_totals": "networth",
    "assign_merchant": "merchants",
    "assign_payee_group": "merchants",
    "attach_transaction_to_stream": "recurring",
    "auto_contribute_goals": "goals",
    "auto_credit_envelopes": "goals",
    "budget_drawdowns": "recurring",
    "budget_month_outlook": "budgets",
    "budget_stat_details": "budgets",
    "budget_summary": "budgets",
    "categorize_transaction": "categories",
    "category_names": "categories",
    "category_usage": "categories",
    "confirm_recurring": "recurring",
    "confirm_transfer": "transactions",
    "connection_rollup": "networth",
    "contribute_to_goal": "goals",
    "count_new_insights": "insights",
    "create_envelope": "goals",
    "create_manual_account": "accounts",
    "create_merchant": "merchants",
    "create_recurring_stream": "recurring",
    "create_split": "transactions",
    "create_transaction": "transactions",
    "create_virtual_goal": "goals",
    "credit_envelope": "goals",
    "delete_budget_line": "budgets",
    "delete_recurring": "recurring",
    "dismiss_budget_suggestions": "budgets",
    "dismiss_insight": "insights",
    "dismissal_markers": "budgets",
    "find_transaction": "transactions",
    "flag_account_as_goal": "goals",
    "get_account": "accounts",
    "get_import_batch": "imports",
    "get_net_worth": "networth",
    "get_net_worth_series": "networth",
    "get_or_create_budget": "budgets",
    "get_or_create_category_from_hint": "categories",
    "get_or_create_currency": "accounts",
    "get_or_create_institution": "accounts",
    "get_or_create_pfc_category": "categories",
    "get_or_create_security": "investments",
    "get_or_create_tag": "transactions",
    "get_portfolio_value": "investments",
    "get_recurring": "recurring",
    "get_status_summary": "networth",
    "get_transaction": "transactions",
    "get_transfer": "transactions",
    "goal_allocations": "goals",
    "goal_drawdowns": "recurring",
    "goal_rate": "goals",
    "goal_rates": "goals",
    "health": "networth",
    "import_file": "imports",
    "liability_details": "accounts",
    "list_accounts": "accounts",
    "list_categories": "categories",
    "list_current_holdings": "investments",
    "list_dismissed_suggestions": "budgets",
    "list_envelopes": "goals",
    "list_goals": "goals",
    "list_import_batch_rows": "imports",
    "list_import_batches": "imports",
    "list_insights": "insights",
    "list_merchants": "merchants",
    "list_recurring": "recurring",
    "list_tags": "transactions",
    "list_trades": "investments",
    "list_transactions": "transactions",
    "list_transfers": "transactions",
    "list_valuations": "accounts",
    "merchant_category_summary": "merchants",
    "merchant_names": "merchants",
    "merchant_usage": "merchants",
    "merchant_websites": "merchants",
    "merge_merchants": "merchants",
    "monthly_cashflow": "transactions",
    "mute_recurring": "recurring",
    "parse_budget_goal": "budgets",
    "pause_recurring": "recurring",
    "payee_groups": "merchants",
    "payment_stream_ids": "recurring",
    "preview_file": "imports",
    "project_balances": "recurring",
    "reconcile_account": "accounts",
    "reconcile_adjustment_for": "accounts",
    "reconcile_preview": "accounts",
    "recurring_match_candidates": "recurring",
    "register_balance_as_of": "accounts",
    "reject_transfer": "transactions",
    "resolve_category_alias": "categories",
    "restore_budget_suggestions": "budgets",
    "resume_recurring": "recurring",
    "set_envelope_auto_credit": "goals",
    "set_goal_auto_contribute": "goals",
    "set_goal_status": "goals",
    "set_merchant_website": "merchants",
    "similar_unassigned": "merchants",
    "soft_delete_account": "accounts",
    "soft_delete_transactions": "transactions",
    "spend_for_target": "budgets",
    "spend_from_envelope": "goals",
    "spending_by_category": "categories",
    "spending_summary": "categories",
    "spending_transactions": "categories",
    "stream_category_names": "recurring",
    "suggest_budget_lines": "budgets",
    "suggest_categories": "categories",
    "sync_account_balance_from_holdings": "investments",
    "tag_transactions": "transactions",
    "top_payees": "transactions",
    "transaction_exists": "transactions",
    "transaction_tags": "transactions",
    "transactions_by_ids": "transactions",
    "transfer_stream_ids": "recurring",
    "uncategorized_transactions": "transactions",
    "uncovered_spend_filters": "budgets",
    "uncovered_spending_rate": "budgets",
    "unflag_goal": "goals",
    "unmute_recurring": "recurring",
    "untag_transactions": "transactions",
    "update_account": "accounts",
    "update_account_balance": "accounts",
    "update_envelope": "goals",
    "update_merchant": "merchants",
    "update_recurring": "recurring",
    "upsert_budget_line": "budgets",
    "upsert_holding": "investments",
    "upsert_provider_security": "investments",
    "upsert_security_price": "investments",
    "upsert_trade": "investments",
    "upsert_valuation": "accounts",
    "walk_envelope": "goals",
}


def test_each_facade_method_is_defined_by_its_owning_mixin() -> None:
    for name, owner in SERVICE_OWNERS.items():
        method = getattr(FinanceService, name)
        expected = f"app.services.finance.service.{owner}"
        assert method.__module__ == expected, (
            f"{name} is defined in {method.__module__}, not the {owner} mixin"
        )


def test_the_facade_still_exposes_every_method_it_used_to() -> None:
    """The split is internal. Routes, jobs and the CLI hold a
    ``FinanceService`` and call it - none of them may notice this happened."""
    missing = [
        n for n in SERVICE_OWNERS if not callable(getattr(FinanceService, n, None))
    ]
    assert not missing, f"the facade dropped {missing}"
    assert FinanceService(None).db is None  # the one piece of state, still there


def test_the_facade_mirrors_the_domain_gates_it_always_did() -> None:
    for gate in BUDGET_GATES:
        assert getattr(FinanceService, gate) == getattr(budgets, gate)
    for gate in ("_STREAM_DIRECTIONS", "_STREAM_FREQUENCIES"):
        assert getattr(FinanceService, gate) == getattr(recurring, gate)


# The 35 finance tables, by the module that must declare them. Splitting
# declarations is safe only while every model still lands in
# ``SQLModel.metadata`` - which is what alembic autogenerate reads, and what
# ``aegis.core.migration_generator.FINANCE_MIGRATION`` must stay
# column-for-column compatible with.
MODEL_OWNERS = {
    "FinanceAccount": "accounts",
    "FinanceAnalystSnapshot": "analyst",
    "FinanceAttachment": "imports",
    "FinanceBalanceSnapshot": "accounts",
    "FinanceBudget": "planning",
    "FinanceBudgetCategory": "planning",
    "FinanceCategory": "categorization",
    "FinanceCategoryAlias": "categorization",
    "FinanceConnection": "connections",
    "FinanceCurrency": "reference",
    "FinanceFxRate": "reference",
    "FinanceHolding": "investments",
    "FinanceIcon": "reference",
    "FinanceImportBatch": "imports",
    "FinanceImportBatchRow": "imports",
    "FinanceImportProfile": "imports",
    "FinanceInsight": "planning",
    "FinanceInstitution": "connections",
    "FinanceLiabilityDetail": "accounts",
    "FinanceMerchant": "categorization",
    "FinanceNetWorthSnapshot": "accounts",
    "FinanceRecurringStream": "planning",
    "FinanceRule": "categorization",
    "FinanceSecurity": "investments",
    "FinanceSecurityPrice": "investments",
    "FinanceSpendingBaseline": "planning",
    "FinanceTag": "categorization",
    "FinanceTrade": "investments",
    "FinanceTransaction": "transactions",
    "FinanceTransactionChangelog": "analyst",
    "FinanceTransactionSplit": "transactions",
    "FinanceTransactionTag": "categorization",
    "FinanceTransfer": "transactions",
    "FinanceValuation": "accounts",
    "FinanceWebhookEvent": "connections",
}


def test_each_table_is_declared_by_its_owning_module() -> None:
    for name, owner in MODEL_OWNERS.items():
        cls = getattr(models, name)
        expected = f"app.services.finance.models.{owner}"
        assert cls.__module__ == expected, (
            f"{name} is declared in {cls.__module__}, not the {owner} module"
        )


def test_every_table_still_registers_in_the_shared_metadata() -> None:
    """The property the whole split rides on. A model that never gets
    imported is absent from ``SQLModel.metadata``, which means alembic
    autogenerate silently proposes dropping its table."""
    from sqlmodel import SQLModel

    registered = {
        cls.__tablename__
        for cls in SQLModel.__subclasses__()
        if getattr(cls, "__tablename__", None)
    }
    for name in MODEL_OWNERS:
        table = getattr(models, name).__tablename__
        assert table in registered, f"{name} ({table}) never reached the metadata"
        assert table in SQLModel.metadata.tables or any(
            t.endswith(f".{table}") or t == table for t in SQLModel.metadata.tables
        ), f"{table} missing from SQLModel.metadata"


def test_the_models_package_re_exports_every_table() -> None:
    """Twelve modules import ``from ...finance.models import Finance*`` and
    alembic's env.py names them explicitly - none of that may move."""
    for name in MODEL_OWNERS:
        assert name in models.__all__, f"{name} missing from models.__all__"


def test_domains_never_reach_into_adapters() -> None:
    """The direction of travel the folder split exists to state.

    A domain that imports an adapter makes a provider outage or a file
    format into a business concern. This bit once: the payee-normalization
    vocabulary lived in ``importers/base.py`` because that is where the
    first caller was, so seven domain modules imported an adapter to speak
    it. It moved to ``utils``; this keeps it moved.
    """
    import pathlib

    import app.services.finance.domains as domains_pkg

    root = pathlib.Path(domains_pkg.__file__).parent
    offenders = [
        f"{path.relative_to(root)}:{n}"
        for path in root.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if "finance.adapters" in line
        and not line.lstrip().startswith(("#", "``"))
        and path.name != "__init__.py"
    ]
    assert not offenders, f"domains importing adapters: {offenders}"


def test_the_service_root_separates_knowing_from_talking() -> None:
    """Six folders, each answering a different question - ``models`` is
    what's stored, ``schemas`` is what's spoken over the API. A new
    package at this level means a new KIND of thing, worth noticing."""
    import pathlib

    import app.services.finance as finance_pkg

    root = pathlib.Path(finance_pkg.__file__).parent
    folders = {p.name for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert folders == {
        "domains",
        "adapters",
        "models",
        "schemas",
        "service",
        "seeds",
    }, folders
