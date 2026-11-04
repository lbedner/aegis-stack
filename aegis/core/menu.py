"""The generator's menu as data: every component and service ``aegis init``
offers, what its brackets take, and what it requires, recommends and
conflicts with.

``aegis menu`` prints it as JSON, each release publishes it
(``menu.json``), and ``aegis components``/``aegis services`` list it for a
person, so the three never differ. What a selection of it builds, or the
rule that blocks it, is ``aegis.core.selection``.
"""

from typing import Any

from .. import __version__
from .components import COMPONENTS
from .option_spec import OptionSpec
from .plugins.spec import PluginSpec
from .selection import typed_options
from .services import SERVICES


def _option(option: OptionSpec) -> dict[str, Any]:
    return {
        "name": option.name,
        "mode": option.mode.value,
        "choices": list(option.choices),
        "default": option.default,
    }


def entry(spec: PluginSpec) -> dict[str, Any]:
    """One part of the menu. ``group`` is a component's type (``core`` is
    in every project) or a service's category."""
    return {
        "name": spec.name,
        "title": spec.display_title,
        "group": spec.type.value if spec.type else spec.category.value,
        "description": spec.description,
        "experimental": spec.experimental,
        "requires": list(spec.required_components),
        "recommends": list(spec.recommended_components),
        "requires_services": list(spec.required_services),
        "conflicts": list(spec.conflicts),
        "options": [_option(o) for o in typed_options(spec)],
        "docs": spec.docs_url,
    }


def menu() -> dict[str, Any]:
    """The whole menu, for the version that offers it."""
    return {
        "version": __version__,
        "components": [entry(spec) for spec in COMPONENTS.values()],
        "services": [entry(spec) for spec in SERVICES.values()],
    }
