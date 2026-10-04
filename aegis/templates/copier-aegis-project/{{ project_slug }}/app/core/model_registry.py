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

Both are found on disk through ``app.core.discovery``. A table defined
anywhere else is invisible,
and the generated test ``tests/test_model_registry.py`` fails the build.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from app.core.discovery import modules_named


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
    import app.components as components
    import app.models as core_models
    import app.services as services

    imported = _import_tree(core_models)
    for name in [
        *modules_named(services, "models"),
        *modules_named(components, "models"),
    ]:
        imported.extend(_import_tree(importlib.import_module(name)))
    return imported
