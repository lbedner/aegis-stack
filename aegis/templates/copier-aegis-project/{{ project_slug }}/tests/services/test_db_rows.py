"""A table's rows as Overseer pages through them (``db_rows``): only a table
the app's models declare, a page at a time, the default order paged by its
key rather than by offset, sorted and filtered only where an index serves
it, what holds a secret never read, and read without taking SQLite's write
lock or running past its time."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from app.core import exposure, model_registry
from app.services.system import db_rows
from tests.services._db_fixtures import (
    EVENT,
    MEMBER,
    META,
    NOTE,
    ORG,
    TAGGED,
    TREE,
    seeded,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return seeded(tmp_path)


def _column(found: db_rows.Rows, name: str) -> list[str]:
    at = found.columns.index(name)
    return [row[at] for row in found.rows]


def test_only_a_table_the_models_declare_is_read() -> None:
    assert db_rows.table_of("member", META) is MEMBER
    assert db_rows.table_of("member; DROP TABLE member", META) is None
    assert db_rows.table_of("sqlite_master", META) is None


def test_only_tables_the_database_has_are_offered() -> None:
    """The health check lists what was migrated; a model of a table that
    is not there is not offered (reading it would fail)."""
    every = db_rows.tables()
    assert db_rows.tables([every[0], "not_a_model"]) == [every[0]]


def test_every_model_counts_though_none_was_imported_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What is a secret is read from every model's table: a process that
    has not imported a model (a script, a worker) must still know it."""
    imported: list[bool] = []
    monkeypatch.setattr(
        model_registry, "import_all_models", lambda: imported.append(True) or []
    )
    db_rows.models.cache_clear()
    try:
        db_rows.tables()
    finally:
        db_rows.models.cache_clear()
    assert imported


def test_the_default_order_pages_by_its_key(engine: Engine) -> None:
    """A page, then the next from where it ended: by the key, not an
    offset, so a deep page costs what the first does."""
    first = db_rows.page(MEMBER, engine=engine)
    assert len(first.rows) == db_rows.PAGE
    assert first.rows[0][0] == "1" and first.next == {"after": "25"}
    assert first.prev is None
    second = db_rows.page(MEMBER, after="25", engine=engine)
    assert second.rows[0][0] == "26" and second.prev == {"before": "26"}
    back = db_rows.page(MEMBER, before="26", engine=engine)
    assert back.rows == first.rows and back.prev is None
    last = db_rows.page(MEMBER, after="50", engine=engine)
    assert len(last.rows) == 10 and last.next is None


def test_newest_first_pages_by_its_key_too(engine: Engine) -> None:
    first = db_rows.page(MEMBER, order="id", desc=True, engine=engine)
    assert first.rows[0][0] == "60" and first.next == {"after": "36"}
    second = db_rows.page(MEMBER, order="id", desc=True, after="36", engine=engine)
    assert second.rows[0][0] == "35" and second.prev == {"before": "35"}
    back = db_rows.page(MEMBER, order="id", desc=True, before="35", engine=engine)
    assert back.rows == first.rows


def test_a_secret_never_leaves_the_database(engine: Engine) -> None:
    """Hidden by its name if it is text; a count or a flag named like one
    (``input_tokens``) is data, and shown."""
    found = db_rows.page(MEMBER, engine=engine)
    assert found.masked == {"hashed_password", "api_token"}
    assert set(_column(found, "hashed_password")) == {db_rows.HIDDEN}
    assert _column(found, "input_tokens")[:2] == ["10", "20"]


def test_a_secret_cannot_be_sorted_or_filtered_by(engine: Engine) -> None:
    """Either would tell its values apart without showing them."""
    with pytest.raises(ValueError):
        db_rows.page(MEMBER, order="hashed_password", engine=engine)
    with pytest.raises(ValueError):
        db_rows.page(MEMBER, where=[("hashed_password", "x")], engine=engine)


def test_a_long_cell_is_redacted_then_cut(engine: Engine) -> None:
    bio = _column(db_rows.page(MEMBER, engine=engine), "bio")[0]
    assert "s3cret" not in bio and bio.endswith("…")
    assert len(bio) <= db_rows.CELL + 1


def test_binary_shows_its_size(engine: Engine) -> None:
    avatar = _column(db_rows.page(MEMBER, engine=engine), "avatar")[0]
    assert avatar == "binary, 16 bytes"


def test_a_filter_is_one_indexed_or_foreign_key_column(engine: Engine) -> None:
    org = db_rows.page(MEMBER, where=[("org_id", "3")], engine=engine)
    assert org.rows and set(_column(org, "org_id")) == {"3"}
    with pytest.raises(ValueError):  # unindexed: a scan of the table
        db_rows.page(MEMBER, where=[("bio", "short")], engine=engine)


def test_a_flag_filters_as_a_flag(engine: Engine) -> None:
    """``false`` is false (``bool("false")`` is not)."""
    MEMBER.c.active.index = True
    try:
        off = db_rows.page(MEMBER, where=[("active", "false")], engine=engine)
    finally:
        MEMBER.c.active.index = None
    assert off.rows and set(_column(off, "active")) == {"False"}


