"""Finance service database models.

SQLModel tables for the finance aggregator. One module per table group;
the migration in ``aegis.core.migration_generator`` (``FINANCE_MIGRATION``)
is the parallel definition and must stay column-for-column compatible
(tests build tables from these models via ``SQLModel.metadata.create_all``;
the generated project builds them from the migration).

Importing this package imports every table module, which is the point:
a model that is never imported is absent from ``SQLModel.metadata``, and
alembic autogenerate reads that metadata to decide what exists. A new
table module MUST be added to the imports below or autogenerate will
propose dropping its table.

Column conventions, the ``finance`` Postgres schema, and the shared
``_bigint`` / ``_utcnow`` helpers live in ``base``.
"""

from app.services.finance.models.accounts import (
    FinanceAccount,
    FinanceBalanceSnapshot,
    FinanceLiabilityDetail,
    FinanceNetWorthSnapshot,
    FinanceValuation,
)
from app.services.finance.models.analyst import (
    FinanceAnalystSnapshot,
    FinanceTransactionChangelog,
)
from app.services.finance.models.categorization import (
    FinanceCategory,
    FinanceCategoryAlias,
    FinanceMerchant,
    FinanceRule,
    FinanceTag,
    FinanceTransactionTag,
)
from app.services.finance.models.connections import (
    FinanceConnection,
    FinanceInstitution,
    FinanceWebhookEvent,
)
from app.services.finance.models.imports import (
    FinanceAttachment,
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
)
from app.services.finance.models.investments import (
    FinanceHolding,
    FinanceSecurity,
    FinanceSecurityPrice,
    FinanceTrade,
)
from app.services.finance.models.planning import (
    FinanceBudget,
    FinanceBudgetCategory,
    FinanceInsight,
    FinanceRecurringStream,
    FinanceSpendingBaseline,
)
from app.services.finance.models.reference import (
    FinanceCurrency,
    FinanceFxRate,
    FinanceIcon,
)
from app.services.finance.models.transactions import (
    FinanceTransaction,
    FinanceTransactionSplit,
    FinanceTransfer,
)

__all__ = [
    "FinanceAccount",
    "FinanceAnalystSnapshot",
    "FinanceAttachment",
    "FinanceBalanceSnapshot",
    "FinanceBudget",
    "FinanceBudgetCategory",
    "FinanceCategory",
    "FinanceCategoryAlias",
    "FinanceConnection",
    "FinanceCurrency",
    "FinanceFxRate",
    "FinanceHolding",
    "FinanceIcon",
    "FinanceImportBatch",
    "FinanceImportBatchRow",
    "FinanceImportProfile",
    "FinanceInsight",
    "FinanceInstitution",
    "FinanceLiabilityDetail",
    "FinanceMerchant",
    "FinanceNetWorthSnapshot",
    "FinanceRecurringStream",
    "FinanceRule",
    "FinanceSecurity",
    "FinanceSecurityPrice",
    "FinanceSpendingBaseline",
    "FinanceTag",
    "FinanceTrade",
    "FinanceTransaction",
    "FinanceTransactionChangelog",
    "FinanceTransactionSplit",
    "FinanceTransactionTag",
    "FinanceTransfer",
    "FinanceValuation",
    "FinanceWebhookEvent",
]
