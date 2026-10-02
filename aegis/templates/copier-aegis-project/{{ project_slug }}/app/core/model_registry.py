"""Import every module that defines a table, so ``SQLModel.metadata`` is complete.

Anything that reasons about the whole schema - alembic's ``env.py``,
``migrate-fix``, the startup re-adoption check, the test suite's
``create_all`` - needs every table registered first. Registration is a side
effect of importing the module that defines the class, so this walks the
places tables live and imports them:

- ``app/models/`` (core tables: users, orgs, conversations)
- ``app/services/<service>/models`` - a package or a single module
- ``app/components/<component>/models`` - a component's own tables (the
  secrets component's ``secret``)

A plugin or a hand-written service that keeps its tables there is picked up
without touching anything else. A table defined anywhere else is invisible,
and the generated test ``tests/test_model_registry.py`` fails the build.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import pkgutil
from types import ModuleType


def _import_tree(module: ModuleType) -> list[str]:
    """Import ``module`` and, if it is a package, every module beneath it."""
    names = [module.__name__]
    if hasattr(module, "__path__"):
        for info in pkgutil.walk_packages(module.__path__, f"{module.__name__}."):
            importlib.import_module(info.name)
            names.append(info.name)
    return names


def import_all_models() -> list[str]:
    """Import every table-defining module. Returns the module names, in order."""
    import app.models as core_models
    import app.services as services

    imported = _import_tree(core_models)
    for service in pkgutil.iter_modules(services.__path__):
        # Only packages can hold a ``models`` submodule; a plain module under
        # app/services (load_test_models.py, say) is not a service.
        if not service.ispkg:
            continue
        name = f"app.services.{service.name}.models"
        try:
            found = importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:
            found = False
        if found:
            imported.extend(_import_tree(importlib.import_module(name)))
    imported.extend(_component_models())
    return imported


def _component_models() -> list[str]:
    """Each component's ``models`` module or package, found on disk first:
    ``find_spec`` would import every component package to look (the Flet
    frontend, the worker's broker), and those imports have effects."""
    import app.components as components

    root = Path(components.__path__[0])
    imported: list[str] = []
    for component in pkgutil.iter_modules(components.__path__):
        here = root / component.name
        if component.ispkg and (
            (here / "models.py").exists() or (here / "models" / "__init__.py").exists()
        ):
            name = f"app.components.{component.name}.models"
            imported.extend(_import_tree(importlib.import_module(name)))
    return imported
