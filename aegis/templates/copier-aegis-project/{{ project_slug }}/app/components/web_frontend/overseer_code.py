"""Overseer > Code: the project's source, read-only. A tree of its folders
and files, and one file open beside it (``?file=``, its path from the
project's root), numbered and highlighted, each line at its own address
(``#L-<n>``) for a traceback or a log line to link to.

The tree is the one rule for what is shown and served: never a hidden file
or folder (``.env``, ``.git``), one generated, installed or holding data, a
link, or a file that is not source. Outside dev it is off until an admin
turns it on (``OVERSEER_CODE_ENABLED``): the source is a map of the app."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
import html
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from markupsafe import Markup, escape

from app.core.config import settings
from app.services.system import source_index, ui_deployments, ui_runtime
from app.services.system.errors.fingerprint import FRAME
from app.services.system.models import ComponentStatus
from app.services.system.patterns import PROJECT_ROOT

from .overseer_nav import NavItem, SectionRequest
from .filters import LINE_ANCHOR
from .rendering import templates, with_query

SECTIONS = ((None, {"code": "Code"}),)
ITEM = NavItem(
    group="code",
    name="code",
    title="Code",
    url="/overseer/code",
    status="",
    component=ComponentStatus(name="code", message=""),
)
FILE = "file"  # the query parameter naming the open file
OWNER = "owner"  # ... scoping the tree to a component's or service's files
FOLDER = "folder"  # ... scoping it to a folder
PANE = "code-file"  # the element a click in the tree swaps
SYMBOL = "/partials/overseer/code/symbol"  # a clicked name, in a popover
VIEW = "code-view"  # the element a change of scope swaps: tree and file
# ponytail: source by suffix and folders skipped by name, not .gitignore;
# parse it if a gitignored source file ever needs hiding.
SOURCE_SUFFIXES = frozenset(
    {".py", ".html", ".jinja", ".js", ".css", ".md", ".toml", ".yml", ".yaml"}
    | {".sql", ".ini", ".cfg", ".txt", ".sh", ".mako"}
)
SOURCE_NAMES = frozenset({"Dockerfile", "Makefile"})
SKIPPED = frozenset({"__pycache__", "node_modules", "dist", "build", "data", "site"})
# A file larger than this is not source anyone reads here.
MAX_BYTES = 512 * 1024
# A frame in a traceback Pygments highlighted (``pytb``): its file, line.
# The file is escaped HTML (Python's own frames are ``&lt;frozen ...&gt;``).
HIGHLIGHTED_FRAME = re.compile(
    r'File <span class="nb">(?:"|&quot;)(.+?)(?:"|&quot;)</span>, '
    r'line <span class="m">(\d+)</span>'
)


@dataclass(frozen=True)
class Node:
    """A folder (its ``children``, never empty) or a file (none)."""

    name: str
    path: str  # from the project's root, with forward slashes
    children: tuple["Node", ...] = ()


@dataclass(frozen=True)
class Scope:
    """What the tree shows: a component's or service's files (``owner``),
    a folder's, or (neither) everything."""

    owner: str = ""
    folder: str = ""

    @classmethod
    def of(cls, query: Mapping[str, str]) -> "Scope":
        owner = query.get(OWNER, "")
        return cls(owner, "" if owner else query.get(FOLDER, "").strip("/"))

    def keeps(self, path: str) -> bool:
        if self.owner:
            return bool(_owned(self.owner).search(path))
        return path.startswith(self.folder + "/")

    def url(self, path: str, **change: str) -> str:
        """``path`` open, in this scope with ``change`` made to it."""
        return with_query(
            ITEM.url, **{FILE: path, OWNER: self.owner, FOLDER: self.folder, **change}
        )


@cache
def _owned(name: str) -> re.Pattern[str]:
    """A path naming ``name``, or the runtime page it shows on (the cache's
    is redis), as a whole word: ``auth/``, ``overseer_auth.py``."""
    words = sorted({name, ui_runtime.page_of(name) or name})
    return re.compile(
        r"(?:^|[/_.-])(?:" + "|".join(map(re.escape, words)) + r")(?:$|[/_.-])"
    )


