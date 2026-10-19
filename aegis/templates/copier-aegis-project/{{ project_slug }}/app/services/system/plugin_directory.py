"""Plugins: the ones this stack has (``_plugins`` in ``.copier-answers.yml``,
as ``aegis add`` records them) and the ones it could add, from the public
directory at aegis-stack.io: the read-only listing ``aegis plugins search``
shows. Nothing is installed from here; adding one is ``pip install`` then
``aegis add``, in the project."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.ontology.parts import answers
from app.core.time import utcnow
from app.services.system.node_now import FIGURES

# The directory's published contract (aegis's ``plugins.registry``).
SITE_URL = "https://aegis-stack.io"
DIRECTORY_URL = f"{SITE_URL}/api/v1/plugins"
# She waits on it, mid-call too: a site that is down says so in seconds,
# and one waking from idle gets a second ask (``_get``).
TIMEOUT = httpx.Timeout(8.0, connect=3.0)


class InstalledPlugin(BaseModel):
    """A plugin this stack has: its version and the options it was added
    with."""

    model_config = FIGURES

    name: str  # what ``aegis add`` took
    version: str
    verified: bool
    options: dict[str, Any] = {}


class ListedPlugin(BaseModel):
    """Everything the directory says of a plugin, as it names it, and
    whether this stack has it; a field it adds later is kept in ``more``."""

    model_config = FIGURES

    name: str  # its PyPI distribution, what ``pip install`` takes
    install_name: str  # what ``aegis add`` takes
    install_command: str | None = None
    summary: str | None = None
    description: str | None = None
    latest_version: str | None = None
    latest_release_at: str | None = None
    verified: bool | None = None
    verified_note: str | None = None
    aegis_version: str | None = None  # the aegis it needs
    downloads: int | None = None
    human_downloads_30d: int | None = None
    stars: int | None = None  # its repository's
    repository_url: str | None = None
    pypi_url: str | None = None
    index_label: str | None = None
    detail_url: str | None = None
    pulse_url: str | None = None
    entry_point: str | None = None
    installed: bool
    add: str  # the commands that add it
    more: dict[str, Any] = {}


class PluginsAnswer(BaseModel):
    model_config = FIGURES

    installed: tuple[InstalledPlugin, ...]
    directory: tuple[ListedPlugin, ...]  # the first ``limit``
    directory_total: int  # all it lists for the search
    note: str | None  # why the directory could not be read, when not
    read_at: datetime


# The directory's own fields; anything else it sends goes in ``more``.
_LISTED = frozenset(ListedPlugin.model_fields) - {"installed", "add", "more"}


def installed(given: Mapping[str, Any]) -> tuple[InstalledPlugin, ...]:
    """The plugins ``given`` (a stack's answers) records; an old string
    entry says too little to list."""
    return tuple(
        InstalledPlugin(
            name=str(entry["name"]),
            version=str(entry.get("version") or ""),
            verified=bool(entry.get("verified")),
            options=dict(entry.get("options") or {}),
        )
        for entry in given.get("_plugins") or []
        if isinstance(entry, dict) and entry.get("name")
    )


async def listed(
    keyword: str | None,
    have: set[str],
    client: httpx.AsyncClient,
    limit: int | None = None,
) -> tuple[tuple[ListedPlugin, ...], int, str | None]:
    """The directory's plugins matching ``keyword`` (a name or summary),
    the first ``limit``, each marked if ``have`` names it, and how many
    there are; or none, and why."""
    try:
        response = await _get(client, {"q": keyword} if keyword else None)
        response.raise_for_status()
        rows = response.json()["plugins"]
        found = tuple(_listing(row, have) for row in rows[:limit])
        return found, len(rows), None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        said = f"{type(exc).__name__}: {exc}"
        return (), 0, f"The plugin directory at {SITE_URL} could not be read: {said}"


async def _get(
    client: httpx.AsyncClient, params: dict[str, str] | None
) -> httpx.Response:
    """The directory's answer, asked twice on a timeout: its first answer
    after a quiet spell can stall while the site wakes."""
    try:
        return await client.get(DIRECTORY_URL, params=params)
    except httpx.TimeoutException:
        return await client.get(DIRECTORY_URL, params=params)


def _listing(row: Mapping[str, Any], have: set[str]) -> ListedPlugin:
    fields = {k: v for k, v in row.items() if k in _LISTED}
    detail = row.get("detail_url") or ""
    if detail.startswith("/"):
        fields["detail_url"] = f"{SITE_URL}{detail}"
    install_name = str(row["install_name"])
    command = str(row.get("install_command") or f"aegis add {install_name}")
    return ListedPlugin(
        **fields,
        installed=install_name in have,
        add=f"pip install {row['name']} && {command}",
        more={k: v for k, v in row.items() if k not in _LISTED},
    )


async def plugins_now(keyword: str | None = None, limit: int = 100) -> PluginsAnswer:
    """This stack's plugins, and the directory's first ``limit``, read now."""
    have = installed(answers())
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        found, total, note = await listed(
            keyword, {p.name for p in have}, client, limit
        )
    return PluginsAnswer(
        installed=have,
        directory=found,
        directory_total=total,
        note=note,
        read_at=utcnow(),
    )
