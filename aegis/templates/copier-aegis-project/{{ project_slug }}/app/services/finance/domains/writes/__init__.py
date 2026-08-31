"""The propose/approve write queue (FW-05).

Importing this package registers the built-in change types - an
executor that is never imported does not exist to the queue, the same
rule the tool registry lives by.
"""

from app.services.finance.domains.writes import executors as executors
from app.services.finance.domains.writes.queue import (
    approve,
    approve_batch,
    batch_rows,
    describe_change,
    get_change,
    list_changes,
    propose,
    propose_many,
    reject,
    reject_batch,
    withdraw,
)
from app.services.finance.domains.writes.registry import (
    ChangeExecutor,
    executor_for,
    register,
    registered_change_types,
)

__all__ = [
    "ChangeExecutor",
    "approve",
    "reject_batch",
    "propose_many",
    "batch_rows",
    "approve_batch",
    "describe_change",
    "executor_for",
    "get_change",
    "list_changes",
    "propose",
    "register",
    "registered_change_types",
    "reject",
    "withdraw",
]