def owners(navigation: Mapping[str, list[NavItem]]) -> list[tuple[str, str]]:
    """Every installed component and service, as a scope's choices."""
    entries = [*navigation["components"], *navigation["services"]]
    return [("", "All"), *((e.name, e.title) for e in entries)]


def line_url(path: str, line: int) -> str:
    """Where ``path`` opens at ``line``."""
    return f"{Scope().url(path)}#{LINE_ANCHOR}-{line}"


@dataclass(frozen=True)
class Frame:
    """A traceback's frame in the app's own code."""

    path: str
    line: int
    function: str


def local_path(frame_path: str) -> str | None:
    """A traceback frame's file as one of this project's the tree shows
    (from its root), or None: a library's, even one with an ``app`` folder
    of its own, and Python's own (``<frozen ...>``)."""
    root = f"{PROJECT_ROOT}/"
    path = frame_path.replace("\\", "/")
    return (
        path[len(root) :]
        if path.startswith(root) and shown(path[len(root) :])
        else None
    )


def own_frames(trace: str | None) -> list[Frame]:
    """The frames of ``trace`` in the app's own code (``local_path``),
    innermost (where it broke) first, each once; none while the page is
    off."""
    if not enabled():
        return []
    found = [
        Frame(path, int(frame["line"]), frame["function"].strip())
        for frame in FRAME.finditer(trace or "")
        if (path := local_path(frame["path"]))
    ]
    return list(dict.fromkeys(reversed(found)))


def code_frames(highlighted: str) -> Markup:
    """A highlighted traceback with each of the app's own frames
    (``local_path``) linked to its line here (while the page is on), and
    every other dimmed, so the app's stand out."""

    def mark(frame: re.Match[str]) -> str:
        path = local_path(html.unescape(frame[1]))
        if path is None:
            return f'<span class="library-frame">{frame[0]}</span>'
        if not enabled():
            return frame[0]
        url = escape(line_url(path, int(frame[2])))
        return f'<a href="{url}" class="code-frame">{frame[0]}</a>'

    return Markup(HIGHLIGHTED_FRAME.sub(mark, str(highlighted)))


templates.env.filters["code_frames"] = code_frames
templates.env.globals.update(
    own_frames=own_frames,
    line_url=line_url,
    code_owners=owners,
    # The page's fixed names, for its templates: no template spells them.
    code_page={
        "pane": PANE,
        "view": VIEW,
        "file": FILE,
        "owner": OWNER,
        "line": f"{LINE_ANCHOR}-",
    },
)


def enabled() -> bool:
    return settings.is_dev or settings.OVERSEER_CODE_ENABLED


def _source(name: str) -> bool:
    return PurePosixPath(name).suffix in SOURCE_SUFFIXES or name in SOURCE_NAMES


def _shown(entry: os.DirEntry[str]) -> bool:
    """Not hidden, not a link, and a folder not skipped or a source file."""
    if entry.name.startswith(".") or entry.is_symlink():
        return False
    return entry.name not in SKIPPED if entry.is_dir() else _source(entry.name)


def shown(path: str) -> bool:
    """Whether the tree shows ``path`` (from the project's root), checked
    on its own: a source file, nothing on the way to it hidden, skipped or
    a link. The one rule for what is listed, opened or linked to."""
    parts = PurePosixPath(path).parts
    if not parts or PurePosixPath(path).is_absolute() or not _source(parts[-1]):
        return False
    if any(p.startswith(".") for p in parts) or any(p in SKIPPED for p in parts[:-1]):
        return False
    steps = [PROJECT_ROOT.joinpath(*parts[: i + 1]) for i in range(len(parts))]
    return steps[-1].is_file() and not any(step.is_symlink() for step in steps)


