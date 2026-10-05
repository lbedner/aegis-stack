"""Find a convention module in every service or component, on disk.

A service keeps its tables in ``models``, its change types in
``change_types``, its scheduled jobs in ``scheduled_jobs``; whoever needs all of
them asks here which exist. The answer comes from the filesystem, so no
package is imported just to see whether it has one (importing a component
package - the Flet frontend, the worker's broker - has effects). A plugin
or a hand-written service that follows a convention is picked up with no
edit anywhere else.
"""

import importlib
from pathlib import Path
import pkgutil
from types import ModuleType


def modules_named(package: ModuleType, name: str) -> list[str]:
    """``<package>.<child>.<name>`` for each child package that holds a
    ``name`` module or package, in name order."""
    found: list[str] = []
    for child in pkgutil.iter_modules(package.__path__):
        if not child.ispkg:
            continue
        here = Path(child.module_finder.path) / child.name  # type: ignore[union-attr]
        if (here / f"{name}.py").is_file() or (here / name / "__init__.py").is_file():
            found.append(f"{package.__name__}.{child.name}.{name}")
    return found


def import_modules_named(package: ModuleType, name: str) -> list[ModuleType]:
    """Import every ``modules_named(package, name)``, in name order: how a
    service's convention module registers what it declares."""
    return [importlib.import_module(found) for found in modules_named(package, name)]
