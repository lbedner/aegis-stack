"""The change-type registry: what the queue knows how to execute.

One entry per mutation kind. FW-06..09 grow by REGISTERING here - a
payload contract, an executor, a describer - never by adding queue
machinery. The payload model validates at propose time (a card the user
cannot safely approve should never exist) and again at approve time
(the world may have moved between the two).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.schemas import ChangeDisplayRow


@dataclass(frozen=True)
class ChangeExecutor:
    """One kind of proposable mutation.

    ``execute`` runs the REAL service mutation and returns an audit
    summary; ``describe`` resolves the payload's ids into the typed
    card rows the confirmation surface renders - system truth from the
    database, never model-authored copy. Rows are ``ChangeDisplayRow``
    end to end; they become plain dicts only at the freeze into the
    audit column and at the tool-result boundary.
    """

    change_type: str
    title: str
    payload_model: type[BaseModel]
    execute: Callable[[AsyncSession, Any, int | None], Awaitable[dict[str, Any]]]
    describe: Callable[
        [AsyncSession, Any, int | None], Awaitable[list[ChangeDisplayRow]]
    ]


_EXECUTORS: dict[str, ChangeExecutor] = {}


def register(executor: ChangeExecutor) -> ChangeExecutor:
    """Add one change type. Double registration is a wiring bug, not a
    merge - two executors silently fighting over one type is exactly
    the ambiguity a confirmation queue cannot carry."""
    if executor.change_type in _EXECUTORS:
        raise ValueError(f"change type {executor.change_type!r} already registered")
    _EXECUTORS[executor.change_type] = executor
    return executor


def executor_for(change_type: str) -> ChangeExecutor:
    try:
        return _EXECUTORS[change_type]
    except KeyError:
        raise ValueError(f"unknown change type: {change_type!r}") from None


def registered_change_types() -> tuple[str, ...]:
    return tuple(sorted(_EXECUTORS))
