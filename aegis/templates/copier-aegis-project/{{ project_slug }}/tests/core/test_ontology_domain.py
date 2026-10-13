"""The model's domain layer (``ontology.domain``): one object per table,
with its fields, allowed values and owner; a link per foreign key; the
table each registered change type changes. Read from the models and the change
type registry, never a database."""

import importlib.util

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core.ontology import EdgeKind, Kind, SystemModel, domain, system_model
from app.core.ontology.model import ChangeNode, ObjectNode
from app.services.system.patterns import PROJECT_ROOT

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sqlmodel") is None,
    reason="no database in this stack: no tables",
)


@pytest.fixture
def model(app: FastAPI, client: TestClient) -> SystemModel:
    return system_model(app)


def _objects(model: SystemModel) -> dict[str, ObjectNode]:
    return {n.name: n for n in model.nodes if isinstance(n, ObjectNode)}


def test_every_table_is_an_object_its_part_owns(model: SystemModel) -> None:
    """Owned by the part whose folder its model is in; the shared core
    tables (``app/models``) by none. (Building the model imported them all.)"""
    from sqlmodel import SQLModel

    objects = _objects(model)
    ids = {n.id for n in model.nodes}
    modules = {
        m.local_table.name: m.class_.__module__ for m in SQLModel._sa_registry.mappers
    }
    for table in SQLModel.metadata.tables.values():
        found = objects[table.name]  # its name, never ``schema.name``
        core = modules.get(table.name, "").startswith("app.models.")
        assert found.owner in ids or (core and found.owner is None), table.name
        assert found.description, table.name
        assert {f.column or f.name for f in found.fields} == set(table.columns.keys())


def test_a_foreign_key_is_a_link_through_its_column(model: SystemModel) -> None:
    from sqlmodel import SQLModel

    links = {
        (e.source, e.target, e.via) for e in model.edges if e.kind is EdgeKind.LINK
    }
    for table in SQLModel.metadata.tables.values():
        for key in table.foreign_keys:
            target = key.column.table.name
            assert (
                f"object:{table.name}",
                f"object:{target}",
                key.parent.name,
            ) in links


def test_no_tables_no_objects() -> None:
    from sqlalchemy import MetaData

    assert domain.objects(MetaData(), lambda module: None) == ([], [])


def test_every_change_type_says_what_it_changes(model: SystemModel) -> None:
    """Its table, when to propose it, and every payload field described
    (``change_types``): what an agent reads instead of a prompt restating
    the schema."""
    changes = [n for n in model.nodes if isinstance(n, ChangeNode)]
    objects = {n.id for n in model.nodes if n.kind is Kind.OBJECT}
    changing = {(e.source, e.target) for e in model.edges if e.kind is EdgeKind.CHANGES}
    for change in changes:
        assert change.object in objects, change.name
        assert (change.id, change.object) in changing
        assert change.description, change.name
    if changes:
        from app.services.change_queue.registry import change_type_contracts

        for name, contract in change_type_contracts().items():
            schema = contract["schema"]
            described = [schema, *schema.get("$defs", {}).values()]
            fields = [f for s in described for f in s.get("properties", {}).values()]
            assert all(f.get("description") for f in fields), name


@pytest.mark.skipif(
    not (PROJECT_ROOT / "app/services/finance").is_dir(), reason="no finance"
)
def test_a_finance_transaction_says_what_it_is(model: SystemModel) -> None:
    transaction = _objects(model)["finance_transaction"]
    fields = {f.name: f for f in transaction.fields}
    assert transaction.owner == "service:finance"
    assert "cents" in fields["amount"].description
    assert fields["status"].allowed
    links = {(e.target, e.via) for e in model.edges if e.source == transaction.id}
    assert ("object:finance_account", "account_id") in links
    acting = {
        n.name
        for n in model.nodes
        if isinstance(n, ChangeNode) and n.object == transaction.id
    }
    assert {
        "transaction.categorize",
        "transaction.assign_payee",
        "transaction.tag",
        "transaction.untag",
        "transaction.split",
    } <= acting
