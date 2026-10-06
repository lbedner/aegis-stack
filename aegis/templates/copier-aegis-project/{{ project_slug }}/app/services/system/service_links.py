"""What each service talks to, read from what is already there rather than
kept in a table: its imports name the components it uses (a component's
package, or a core client that says which component it fronts with
``FRONTS``) and the services it calls; the secrets it declares
(``app.core.secrets``), the ones what is enabled reads, name the outside
providers it calls. What Overseer's Server map draws. No UI framework
imports.
"""

import ast
from collections.abc import Iterable
from functools import cache
from importlib import import_module
from pathlib import Path
import pkgutil
import re
from types import ModuleType

from app.core import secrets
from app.core.secrets import Secret
import app.services
from app.services.system import topology
from app.services.system.ui import get_component_title, registry_key

# What every service imports to be one (its health check, shared models):
# plumbing, not something it talks to.
PLUMBING = frozenset({"system", "shared"})
OUTSIDE = "outside:"  # an outside provider's key, before its name
_BRACKETED = re.compile(r"\(([^)]+)\)")


@cache
def links() -> dict[str, list[str]]:
    """``{service's registry key: [what it talks to]}`` for every installed
    service: a component's name, another service's registry key, or an
    outside provider's ``outside:<name>``. Read once: it is the code."""
    root = Path(app.services.__file__).parent
    declared = secrets.declared()
    return {
        registry_key("services", name): talks_to(root / name, declared)
        for name in packages(app.services)
        if name not in PLUMBING
    }


def packages(parent: ModuleType) -> list[str]:
    """The packages directly in ``parent`` (``app.services``), by name: the
    services, or the components."""
    return sorted(m.name for m in pkgutil.iter_modules(parent.__path__) if m.ispkg)


def talks_to(package: Path, declared: Iterable[Secret]) -> list[str]:
    """What the service whose package is at ``package`` talks to, sorted."""
    service = package.name
    found = {t for name in imports(package) if (t := _target(name, service))}
    found |= {key for key, _ in _called_with(declared, service)}
    return sorted(found)


@cache
def provider_keys() -> dict[str, list[str]]:
    """``{outside provider's key: the needed secrets it is called with}``
    across every service: what the map checks are set."""
    found: dict[str, list[str]] = {}
    for key, name in _called_with(secrets.declared()):
        found.setdefault(key, []).append(name)
    return found


def _called_with(
    declared: Iterable[Secret], service: str | None = None
) -> list[tuple[str, str]]:
    """``(outside provider's key, secret)`` for each secret ``service``
    (any service, given none) declares that what is enabled needs."""
    return [
        (OUTSIDE + _provider(entry, owner), entry.name)
        for entry in declared
        if (owner := _service_of(entry.module))
        and owner == (service or owner)
        and entry.is_needed()
    ]


def title(key: str) -> str:
    """A target's name: an outside provider's own, else the registry's."""
    if key.startswith(OUTSIDE):
        return key.removeprefix(OUTSIDE)
    return get_component_title(key)


def imports(package: Path) -> set[str]:
    """Every absolute module the package's code imports, read, not run."""
    found: set[str] = set()
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module)
    return found


def _target(module: str, service: str) -> str | None:
    """What importing ``module`` says the service talks to, if anything."""
    parts = module.split(".")
    if parts[:2] == ["app", "components"] and len(parts) > 2:
        # Not the server's own package: the service runs inside it.
        if parts[2] == topology.HOST:
            return None
        return topology.THROUGH.get(parts[2], parts[2])
    if parts[:2] == ["app", "services"] and len(parts) > 2:
        other = parts[2]
        if other != service and other not in PLUMBING:
            return registry_key("services", other)
        return None
    if parts[:2] == ["app", "core"] and len(parts) > 2:
        return _fronts(".".join(parts[:3]))
    return None


def _fronts(module: str) -> str | None:
    """The component a core client says it fronts (its ``FRONTS``)."""
    try:
        return getattr(import_module(module), "FRONTS", None)
    except ImportError:
        return None


def within(module: str, package: str) -> bool:
    """Whether ``module`` is ``package`` or in it."""
    return module == package or module.startswith(f"{package}.")


def _service_of(module: str) -> str | None:
    """The service whose package ``module`` is in, if any."""
    parts = module.split(".")
    return parts[2] if len(parts) > 2 and parts[:2] == ["app", "services"] else None


def _provider(entry: Secret, service: str) -> str:
    """The provider a secret is for: the one its owner names in brackets
    (``Payment (Stripe)``), the owner itself (``Twilio``), or, where the
    owner is the service, its label's (``OpenAI API key``)."""
    bracketed = _BRACKETED.search(entry.owner)
    if bracketed:
        return bracketed.group(1)
    if entry.owner.lower() != service.replace("_", " "):
        return entry.owner
    return entry.label.removesuffix(" API key")
