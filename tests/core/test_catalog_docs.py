"""The README's and the docs' component and service tables are rendered
from the specs (``aegis.core.catalog_docs``), so a part added, renamed or
described anew shows everywhere at once. A hand edit inside a table's
markers, or a spec the tables do not list, fails here."""

from pathlib import Path

import pytest

from aegis.core import catalog_docs
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", catalog_docs.FILES)
def test_every_table_is_what_the_specs_say(path: Path) -> None:
    text = path.read_text()
    assert text == catalog_docs.rendered(text), f"{path} is stale: run `make readme`"


@pytest.mark.parametrize("path", catalog_docs.FILES)
def test_every_file_carries_a_table(path: Path) -> None:
    text = path.read_text()
    assert any(catalog_docs.start(kind) in text for kind in catalog_docs.KINDS), path


@pytest.mark.parametrize(
    ("kind", "specs"), [("components", COMPONENTS), ("services", SERVICES)]
)
def test_every_spec_has_a_row(kind: str, specs: dict) -> None:
    table = catalog_docs.table(kind)
    for spec in specs.values():
        assert f"**[{catalog_docs.title(spec)}]" in table, spec.name
        assert spec.description in table, spec.name


def test_an_edit_inside_a_table_is_undone() -> None:
    marked = f"{catalog_docs.start('services')}\n| a hand edit |\n{catalog_docs.end('services')}"
    assert "a hand edit" not in catalog_docs.rendered(marked)
    assert catalog_docs.table("services") in catalog_docs.rendered(marked)


def test_an_empty_table_is_filled() -> None:
    marked = f"{catalog_docs.start('components')}\n{catalog_docs.end('components')}"
    assert catalog_docs.table("components") in catalog_docs.rendered(marked)


def test_the_dead_docs_index_is_gone() -> None:
    """``scripts/gen_docs.py`` writes the docs index from the README; a file
    on disk under that name is shadowed and never published."""
    assert not (ROOT / "docs" / "index.md").exists()
