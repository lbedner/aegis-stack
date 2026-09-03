"""Module boundaries inside the documents service.

Behavioural tests cannot see a layout: extraction works the same whether
it lives in one flat package or in a domain of its own, so a later change
that drops a new function into whichever file was open passes the whole
suite. These assertions are the only place the split is stated.

The claim: the package root is the service's spine (its facade, its
tables, its reads, its wiring), and reading a document is a domain -
render a page, try its text layer, hand it to a model, decide where the
work runs, narrate progress.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

SPINE = {"service.py", "models.py", "queries.py", "health.py", "deps.py"}

# Public callable -> the module that must DEFINE it.
OWNERS = {
    "app.services.documents.service": ["DocumentService", "ProtectedDocumentError"],
    "app.services.documents.domains.extraction.pages": [
        "extract_document",
        "VisionReader",
    ],
    "app.services.documents.domains.extraction.pdf": ["PdfPages", "encode_png"],
    "app.services.documents.domains.extraction.dispatch": [
        "start_extraction",
        "start_extraction_in_process",
    ],
    "app.services.documents.domains.extraction.jobs": [
        "run_extraction",
        "run_extraction_job",
    ],
}


def _package_root() -> Path:
    return Path(importlib.import_module("app.services.documents").__file__).parent


def test_the_root_is_the_spine_and_nothing_else() -> None:
    """Anything that is not the spine is a domain, not a root module."""
    root = _package_root()
    modules = {
        f.name for f in root.glob("*.py") if f.name not in {"__init__.py"}
    }

    assert SPINE <= modules, f"the spine is incomplete: {sorted(SPINE - modules)}"
    assert not modules - SPINE, (
        f"these belong in a domain package, not at the root: {sorted(modules - SPINE)}"
    )


def test_extraction_is_a_domain() -> None:
    root = _package_root()
    extraction = root / "domains" / "extraction"

    assert extraction.is_dir(), "extraction is not a domain package"
    assert {f.name for f in extraction.glob("*.py")} >= {
        "__init__.py",
        "pages.py",
        "pdf.py",
        "vision.py",
        "dispatch.py",
        "jobs.py",
    }


def _defines(module_name: str, name: str) -> bool:
    """Whether the module's own source binds ``name`` at top level.

    Read from the source rather than from ``__module__``: a type alias is
    a plain assignment, so ``VisionReader.__module__`` says
    ``collections.abc`` no matter which file wrote it down.
    """
    source = Path(importlib.import_module(module_name).__file__).read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if node.name == name:
                return True
        elif isinstance(node, ast.Assign):
            if any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            ):
                return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return True
    return False


@pytest.mark.parametrize(("module_name", "names"), sorted(OWNERS.items()))
def test_each_module_defines_what_it_claims(module_name: str, names: list[str]) -> None:
    module = importlib.import_module(module_name)

    for name in names:
        assert getattr(module, name, None) is not None, (
            f"{module_name} does not export {name}"
        )
        assert _defines(module_name, name), (
            f"{name} is imported into {module_name}, not defined there"
        )
