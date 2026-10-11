"""The project's source as one index (``source_index``): each file parsed
once per change, whoever reads it, with what it imports and the component
a core client fronts, read without importing it."""

from collections import Counter
from pathlib import Path

import pytest

from app.core import source_index
from app.services.system import service_links, service_patterns
from tests._files import write_tree

FILES = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/core/cache.py": "from app.core.constants import ComponentName\n"
    "FRONTS = ComponentName.CACHE\n",
    "app/core/storage.py": 'FRONTS = "storage"\n',
    "app/services/notes/__init__.py": "",
    "app/services/notes/store.py": (
        "from typing import TYPE_CHECKING\n"
        "from app.core import cache\n"
        "from . import helpers\n"
        "from ..other.api import call\n"
        "if TYPE_CHECKING:\n"
        "    from app.components.worker.pools import enqueue\n"
        "async def save(session):\n"
        "    import app.services.blog.models\n"
        "    return session\n"
    ),
    "app/services/notes/helpers.py": "",
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write_tree(tmp_path, FILES)
    return tmp_path


def test_a_module_lists_every_module_it_imports(project: Path) -> None:
    """Relative ones resolved, lazy and ``TYPE_CHECKING`` ones too, and a
    module imported from its package (``from app.core import cache``) by
    its own name."""
    found = source_index.at(project).get("app.services.notes.store")
    assert found is not None
    assert {
        "typing",
        "app.core.cache",
        "app.services.notes.helpers",
        "app.services.other.api",
        "app.components.worker.pools",
        "app.services.blog.models",
    } <= found.imports


def test_a_core_client_says_what_it_fronts_unimported(project: Path) -> None:
    index = source_index.at(project)
    assert index.get("app.core.cache").fronts == "cache"
    assert index.get("app.core.storage").fronts == "storage"
    assert index.get("app.services.notes.store").fronts is None


def test_each_file_is_parsed_once_whoever_reads_it(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Server map's links, the load costs' imports, Code's lookups and
    the Service pattern, asked twice: each file is parsed once."""
    parsed: list[str] = []
    parse = source_index.ast.parse

    def counted(source: str, *args: object, **kwargs: object) -> object:
        parsed.append(source)
        return parse(source, *args, **kwargs)

    monkeypatch.setattr(source_index.ast, "parse", counted)
    monkeypatch.setattr(service_patterns, "PROJECT_ROOT", project)
    notes = project / "app" / "services" / "notes"
    for _ in range(2):
        index = source_index.at(project)
        service_links.talks_to(notes, (), index)
        index.imports_under("app.services.notes")
        index.get("app.core.cache")
        service_patterns.services()
    # The project's own core clients may be read too (what a module's
    # ``FRONTS`` says): only this tree's files are counted.
    mine = set(FILES.values())
    assert Counter(p for p in parsed if p in mine) == Counter(
        FILES[name]
        for name in (
            "app/core/cache.py",
            "app/services/notes/__init__.py",
            "app/services/notes/store.py",
            "app/services/notes/helpers.py",
        )
    )
