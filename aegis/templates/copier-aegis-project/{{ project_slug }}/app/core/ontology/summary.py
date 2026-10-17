"""What the app is, in brief (``summary``): the ``ontology`` tool's answer
with no arguments. The app, its nodes counted by kind, its parts where the
reader may see them, and its data: the tables by the part owning them, each
with the tables it links to, and the changes that can be made to them.
Read from the model alone, so the same model answers the same; ``text``
writes it as an agent always has it (``app_map``, a memory module)."""

from collections import Counter

from pydantic import BaseModel, ConfigDict

from app.core.ontology.model import (
    ChangeNode,
    EdgeKind,
    ObjectNode,
    PartNode,
    Stack,
    SystemModel,
    parse_node_id,
)

# The owner a table no part owns is listed under.
UNOWNED = "unowned"
# Where the map ends, its first line: with it in hand an agent answers
# from it and fills in the rest from general knowledge, unless told what
# it lacks and what has it. Anyone but an admin has no route walk.
EDGE = (
    "This app, read from its code. This map has no routes, functions, "
    "files, what depends on what, or how a request moves between parts: for "
    "any of those, call the ontology tool before answering (a part's "
    "neighbours say what it uses and what uses it; a route's walk gives each "
    "step's file and line). Never fill them in from general knowledge; where "
    "neither says, say you don't know."
)
DATA_EDGE = (
    "This app's data, read from its code. For more than this map has, call "
    "the ontology tool before answering. Never fill it in from general "
    "knowledge; where neither says, say you don't know."
)


class ChangeBrief(BaseModel):
    """A change an agent may propose: what it does, the table it changes."""

    model_config = ConfigDict(frozen=True)

    title: str
    table: str | None


class Summary(BaseModel):
    """What the app is, in brief: ``parts`` empty where the reader may see
    only the app's data (``SystemModel.domain``)."""

    model_config = ConfigDict(frozen=True)

    app: Stack
    counts: dict[str, int]  # nodes by kind: an ``object`` is a table
    parts: tuple[PartNode, ...] = ()
    tables: dict[str, dict[str, list[str]]]  # owner -> table -> tables it links to
    changes: dict[str, ChangeBrief]


def _name(found: str) -> str:
    return parse_node_id(found)[1]


def tables(model: SystemModel) -> dict[str, dict[str, list[str]]]:
    """Each table by the part owning it, with the tables it links to."""
    links: dict[str, dict[str, None]] = {}  # each linked table once, in order
    for edge in model.edges:
        if edge.kind is EdgeKind.LINK:
            links.setdefault(edge.source, {})[_name(edge.target)] = None
    grouped: dict[str, dict[str, list[str]]] = {}
    for node in model.nodes:
        if isinstance(node, ObjectNode):
            owned = grouped.setdefault(node.owner or UNOWNED, {})
            owned[node.name] = list(links.get(node.id, {}))
    return grouped


def summary(model: SystemModel) -> Summary:
    return Summary(
        app=model.stack,
        counts=Counter(n.kind.value for n in model.nodes),
        parts=tuple(n for n in model.nodes if isinstance(n, PartNode)),
        tables=tables(model),
        changes={
            n.name: ChangeBrief(
                title=n.title, table=_name(n.object) if n.object else None
            )
            for n in model.nodes
            if isinstance(n, ChangeNode)
        },
    )


def text(found: Summary) -> str:
    """``found`` as a short map for a prompt: each part with what it is
    for (its sub-parts left to the tool, as its routes are), the tables by
    owner with what each links to, and the changes.
    Nothing live (no traffic, health or rows), so its bytes stay the same
    turn to turn and a provider's prompt cache serves them."""
    lines = [EDGE if found.parts else DATA_EDGE]
    if found.parts:
        lines += ["", "Parts:"] + [
            f"- {p.id}: {p.description}" if p.description else f"- {p.id}"
            for p in found.parts
            if p.owner is None
        ]
    if found.tables:
        lines += ["", "Tables, by owner (a table's links in brackets):"] + [
            f"- {owner}: " + ", ".join(_linked(t, links) for t, links in owned.items())
            for owner, owned in found.tables.items()
        ]
    if found.changes:
        lines += ["", "Changes that can be proposed:"] + [
            f"- {name}: {change.title} (on {change.table})"
            if change.table
            else f"- {name}: {change.title}"
            for name, change in found.changes.items()
        ]
    return "\n".join(lines)


def _linked(table: str, links: list[str]) -> str:
    return f"{table} ({', '.join(links)})" if links else table
