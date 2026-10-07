"""The sources research knows how to read: what a plugin registers.

A source says how to reach one site: ``search`` runs a watch's query and
``thread`` reads one item with everything under it. ``query`` checks a
watch's query before it is saved and ``data`` the extras an item carries
beyond the columns every source shares. Storing, refreshing and reading the
items is the research service's.

A plugin registers its source in its own ``app/services/<service>/
sources.py``; the registry imports every such module on disk
(``app.core.discovery``) the first time a source is asked for, so nothing
else lists it.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.discovery import import_modules_named
from app.core.time import as_stored
from app.services.research.models import ResearchNumbers


class SourceItem(ResearchNumbers):
    """One item as a source returns it, before it is stored."""

    model_config = ConfigDict(extra="forbid")

    external_id: str
    # story, comment, post, page: what the source calls it.
    kind: str
    # In a thread: the item it answers, and the top of its thread (a search
    # hit can be a reply; its thread is read from the top).
    parent_external_id: str | None = None
    root_external_id: str | None = None
    title: str | None = None
    url: str | None = None
    text: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("published_at")
    @classmethod
    def _stored(cls, value: datetime | None) -> datetime | None:
        """Naive UTC, as every timestamp column stores it: a source may hand
        over an aware time, which Postgres refuses for those columns."""
        return as_stored(value) if value else None


class NoData(BaseModel):
    """A source whose items carry nothing beyond the shared columns."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Source:
    name: str
    title: str
    query: type[BaseModel]
    search: Callable[[Any], Awaitable[list[SourceItem]]]
    thread: Callable[[str], Awaitable[list[SourceItem]]]
    data: type[BaseModel] = NoData


class UnknownSourceError(Exception):
    pass


_SOURCES: dict[str, Source] = {}


def register_source(source: Source) -> None:
    _SOURCES[source.name] = source


def unregister_source(name: str) -> None:
    _SOURCES.pop(name, None)


def load_sources() -> None:
    """Import every service's ``sources`` module, registering its sources."""
    import app.services as services

    import_modules_named(services, "sources")


def installed_sources() -> list[Source]:
    """Every installed source, by name."""
    load_sources()
    return [_SOURCES[name] for name in sorted(_SOURCES)]


def source_for(name: str) -> Source:
    """The source ``name``, loading the installed ones on a miss."""
    if name not in _SOURCES:
        load_sources()
    if name not in _SOURCES:
        raise UnknownSourceError(f"no research source named {name!r}")
    return _SOURCES[name]


def validated(
    model: type[BaseModel], value: dict[str, Any], what: str
) -> dict[str, Any]:
    """``value`` checked by a source's ``model`` (a watch's query, an item's
    extras), as it is stored; a refusal names what was wrong."""
    try:
        return model.model_validate(value).model_dump(mode="json")
    except ValidationError as e:
        raise ValueError(f"invalid {what}: {e}") from e
