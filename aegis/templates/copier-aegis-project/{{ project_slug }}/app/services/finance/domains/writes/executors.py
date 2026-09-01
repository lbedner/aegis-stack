"""The registered change types - one ``register()`` entry per type.

FW-05 shipped categorize to prove the loop end to end; later FW tickets
add theirs HERE. Definitions live in the topic modules (``curation`` for
the label axes, ``structure`` for what a row is); importing this module
arms the whole surface.
"""

from __future__ import annotations

from app.services.finance.domains.writes import curation, structure
from app.services.finance.domains.writes.registry import ChangeExecutor, register

register(
    ChangeExecutor(
        change_type="transaction.categorize",
        title="Categorize a transaction",
        payload_model=curation.CategorizePayload,
        execute=curation.categorize_execute,
        describe=curation.categorize_describe,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.assign_payee",
        title="Assign a payee",
        payload_model=curation.AssignPayeePayload,
        execute=curation.assign_payee_execute,
        describe=curation.assign_payee_describe,
    )
)
register(
    ChangeExecutor(
        change_type="recurring.match",
        title="Match a payment to a bill",
        payload_model=structure.MatchPayload,
        execute=structure.match_execute,
        describe=structure.match_describe,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.tag",
        title="Tag a transaction",
        payload_model=curation.TagPayload,
        execute=curation.tag_execute,
        describe=curation.tag_describe,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.untag",
        title="Remove a tag from a transaction",
        payload_model=curation.TagPayload,
        execute=curation.untag_execute,
        describe=curation.untag_describe,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.split",
        title="Split a transaction",
        payload_model=structure.SplitChangePayload,
        execute=structure.split_execute,
        describe=structure.split_describe,
    )
)
