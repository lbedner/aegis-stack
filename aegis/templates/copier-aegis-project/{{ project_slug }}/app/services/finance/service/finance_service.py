"""``FinanceService``: a thin delegating facade: every method forwards to a
domain module (``accounts``, ``transactions``, ``budgets``, ...) as
``module.func(self.db, ...)``. New code should call the domain modules
directly; the facade exists so routes, jobs, and the CLI keep a single
injection point (``deps.get_finance_service``).

One mixin per domain area, each sitting opposite the module it forwards
to, so "where does the facade expose budgets" has an answer that is a
filename rather than a line number. The composition below is the whole
class - it declares no methods of its own. Callers import it from the
facade: ``from app.services.finance.service import FinanceService``.

Every read statement lives in a per-package ``queries.py`` under
``domains/`` and ``adapters/``; domain modules
own writes and orchestration. Writes ``db.add(...)`` + ``db.flush()`` but do
NOT commit - the caller (route / CLI / scheduler job) owns the transaction
boundary. Rows are owner-scoped by ``owner_user_id``.
"""

# Aliased: ``budgets`` and ``recurring`` also name the mixin modules beside
# this one, and the gate mirrors underneath want planning's.
from app.services.finance.domains.planning import budgets as planning_budgets
from app.services.finance.domains.planning import recurring as planning_recurring
from app.services.finance.service.accounts import AccountsMixin
from app.services.finance.service.base import FinanceServiceBase
from app.services.finance.service.budgets import BudgetsMixin
from app.services.finance.service.categories import CategoriesMixin
from app.services.finance.service.goals import GoalsMixin
from app.services.finance.service.imports import ImportsMixin
from app.services.finance.service.insights import InsightsMixin
from app.services.finance.service.investments import InvestmentsMixin
from app.services.finance.service.merchants import MerchantsMixin
from app.services.finance.service.networth import NetWorthMixin
from app.services.finance.service.recurring import RecurringMixin
from app.services.finance.service.transactions import TransactionsMixin


class FinanceService(
    AccountsMixin,
    TransactionsMixin,
    CategoriesMixin,
    MerchantsMixin,
    NetWorthMixin,
    BudgetsMixin,
    GoalsMixin,
    RecurringMixin,
    InsightsMixin,
    InvestmentsMixin,
    ImportsMixin,
    FinanceServiceBase,
):
    """Delegating facade over the finance domain modules."""

    # Mirrored so a caller holding the service can read the gate that
    # decided something without importing the domain module for it.
    _BUDGET_BILLED_SHARE = planning_budgets._BUDGET_BILLED_SHARE
    _BUDGET_LOOKBACK_MONTHS = planning_budgets._BUDGET_LOOKBACK_MONTHS
    _BUDGET_MAX_UNUSUAL_MONTHS = planning_budgets._BUDGET_MAX_UNUSUAL_MONTHS
    _BUDGET_MIN_AMOUNT = planning_budgets._BUDGET_MIN_AMOUNT
    _BUDGET_MIN_MONTHS = planning_budgets._BUDGET_MIN_MONTHS
    _BUDGET_UNUSUAL_BAND = planning_budgets._BUDGET_UNUSUAL_BAND
    _STREAM_DIRECTIONS = planning_recurring._STREAM_DIRECTIONS
    _STREAM_FREQUENCIES = planning_recurring._STREAM_FREQUENCIES
