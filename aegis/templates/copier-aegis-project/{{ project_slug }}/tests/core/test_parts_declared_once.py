"""Each part's place is declared once, on its spec (``app.core.parts``):
the map's tiers, lines and shapes, the sidebar's order and the pages its
containers show on are read from there, never kept again beside the code
that draws them."""

import ast
import importlib.util
from pathlib import Path

import pytest

from app.core import source_index
from app.core.parts import PARTS
from app.core.source_index import ROOT

# Where those tables once were.
READERS = (
    "app.services.system.topology",
    "app.core.runtime",
    "app.components.web_frontend.overseer_nav",
)


def _file(module: str) -> Path:
    return ROOT / source_index.module_paths(module)[0]


def _literals(module: str) -> set[str]:
    tree = ast.parse(_file(module).read_text())
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


@pytest.mark.parametrize("module", READERS)
def test_no_part_is_named_where_the_parts_are_read(module: str) -> None:
    if not _file(module).is_file():
        pytest.skip(f"{module} is not in this stack")
    named = _literals(module) & set(PARTS)
    assert not named, f"{module} names {sorted(named)}: declare it on the spec"


def test_the_old_import_scan_is_gone() -> None:
    """The Server zoom's private import scan: its calls are the model's."""
    assert importlib.util.find_spec("app.services.system.service_links") is None