def test_another_order_pages_by_offset_only_where_indexed(engine: Engine) -> None:
    found = db_rows.page(MEMBER, order="email", desc=True, number=2, engine=engine)
    assert found.next == {"page": "3"} and found.prev == {"page": "1"}
    emails = sorted((f"m{n:02}@x.io" for n in range(1, 61)), reverse=True)
    assert _column(found, "email") == emails[db_rows.PAGE : 2 * db_rows.PAGE]
    assert "bio" not in found.sortable
    with pytest.raises(ValueError):
        db_rows.page(MEMBER, order="bio", engine=engine)


def test_pages_by_offset_go_only_so_deep(engine: Engine) -> None:
    deep = db_rows.MAX_DEPTH + 1
    with pytest.raises(ValueError):
        db_rows.page(MEMBER, order="email", number=deep, engine=engine)


def test_a_table_without_one_key_pages_in_its_keys_order(engine: Engine) -> None:
    assert len(db_rows.page(EVENT, number=2, engine=engine).rows) == 5
    tagged = db_rows.page(TAGGED, engine=engine)
    assert tagged.key is None
    assert tagged.rows == [["1", "1"], ["1", "2"], ["2", "1"], ["2", "2"]]


def test_hidden_where_rows_are_not_shown(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exposure, "refusal", lambda flag: "off here.")
    with pytest.raises(db_rows.RowsHiddenError):
        db_rows.page(MEMBER, engine=engine)


def test_a_read_past_its_time_is_stopped(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_rows, "SECONDS", -1.0)
    monkeypatch.setattr(db_rows, "STEPS", 1)
    with pytest.raises(db_rows.ReadTooSlowError):
        db_rows.page(MEMBER, engine=engine)


def test_reading_takes_no_write_lock(engine: Engine, tmp_path: Path) -> None:
    """A write held open elsewhere does not stop a read, nor the read it."""
    other = create_engine(
        f"sqlite:///{tmp_path / 'rows.db'}", connect_args={"timeout": 0}
    )
    with other.connect() as writer:
        writer.exec_driver_sql("BEGIN IMMEDIATE")
        writer.execute(text("INSERT INTO org (id, name) VALUES (9, 'Held')"))
        found = db_rows.page(ORG, engine=engine)
        assert _column(found, "name") == ["Acme", "Initech"]
        writer.rollback()


def test_a_tables_keys_out_and_in() -> None:
    """Each foreign key whole, a composite one too: from its columns to
    the ones it points at."""
    org_id = db_rows.Key("member", ("org_id",), "org", ("id",))
    both = db_rows.Key("note", ("post_id", "tag_id"), "tagged", ("post_id", "tag_id"))
    assert db_rows.keys(MEMBER) == ([org_id], [])
    assert db_rows.keys(ORG) == ([], [org_id])
    assert db_rows.keys(TAGGED) == ([], [both])
    assert db_rows.keys(NOTE) == ([both], [])


def test_a_row_follows_its_keys(engine: Engine) -> None:
    """Out to the row it points at; in to the rows pointing at it; each a
    table and the filter that finds them, which then finds them."""
    note = dict(zip(*_first(db_rows.page(NOTE, engine=engine))))
    (out,), _ = db_rows.keys(NOTE)
    assert db_rows.follow(out, note, out=True, metadata=META) == (
        "tagged",
        "post_id:2, tag_id:1",
    )
    found = db_rows.page(
        TAGGED, where=db_rows.parse_where("post_id:2, tag_id:1"), engine=engine
    )
    assert found.rows == [["2", "1"]]
    org = dict(zip(*_first(db_rows.page(ORG, engine=engine))))
    _, (into,) = db_rows.keys(ORG)
    assert db_rows.follow(into, org, out=False, metadata=META) == ("member", "org_id:3")


def test_a_key_into_its_own_table_leads_both_ways() -> None:
    """A tree: up to the parent, down to the children."""
    parent = db_rows.Key("tree", ("parent_id",), "tree", ("id",))
    assert db_rows.keys(TREE) == ([parent], [parent])
    row = {"id": "4", "parent_id": "2"}
    assert db_rows.follow(parent, row, out=True, metadata=META) == ("tree", "id:2")
    assert db_rows.follow(parent, row, out=False, metadata=META) == (
        "tree",
        "parent_id:4",
    )


def test_only_a_value_the_filter_can_ask_for_is_followed() -> None:
    """Not empty, hidden, cut or holding a comma, and only to columns the
    other table may be filtered by."""
    key = db_rows.Key("member", ("org_id",), "org", ("id",))
    for value in ("", "12…", db_rows.HIDDEN, "a,b"):
        assert db_rows.follow(key, {"org_id": value}, out=True, metadata=META) is None
    secret = db_rows.Key("org", ("name",), "member", ("hashed_password",))
    assert db_rows.follow(secret, {"name": "x"}, out=True, metadata=META) is None


def test_a_unique_constraint_serves_a_sort() -> None:
    assert "code" in db_rows.sortable(TREE)


def _first(found: db_rows.Rows) -> tuple[list[str], list[str]]:
    return found.columns, found.rows[0]
