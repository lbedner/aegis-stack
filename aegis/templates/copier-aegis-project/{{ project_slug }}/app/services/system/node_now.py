"""What is true of a part now (``now``), beside what its code says: the
``ontology`` tool's answer for one part carries it. Its health check, the
errors it owns, and for the AI service what it has spent, each read when
asked and stamped with when, so a figure from an earlier turn reads as
old. And what is wrong across the app right now (``right_now``), the one
line an assistant's current message carries while something is."""

import asyncio
from collections.abc import Iterator, Mapping
from datetime import datetime
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.edges_http import AI
from app.core.log import logger
from app.core.ontology import Kind
from app.core.ontology.model import Node, PartNode
from app.core.time import utcnow
from app.services.system import live_status, ui_errors
from app.services.system.errors.models import ErrorIssue
from app.services.system.errors.read import search
from app.services.system.errors.store import ErrorStore
from app.services.system.models import ComponentStatus, ComponentStatusType

# The most issues a part's ``now`` lists, latest first; ``errors_total``
# counts them all.
NOW_ERRORS = 5
# What an agent reads: a field that is not one, or a figure changed after
# it was read, is refused (the AI service's ``schemas.FIGURES``; this
# module ships where that one does not).
FIGURES = ConfigDict(frozen=True, extra="forbid")


class UsageWindow(BaseModel):
    """What the AI service spent over a named window (``since`` None: all
    time), named as its ``UsageTotals`` are."""

    model_config = FIGURES

    label: str
    since: datetime | None
    total_requests: int
    total_tokens: int
    total_cost: float  # USD


class NodeNow(BaseModel):
    """A part's live state: its health check (None where it has none), the
    issues it owns, its spend, and when all of it was read."""

    model_config = FIGURES

    health: ComponentStatus | None
    errors: tuple[ErrorIssue, ...]
    errors_total: int
    errors_note: str | None  # why errors could not be read, when not
    spend: tuple[UsageWindow, ...]
    read_at: datetime


class Attention(BaseModel):
    """A check that is not healthy: its dotted name, status and message."""

    model_config = FIGURES

    name: str
    status: ComponentStatusType
    message: str


class RightNow(BaseModel):
    """What is wrong across the app, when it was read, and why it may be
    less than all of it (``note``)."""

    model_config = FIGURES

    attention: tuple[Attention, ...]
    read_at: datetime
    note: str | None = None

    def line(self) -> str | None:
        """One line for the current message, or None while nothing is
        wrong and every check was read: silence must mean all clear."""
        said = "; ".join(
            f"{a.name.rsplit('.', 1)[-1]} {a.status.value}: {a.message}"
            for a in self.attention
        )
        told = ". ".join(part for part in (said, self.note) if part)
        if not told:
            return None
        return (
            f"Right now (read {self.read_at:%H:%M} UTC): {told}. "
            "Ask the health tool or the ontology for more."
        )


def checks(
    components: dict[str, ComponentStatus], prefix: str = ""
) -> Iterator[tuple[str, ComponentStatus]]:
    """Each check in the tree by its dotted name, but one only passing on
    its parts' issues (``aegis``, ``components``): it is not one more."""
    for key, component in components.items():
        name = f"{prefix}{key}"
        yield from checks(component.sub_components, f"{name}.")
        parts = component.sub_components.values()
        if component.healthy or all(p.healthy for p in parts):
            yield name, component


def attention(components: dict[str, ComponentStatus]) -> tuple[Attention, ...]:
    """Every check that is not healthy: what the ``health`` tool and the
    current message's line both report."""
    return tuple(
        Attention(name=name, status=c.status, message=c.message)
        for name, c in checks(components)
        if not c.healthy
    )


async def right_now() -> RightNow:
    """What is wrong, read now. A read that fails says so on the line and
    never fails the turn it rides."""
    try:
        status, note = await live_status.live_status()
    except Exception as exc:
        logger.warning("right-now health read failed", error=str(exc))
        return RightNow(
            attention=(),
            read_at=utcnow(),
            note=f"the app's health could not be read ({type(exc).__name__})",
        )
    return RightNow(attention=attention(status.components), read_at=utcnow(), note=note)


# An agent's copy of a check's details: what fits a prompt. The page
# shows the rest (every table's schema, every migration). Passwords are
# already hidden in every check (``ComponentStatus``).
DETAIL_CHARS = 500


def health_of(
    components: dict[str, ComponentStatus], name: str
) -> ComponentStatus | None:
    """The check named ``name``, wherever it sits in the tree, as an agent
    reads it (``trimmed``)."""
    for key, component in components.items():
        if key == name:
            return trimmed(component)
        if found := health_of(component.sub_components, name):
            return found
    return None


def trimmed(component: ComponentStatus) -> ComponentStatus:
    """``component`` with only the details that fit a prompt, and the names
    of those left out (``omitted``), its parts the same."""
    kept = {
        key: value
        for key, value in component.metadata.items()
        if len(json.dumps(value, default=str)) <= DETAIL_CHARS
    }
    if omitted := sorted(set(component.metadata) - set(kept)):
        kept["omitted"] = omitted
    return component.model_copy(
        update={
            "metadata": kept,
            "sub_components": {
                k: trimmed(v) for k, v in component.sub_components.items()
            },
        }
    )


async def now_of(node: Node) -> NodeNow | None:
    """``node``'s live state, or None: only a top-level part has one (a
    sub-part's errors and health are its part's). Its three reads run at
    once."""
    if not isinstance(node, PartNode) or node.owner is not None:
        return None
    owner = "app_component" if node.kind is Kind.COMPONENT else "app_service"
    (status, _), found, spend = await asyncio.gather(
        live_status.live_status(),
        ui_errors.load({owner: node.name}, _owned),
        _spend(node),
    )
    return NodeNow(
        health=health_of(status.components, node.name),
        errors=tuple(found["error_rows"]),
        errors_total=found["error_total"],
        errors_note=found["error_note"],
        spend=spend,
        read_at=utcnow(),
    )


async def _owned(store: ErrorStore, query: Mapping[str, str]) -> dict[str, Any]:
    """The first ``NOW_ERRORS`` issues ``query``'s owner has, and how many."""
    # ponytail: scans every retained occurrence to find one owner's; a
    # per-owner index in the store if node reads get frequent.
    rows, total = await search(store, query, offset=0, limit=NOW_ERRORS)
    return {"error_rows": rows, "error_total": total}


async def _spend(node: PartNode) -> tuple[UsageWindow, ...]:
    if node.id != AI:
        return ()
    from app.services.ai import service as ai

    # An AI service without a database keeps no ledger: its facade offers
    # no spend.
    if "spend_windows" not in ai.__all__:
        return ()
    return await ai.spend_windows()
