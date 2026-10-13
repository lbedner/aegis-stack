"""The model's domain layer: what the app's data is, read from its table
models, never a database.

One object per table, ``object:<table name>`` (never the schema-qualified
key, so SQLite and Postgres agree): its owner by ``ownership``'s rule, its
class docstring's first sentence, and each column's type, whether it may
be empty, its ``Field(description=)`` and the values a single-column
``CHECK (x IN (...))`` lets in. A link per foreign key, through its
column. Each registered change type as the change it makes: the table it
changes. Names and types only: no defaults, no
rows, so a secret column shows as a name and nothing else."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import re
from typing import TYPE_CHECKING, Any

from app.core.formatting import first_sentence
from app.core.ontology.model import (
    ChangeNode,
    Edge,
    EdgeKind,
    Kind,
    ObjectField,
    ObjectNode,
    node_id,
)

if TYPE_CHECKING:  # a stack without a database has neither
    from sqlalchemy import Column, MetaData, Table

Owned = Callable[[str], str | None]  # a module -> the node owning it
IN_CHECK = re.compile(r"^\s*(\w+)\s+IN\s*\((.*)\)\s*$", re.IGNORECASE | re.DOTALL)


def objects(metadata: MetaData, owned: Owned) -> tuple[list[ObjectNode], list[Edge]]:
    """Each table in ``metadata`` as an object, and its foreign keys as
    links, in the order of their names."""
    from sqlmodel import SQLModel

    classes = {m.local_table: m.class_ for m in SQLModel._sa_registry.mappers}
    tables = sorted(metadata.tables.values(), key=lambda t: t.name)
    links = [
        Edge(
            source=node_id(Kind.OBJECT, table.name),
            target=node_id(Kind.OBJECT, key.column.table.name),
            kind=EdgeKind.LINK,
            via=key.parent.name,
        )
        for table in tables
        for key in sorted(table.foreign_keys, key=lambda k: k.parent.name)
    ]
    return [_object(t, classes.get(t), owned) for t in tables], links


def _object(table: Table, cls: type | None, owned: Owned) -> ObjectNode:
    attributes = _attributes(cls)
    described = getattr(cls, "model_fields", {})
    allowed = _allowed(table)
    return ObjectNode(
        name=table.name,
        owner=owned(cls.__module__) if cls else None,
        module=cls.__module__ if cls else None,
        class_name=cls.__name__ if cls else table.name,
        description=first_sentence(cls.__dict__.get("__doc__") if cls else None),
        fields=tuple(
            _column(c, attributes.get(c.name, c.name), described, allowed)
            for c in table.columns
        ),
    )


def _attributes(cls: type | None) -> dict[str, str]:
    """Each column's attribute name on its class (``date`` is ``date_``)."""
    mapper = getattr(cls, "__mapper__", None)
    if mapper is None:
        return {}
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


def _column(
    column: Column[Any],
    name: str,
    described: dict[str, Any],
    allowed: dict[str, tuple[str, ...]],
) -> ObjectField:
    field = described.get(name)
    return ObjectField(
        name=name,
        column=column.name if column.name != name else None,
        type=_type(column),
        nullable=bool(column.nullable),
        primary_key=column.primary_key,
        description=(field.description or "") if field else "",
        allowed=allowed.get(column.name, ()),
    )


def _type(column: Column[Any]) -> str:
    try:
        return column.type.python_type.__name__
    except NotImplementedError:
        return str(column.type).lower()


def _allowed(table: Table) -> dict[str, tuple[str, ...]]:
    """What each single-column ``IN (...)`` check lets in, by column."""
    from sqlalchemy import CheckConstraint

    found = {}
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint):
            continue
        match = IN_CHECK.match(str(constraint.sqltext))
        if match:
            found[match[1]] = tuple(re.findall(r"'([^']*)'", match[2]))
    return found


def change(
    name: str, executor: Any, owner: str | None, module: str | None
) -> ChangeNode:
    """A registered change type (its ``ChangeExecutor``) as the change it
    makes: the table it changes. Its payload is ``change_types``' to give,
    whole, as the schema an agent proposes against."""
    table = getattr(executor.object, "__table__", None)
    return ChangeNode(
        name=name,
        owner=owner,
        module=module,
        title=executor.title,
        description=executor.description,
        object=node_id(Kind.OBJECT, table.name) if table is not None else None,
    )


def changing(nodes: Iterable[ChangeNode]) -> list[Edge]:
    """A line from each change to the table it changes."""
    return [
        Edge(source=n.id, target=n.object, kind=EdgeKind.CHANGES)
        for n in nodes
        if n.object
    ]
