"""The tables the database browser's tests read (``db_rows``,
``db_query``), declared on their own metadata and seeded into a file
database: a member table with secrets, binary and an AutoString token; an
org it points at; an event with no key; a composite-key join, and a note
pointing at a join row by both its columns; a tree pointing at itself; a
ledger of dates, money and JSON; a table keyed by text; an account and the
one profile each has, deleted with it."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    insert,
)
from sqlmodel import AutoString

META = MetaData()
MEMBER = Table(
    "member",
    META,
    Column("id", Integer, primary_key=True),
    Column("email", String, unique=True),
    Column("hashed_password", String),
    Column("org_id", Integer, ForeignKey("org.id")),
    Column("bio", String),
    Column("input_tokens", Integer),
    Column("active", Boolean),
    Column("avatar", LargeBinary),
    Column("api_token", AutoString),  # how SQLModel types a str field
)
ORG = Table(
    "org", META, Column("id", Integer, primary_key=True), Column("name", String)
)
EVENT = Table("event", META, Column("kind", String), Column("at", Integer))  # no key
TAGGED = Table(
    "tagged",
    META,
    Column("post_id", Integer, primary_key=True),
    Column("tag_id", Integer, primary_key=True),
)
NOTE = Table(
    "note",
    META,
    Column("id", Integer, primary_key=True),
    Column("post_id", Integer),
    Column("tag_id", Integer),
    ForeignKeyConstraint(["post_id", "tag_id"], ["tagged.post_id", "tagged.tag_id"]),
)
TREE = Table(
    "tree",
    META,
    Column("id", Integer, primary_key=True),
    Column("parent_id", Integer, ForeignKey("tree.id")),
    Column("code", String),
    UniqueConstraint("code"),
)
LEDGER = Table(
    "ledger",
    META,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime),
    Column("amount", Numeric(10, 2)),
    Column("meta", JSON),
)
SLUG = Table("slug", META, Column("name", String, primary_key=True))
ACCOUNT = Table("account", META, Column("id", Integer, primary_key=True))
PROFILE = Table(
    "profile",
    META,
    Column(
        "account_id",
        Integer,
        ForeignKey("account.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


def seeded(tmp_path: Path) -> Engine:
    """A file database at ``tmp_path`` holding the tables, seeded."""
    found = create_engine(f"sqlite:///{tmp_path / 'rows.db'}")
    META.create_all(found)
    with found.begin() as conn:
        conn.execute(
            insert(ORG), [{"id": 3, "name": "Acme"}, {"id": 5, "name": "Initech"}]
        )
        conn.execute(
            insert(MEMBER),
            [
                {
                    "id": n,
                    "email": f"m{n:02}@x.io",
                    "hashed_password": "$2b$12$secret",
                    "org_id": 3 if n % 2 else 5,
                    "bio": "postgres://app:s3cret@db/app " + "x" * 500
                    if n == 1
                    else "short",
                    "input_tokens": n * 10,
                    "active": n % 3 == 0,
                    "avatar": b"\x89PNG" * 4,
                }
                for n in range(1, 61)
            ],
        )
        conn.execute(insert(EVENT), [{"kind": f"k{n}", "at": n} for n in range(30)])
        conn.execute(
            insert(TAGGED),
            [{"post_id": p, "tag_id": t} for p in (2, 1) for t in (2, 1)],
        )
        conn.execute(insert(NOTE), [{"id": 1, "post_id": 2, "tag_id": 1}])
        conn.execute(
            insert(LEDGER),
            [
                {
                    "id": n,
                    "at": datetime(2024, 1, n, 10),
                    "amount": Decimal(f"{n}0.50"),
                    "meta": {"n": n},
                }
                for n in (1, 2, 3)
            ],
        )
        conn.execute(insert(SLUG), [{"name": f"s{n:02}"} for n in range(30)])
    return found
