"""What a caller may read of the system model (the ``ontology`` tool's):
an admin all of it, a guest how the parts fit, anyone else the app's data.
"""

from typing import NamedTuple

from app.core.ontology import Kind
from app.core.ontology.model import DOMAIN_KINDS, STRUCTURE_KINDS, SystemModel
from app.services.shared.deps import caller_is_admin, caller_is_guest

# What ``ontology`` tells anyone but an admin, in every answer: an empty
# list alone had a model try each kind in turn.
DOMAIN_ONLY = (
    "Only the app's tables and the changes to them are read here: its "
    "parts, routes, jobs, queues, containers and keys are an admin's. "
    "Tell the user so; do not look further for them."
)


# What ``ontology`` tells a guest: how the parts fit, and nothing else.
STRUCTURE_ONLY = (
    "Only the app's structure is read here: its components and services, "
    "what each could be built as, and how they connect. Its data, routes, "
    "jobs, containers, health and code are not shared; do not look further "
    "for them."
)


def hidden(ids: list[str], kinds: tuple[Kind, ...]) -> list[str]:
    """The ids naming a kind outside ``kinds``: an unknown id is no one's,
    and is answered as unknown."""
    others = set(Kind) - set(kinds)
    return [i for i in ids if i.partition(":")[0] in others]


class ModelView(NamedTuple):
    """What the caller may read of the model: the kinds (None: every one)
    and the note saying what is left out."""

    model: SystemModel
    kinds: tuple[Kind, ...] | None = None
    note: str | None = None


async def view_of(model: SystemModel) -> ModelView:
    """An admin reads all of it, a guest how the parts fit, anyone else
    the app's data."""
    if caller_is_guest():
        return ModelView(model.structure(), STRUCTURE_KINDS, STRUCTURE_ONLY)
    if not await caller_is_admin():
        return ModelView(model.domain(), DOMAIN_KINDS, DOMAIN_ONLY)
    return ModelView(model)
