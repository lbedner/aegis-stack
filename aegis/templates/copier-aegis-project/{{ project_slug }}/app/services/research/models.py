"""Research tables: the saved searches, what they found, and which found
what.

An item is stored once per source, whoever's watch found it: outside posts
are public, and a refresh updates the one row. Its numbers are also kept a
day at a time (``ResearchItemSnapshot``), so a thread's rise outlives it. Watches are their owner's;
what an owner may read is ``ResearchService``'s rule.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class ResearchNumbers(SQLModel):
    """The numbers every source has, wherever an item's are held: as a source
    returns it, on its row, and day by day. Anything else is in ``data``."""

    score: int | None = None
    comment_count: int | None = None


class ResearchWatch(SQLModel, table=True):
    """A saved search on one source, refreshed on a schedule."""

    __tablename__ = "research_watch"
    __table_args__ = (Index("ix_research_watch_owner", "owner_user_id"),)

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    source: str = Field(max_length=32)
    name: str = Field(max_length=255)
    # The source's own query shape, validated by its ``query`` model.
    query: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("query", JSON, nullable=False)
    )
    # Read each found story's thread too (its comments), not just the story.
    with_threads: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    refreshed_at: datetime | None = None


class ResearchItem(ResearchNumbers, table=True):
    """One outside post, comment or page, from any source."""

    __tablename__ = "research_item"
    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", name="uq_research_item_source_external"
        ),
        Index("ix_research_item_root", "root_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(max_length=32)
    # The source's own id for it, so a refresh finds the row again.
    external_id: str = Field(max_length=128)
    kind: str = Field(max_length=32)
    parent_id: int | None = Field(default=None, foreign_key="research_item.id")
    # The top of its thread (itself for a story), so a thread is one read.
    root_id: int | None = Field(default=None, foreign_key="research_item.id")
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    text: str | None = None
    author: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None
    data: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("data", JSON, nullable=False)
    )
    fetched_at: datetime = Field(default_factory=utcnow)
    # Gone from the source (``refresh._mark_vanished``).
    deleted_at: datetime | None = None


class ResearchMatch(SQLModel, table=True):
    """Which watch found which item, and when it last did: an item that
    stops matching reads as a past find rather than vanishing."""

    __tablename__ = "research_match"
    __table_args__ = (Index("ix_research_match_item", "item_id"),)

    watch_id: int = Field(foreign_key="research_watch.id", primary_key=True)
    item_id: int = Field(foreign_key="research_item.id", primary_key=True)
    last_matched_at: datetime = Field(default_factory=utcnow)


class ResearchItemSnapshot(ResearchNumbers, table=True):
    """An item's numbers on one day, today's included. One per item per day:
    a later refresh that day replaces it. An item with no numbers has none."""

    __tablename__ = "research_item_snapshot"

    item_id: int = Field(foreign_key="research_item.id", primary_key=True)
    as_of: date = Field(primary_key=True)