def tree(folder: str = "") -> tuple[Node, ...]:
    """The folders (those with anything shown) then the files, by name;
    ``folder`` is a path from the project's root ("" for the root)."""
    with os.scandir(PROJECT_ROOT / folder) as found:
        entries = sorted(
            (e for e in found if _shown(e)),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        )
    nodes = []
    for entry in entries:
        path = f"{folder}/{entry.name}" if folder else entry.name
        if not entry.is_dir():
            nodes.append(Node(entry.name, path))
        elif children := tree(path):
            nodes.append(Node(entry.name, path, children))
    return tuple(nodes)


def files(nodes: tuple[Node, ...]) -> list[str]:
    """Every file's path in ``nodes``, at any depth, in the tree's order."""
    return [
        found
        for node in nodes
        for found in (files(node.children) if node.children else [node.path])
    ]


def version() -> str:
    """Which source this is: the live build's commit once a deploy stamped
    one, else the files as they are (dev's working tree)."""
    if live := ui_deployments.commit():
        return f"at {live}"
    if settings.BUILD_ID == ui_deployments.LOCAL:
        return "working tree"
    return f"build {settings.BUILD_ID}"


def pruned(nodes: tuple[Node, ...], keeps: Callable[[str], bool]) -> tuple[Node, ...]:
    """``nodes`` with only the files ``keeps``, and the folders holding one."""
    kept = []
    for node in nodes:
        if not node.children:
            if keeps(node.path):
                kept.append(node)
        elif children := pruned(node.children, keeps):
            kept.append(Node(node.name, node.path, children))
    return tuple(kept)


def spread(nodes: tuple[Node, ...]) -> tuple[int, int]:
    """How many files ``nodes`` hold, in how many folders."""
    paths = files(nodes)
    return len(paths), len({path.rpartition("/")[0] for path in paths})


def crumbs(path: str, scope: Scope) -> list[tuple[str, str]]:
    """Each folder ``path`` is in, with where it scopes the tree to it."""
    parts = path.split("/")[:-1]
    return [
        (part, scope.url(path, **{OWNER: "", FOLDER: "/".join(parts[: i + 1])}))
        for i, part in enumerate(parts)
    ]


def read(path: str) -> str | None:
    """The source at ``path``, or None unless it is a file the tree shows."""
    if not shown(path):
        return None
    found = PROJECT_ROOT / path
    try:
        if found.stat().st_size > MAX_BYTES:
            return None
        return found.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # gone, unreadable, or not text
        return None


def symbol_context(path: str, line: int, col: int) -> dict[str, Any]:
    """The name at ``line``:``col`` of ``path``: where it is defined and
    every line naming it, across the tree's Python files."""
    python = [p for p in files(tree()) if p.endswith(".py")]
    modules = source_index.Index(PROJECT_ROOT, python)
    found = source_index.symbol_at(modules, path, line, col) if shown(path) else None
    name, symbol = found or ("", None)
    return {
        "symbol_name": name,
        "symbol_definition": symbol and source_index.definition(modules, symbol),
        "symbol_references": source_index.references(modules, symbol) if symbol else [],
    }


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    path = req.query.get(FILE, "")
    scope = Scope.of(req.query)
    context = {
        "section_subtitle": "The project's source, read-only.",
        "code_scope": scope,
        "code_crumbs": crumbs(path, scope),
        # The open file in no scope: where the chips pick a new one.
        "code_unscoped": Scope().url(path),
        "code_path": path,
        "code_source": read(path) if path else None,
        "code_version": version(),
        "code_symbol": with_query(SYMBOL, **{FILE: path})
        if path.endswith(".py")
        else None,
        "code_nodes": None,
        "code_spread": None,
    }
    if req.target == PANE:  # a click in the tree: the file alone
        return context
    nodes = tree()
    listed = pruned(nodes, scope.keeps) if scope != Scope() else nodes
    return context | {
        "code_nodes": listed,
        "code_files": files(nodes),
        "code_spread": spread(listed) if listed is not nodes else None,
    }
