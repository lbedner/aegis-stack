"""The registered change types - one ``register()`` entry per type.

FW-05 shipped categorize to prove the loop end to end; later FW tickets
add theirs HERE. Definitions live in the topic modules (``curation`` for
the label axes, ``structure`` for what a row is); importing this module
arms the whole surface.
"""

from __future__ import annotations

from app.services.finance.domains.writes import curation, structure
from app.services.change_queue.registry import ChangeExecutor, register
from app.services.finance.models import FinanceRecurringStream, FinanceTransaction

register(
    ChangeExecutor(
        change_type="transaction.categorize",
        title="Categorize a transaction",
        payload_model=curation.CategorizePayload,
        execute=curation.categorize_execute,
        describe=curation.categorize_describe,
        description="File a transaction under one category.",
        object=FinanceTransaction,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.assign_payee",
        title="Assign a payee",
        payload_model=curation.AssignPayeePayload,
        execute=curation.assign_payee_execute,
        describe=curation.assign_payee_describe,
        description="Name who a transaction was really with (these 12 ATM "
        "withdrawals are Hudson Valley Grounded).",
        object=FinanceTransaction,
    )
)
register(
    ChangeExecutor(
        change_type="recurring.match",
        title="Match a payment to a bill",
        payload_model=structure.MatchPayload,
        execute=structure.match_execute,
        describe=structure.match_describe,
        description="Record which payment paid which bill.",
        object=FinanceRecurringStream,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.tag",
        title="Tag a transaction",
        payload_model=curation.TagPayload,
        execute=curation.tag_execute,
        describe=curation.tag_describe,
        description="Put a label on a transaction beside its category "
        "(Business on a Software row), so one lens rolls up across categories.",
        object=FinanceTransaction,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.untag",
        title="Remove a tag from a transaction",
        payload_model=curation.TagPayload,
        execute=curation.untag_execute,
        describe=curation.untag_describe,
        description="Take a label off a transaction.",
        object=FinanceTransaction,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.split",
        title="Split a transaction",
        payload_model=structure.SplitChangePayload,
        execute=structure.split_execute,
        describe=structure.split_describe,
        description="Carve one purchase into category lines ($25 of the "
        "Target run was food). The parent row never changes; budgets and "
        "category views count the lines.",
        object=FinanceTransaction,
    )
)
