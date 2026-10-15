"""A table's rows as Overseer pages through them (``db_rows``): only a table
the app's models declare, a page at a time, the default order paged by its
key rather than by offset, sorted and filtered only where an index serves
it, what holds a secret never read, and read without taking SQLite's write
lock or running past its time."""

from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    text,
)

from app.core import exposure, model_registry
from app.services.system import db_filters, db_rows
from tests.services._db_fixtures import (
    EVENT,
    LEDGER,
    MEMBER,
    META,
    NOTE,
    ORG,
    SLUG,
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
        db_rows.page(MEMBER, where=[("hashed_password", ":", "x")], engine=engine)


def test_a_long_cell_is_redacted_then_cut(engine: Engine) -> None:
    bio = _column(db_rows.page(MEMBER, engine=engine), "bio")[0]
    assert "s3cret" not in bio and bio.endswith("…")
    assert len(bio) <= db_rows.CELL + 1


def test_binary_shows_its_size(engine: Engine) -> None:
    avatar = _column(db_rows.page(MEMBER, engine=engine), "avatar")[0]
    assert avatar == "binary, 16 bytes"


def test_any_column_filters_but_a_secret_or_binary(engine: Engine) -> None:
    """Unindexed too (a scan, which ``SECONDS`` stops); never a secret (its
    values told apart unshown) or bytes (nothing to type)."""
    org = db_rows.page(MEMBER, where=[("org_id", ":", "3")], engine=engine)
    assert org.rows and set(_column(org, "org_id")) == {"3"}
    tokens = db_rows.page(MEMBER, where=[("input_tokens", ":", "10")], engine=engine)
    assert _column(tokens, "input_tokens") == ["10"]
    with pytest.raises(ValueError):
        db_rows.page(MEMBER, where=[("avatar", ":", "x")], engine=engine)
    with pytest.raises(ValueError):
        db_rows.page(MEMBER, where=[("nope", ":", "x")], engine=engine)
    assert "avatar" not in db_rows.filterable(MEMBER)
    more = db_rows.page(MEMBER, where=[("input_tokens", ">=", "20")], engine=engine)
    assert more.rows and all(int(n) >= 20 for n in _column(more, "input_tokens"))


def test_a_flag_filters_as_a_flag(engine: Engine) -> None:
    """``false`` is false (``bool("false")`` is not)."""
    off = db_rows.page(MEMBER, where=[("active", ":", "false")], engine=engine)
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
        TAGGED, where=db_filters.parse_where("post_id:2, tag_id:1"), engine=engine
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


def test_a_value_is_read_as_its_columns_kind(engine: Engine) -> None:
    """A date as the page shows it, money; one not of the kind says so (a
    raw string compared as text would match nothing, or fail in the driver)."""
    on = db_rows.page(LEDGER, where=[("at", ":", "2024-01-02 10:00:00")], engine=engine)
    assert _column(on, "id") == ["2"]
    since = db_rows.page(LEDGER, where=[("at", ">=", "2024-01-02")], engine=engine)
    assert _column(since, "id") == ["2", "3"]
    rich = db_rows.page(LEDGER, where=[("amount", ">", "20")], engine=engine)
    assert _column(rich, "id") == ["2", "3"]
    for name, wrong in (("amount", "abc"), ("at", "soon"), ("id", "x")):
        with pytest.raises(db_filters.AskError):
            db_rows.page(LEDGER, where=[(name, ":", wrong)], engine=engine)


def test_json_is_not_filtered_and_text_is_only_matched(engine: Engine) -> None:
    """JSON has no equality on PostgreSQL; ordering text would spell out what
    the page hides, a character at a time (``redact``, the cut)."""
    assert "meta" not in db_rows.filterable(LEDGER)
    db_rows.page(MEMBER, where=[("bio", "!=", "x")], engine=engine)
    with pytest.raises(db_filters.AskError):
        db_rows.page(MEMBER, where=[("bio", ">=", "post")], engine=engine)


def test_a_flag_is_matched_true_or_false(engine: Engine) -> None:
    """Ordered, a flag means nothing (and SQLAlchemy refuses it); a value
    neither true nor false is not one."""
    for op, value in ((">", "true"), (":", "nope")):
        with pytest.raises(db_filters.AskError):
            db_rows.page(MEMBER, where=[("active", op, value)], engine=engine)


def test_pages_by_a_column_with_ties_break_them_by_key(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many rows share an org: without the key after it, PostgreSQL may
    order the ties differently each page, repeating rows and losing others."""
    read = db_rows._read
    asked: list[str] = []

    def spy(*args: object) -> object:
        asked.append(str(args[2]))
        return read(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(db_rows, "_read", spy)
    monkeypatch.setattr(MEMBER.c.org_id, "index", True)  # sortable, with ties
    db_rows.page(MEMBER, order="org_id", desc=True, engine=engine)
    assert "ORDER BY member.org_id DESC, member.id DESC" in asked[0]


def test_not_equal_keeps_a_row_holding_nothing_there(engine: Engine) -> None:
    """NULL is not 3 either; SQL's ``!=`` would drop it unsaid."""
    with engine.begin() as conn:
        conn.execute(insert(MEMBER).values(id=99, email="none@x.io", org_id=None))
    found = db_rows.page(
        MEMBER, where=[("org_id", "!=", "3")], desc=True, engine=engine
    )
    assert _column(found, "id")[0] == "99"


def test_a_text_key_pages_by_offset(engine: Engine) -> None:
    """Paging from a text key would order text, and carry its values whole
    in the page links, past what the cells redact."""
    found = db_rows.page(SLUG, engine=engine)
    assert found.key is None and found.next == {"page": "2"}


def test_a_table_the_database_lacks_says_so(tmp_path: Path) -> None:
    """Not migrated yet: the health check lists none, so the models' tables
    are offered."""
    empty = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with pytest.raises(db_rows.RowsUnreadError, match="member"):
        db_rows.page(MEMBER, engine=empty)


def test_a_column_marked_or_named_as_a_secret_is_hidden() -> None:
    """A model marks one (``info={"secret": True}``, any type); the names
    the redaction words miss are caught as whole parts of a name."""
    vault = Table(
        "vault",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("pin", Integer, info={"secret": True}),
        Column("private_key", String),
        Column("signing_key", String),
        Column("otp", String),
        Column("totp_seed", String),
        Column("recovery_codes", String),
        Column("salt", String),
        Column("footprint", String),
        Column("cache_key", String),
    )
    assert db_rows.masked(vault) == {
        "pin",
        "private_key",
        "signing_key",
        "otp",
        "totp_seed",
        "recovery_codes",
        "salt",
    }
