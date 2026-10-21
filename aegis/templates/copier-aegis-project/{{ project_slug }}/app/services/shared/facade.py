"""A service facade that costs nothing to import.

Callers outside a service reach it through its facade (the parts pattern's
through-facade rule). A facade composed of many modules (a ``service/``
package) would load the whole service for one name, so it offers what its
``if TYPE_CHECKING:`` block imports, each loaded the first time it is used.
That block is the one list: type checkers read it as the imports it is, and
``lazy`` reads it as the names to offer::

    if TYPE_CHECKING:
        from app.services.ai.domains.spend.recording import record_usage

    __getattr__, __all__ = facade.lazy(__name__, __file__)
"""

import ast
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any


def lazy(package: str, path: str) -> tuple[Callable[[str], Any], list[str]]:
    """``__getattr__`` and ``__all__`` for the facade ``package`` (its
    ``__init__`` at ``path``): each name its ``if TYPE_CHECKING:`` block
    imports, loaded from its module on first use. Read from that module
    every time, never kept on the facade, so a test that patches the
    module a name is defined in patches it for every caller."""
    offered = _offered(Path(path))

    def offer(name: str) -> Any:
        if name not in offered:
            raise AttributeError(f"module {package!r} has no attribute {name!r}")
        return _load(*offered[name])

    return offer, list(offered)


def _offered(path: Path) -> dict[str, tuple[str, str]]:
    """``{name: (module, member)}`` for each name the module's top-level
    ``if TYPE_CHECKING:`` blocks import, in their order."""
    tree = ast.parse(path.read_text())
    return {
        alias.asname or alias.name: (node.module, alias.name)
        for block in tree.body
        if isinstance(block, ast.If)
        and isinstance(block.test, ast.Name)
        and block.test.id == "TYPE_CHECKING"
        for node in block.body
        if isinstance(node, ast.ImportFrom) and node.module and not node.level
        for alias in node.names
    }


def _load(module: str, member: str) -> Any:
    """``member`` of ``module``: what it defines, or its submodule of that
    name (a package binds a submodule only once it is imported)."""
    found = import_module(module)
    try:
        return getattr(found, member)
    except AttributeError:
        return import_module(f"{module}.{member}")
