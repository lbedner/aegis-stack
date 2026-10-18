"""What each services folder's code talks to, read from what is already
there rather than kept in a table: its imports name the components it uses
(a component's package, or a core client that says which component it
fronts with ``FRONTS``) and the services it calls (``ownership``); the
secrets it declares (``app.core.secrets``), the ones what is enabled needs
now, name the outside providers it calls. Each target is a node's id.

The imports are the code, read once a build; the providers are read live,
so a provider switched in settings is the one drawn."""

from collections.abc import Iterable
from pathlib import Path
import re

from app.core import ownership, secrets, source_index
from app.core.ontology.model import Kind, node_id
from app.core.secrets import Secret

_BRACKETED = re.compile(r"\(([^)]+)\)")


def talks_to(
    package: Path, declared: Iterable[Secret], index: source_index.Index
) -> list[str]:
    """What the code of the services folder at ``package`` talks to, as
    node ids, sorted, read from ``index``."""
    module = source_index.module_name(package.relative_to(index.root).as_posix())
    found = set(reaches(module, index))
    found |= {node_id(Kind.EXTERNAL, p) for p, _ in providers(declared, package.name)}
    return sorted(found)


def reaches(module: str, index: source_index.Index) -> list[str]:
    """What the code of ``module`` (a job's) talks to, as node ids, sorted:
    the parts its imports belong to, its own services folder left out."""
    folder = _folder_of(module) or ""
    return sorted(
        {t for name in index.imports_under(module) if (t := _target(name, folder))}
    )


def providers(
    declared: Iterable[Secret], folder: str | None = None, *, needed: bool = True
) -> list[tuple[str, str]]:
    """``(outside provider, secret)`` for each secret the services folder
    ``folder`` (any, given none) declares that what is enabled needs now
    (each it declares at all, not ``needed``)."""
    return [
        (_provider(entry, owner), entry.name)
        for entry in declared
        if (owner := _folder_of(entry.module))
        and owner == (folder or owner)
        and (not needed or entry.is_needed())
    ]


def by_package(declared: Iterable[Secret]) -> dict[str, list[str]]:
    """``{package: the outside providers its needed keys are for}``: the
    package of the module declaring them, whose client beside it reads them.
    What code reaching that package calls (the dry path)."""
    found: dict[str, list[str]] = {}
    for entry in declared:
        package = entry.module.rpartition(".")[0]
        for provider, _ in providers([entry]):
            found.setdefault(package, []).append(provider)
    return {package: list(dict.fromkeys(names)) for package, names in found.items()}


def provider_keys() -> dict[str, list[str]]:
    """``{outside provider: the needed secrets it is called with}`` across
    every service, read now: what the map checks are set."""
    found: dict[str, list[str]] = {}
    for provider, name in providers(secrets.declared()):
        found.setdefault(provider, []).append(name)
    return found


def _target(module: str, folder: str) -> str | None:
    """What importing ``module`` says the folder's code talks to, if
    anything: the component or other service that owns it (a core client
    by what it fronts), as a node's id."""
    found = ownership.owner(module) if module.startswith("app.") else None
    if found is None or found.kind == ownership.SHARED:
        return None
    if found.kind == ownership.SERVICE:
        return None if found.name == folder else node_id(Kind.SERVICE, found.name)
    # Not the host's own package: the service runs inside it. A part that
    # takes work (the worker) is reached through what it takes from.
    if found.name == ownership.HOST:
        return None
    return node_id(Kind.COMPONENT, ownership.TAKES.get(found.name, found.name))


def _folder_of(module: str) -> str | None:
    """The services folder ``module`` is in, if any."""
    parts = module.split(".")
    return parts[2] if len(parts) > 2 and parts[:2] == ["app", "services"] else None


def _provider(entry: Secret, folder: str) -> str:
    """The provider a secret is for: the one its owner names in brackets
    (``Payment (Stripe)``), the owner itself (``Twilio``), or, where the
    owner is the service, its label's (``OpenAI API key``)."""
    bracketed = _BRACKETED.search(entry.owner)
    if bracketed:
        return bracketed.group(1)
    if entry.owner.lower() != folder.replace("_", " "):
        return entry.owner
    return entry.label.removesuffix(" API key")
