"""Blueprint registry, discovered from this package.

One module per blueprint, each exporting a ``BLUEPRINT``. Adding a preset is
adding a file: nothing here (and no call site) needs editing, which is what
keeps a roster of dozens maintainable.

Discovery is import-time and eager. The set is small, every module is pure
data, and both the gallery and ``aegis blueprints`` need the whole roster
anyway, so laziness would buy nothing.
"""

from __future__ import annotations

import importlib
import pkgutil

from .spec import Blueprint, blueprint_selection

_EXPORT = "BLUEPRINT"


def _discover() -> dict[str, Blueprint]:
    """Every ``BLUEPRINT`` in this package, keyed by its own slug.

    Sorted by module name so listings and the gallery have a stable order
    regardless of filesystem iteration.
    """
    found: dict[str, Blueprint] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_") or info.name == "spec":
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        blueprint = getattr(module, _EXPORT, None)
        if blueprint is None:
            continue
        if not isinstance(blueprint, Blueprint):
            raise TypeError(
                f"{module.__name__}.{_EXPORT} must be a Blueprint, "
                f"got {type(blueprint).__name__}"
            )
        if blueprint.slug in found:
            raise ValueError(f"Duplicate blueprint slug: {blueprint.slug}")
        found[blueprint.slug] = blueprint
    return found


BLUEPRINTS: dict[str, Blueprint] = _discover()


def get_blueprint(slug: str) -> Blueprint | None:
    """The registered blueprint for ``slug``, or None."""
    return BLUEPRINTS.get(slug)


__all__ = ["BLUEPRINTS", "Blueprint", "blueprint_selection", "get_blueprint"]
