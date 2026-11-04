"""
What ``aegis init`` accepts: a selection checked and resolved into the
stack it builds, or the rules that block it.

``init``'s ``--components``/``--services`` callbacks and ``aegis menu``
run these same checks, so a selection the menu accepts is one ``init``
builds, and one it refuses ``init`` refuses for the same rule.
"""

import functools
import re
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import ParamSpec, TypeVar

from ..constants import ComponentNames, Messages, PostgresProviders, StorageBackends
from ..i18n import t
from .component_utils import (
    clean_component_names,
    extract_base_component_name,
    extract_base_service_name,
    restore_engine_info,
    split_bracket_list,
)
from .components import COMPONENTS, CORE_COMPONENTS
from .dependency_resolver import DependencyResolver
from .option_spec import OptionSpec, compute_auto_requires, parse_options
from .parts import OLDER_AXES
from .plugins.spec import PluginSpec
from .service_resolver import ServiceResolver
from .services import SERVICES


def _scheduler_database(backend: str) -> list[str]:
    """The database a persistent scheduler keeps its jobs in."""
    if backend == StorageBackends.MEMORY:
        return []
    return [f"{ComponentNames.DATABASE}[{backend}]"]


def _typed(name: str, axes: list[OptionSpec]) -> OptionSpec:
    """An older axis as ``init`` reads it (``template_generator``): one
    value in the brackets, its first axis's choice, where a Postgres
    provider stands alone for postgres (``database[neon]``)."""
    first = axes[0]
    choices = list(first.choices)
    if name == ComponentNames.DATABASE:
        choices += [p for p in PostgresProviders.ALL if p != PostgresProviders.DEFAULT]
    brings = _scheduler_database if name == ComponentNames.SCHEDULER else None
    return replace(first, choices=choices, auto_requires=brings)


TYPED_AXES = {name: _typed(name, axes) for name, axes in OLDER_AXES.items()}


class SelectionError(ValueError):
    """A selection ``init`` refuses: every rule it breaks, and the
    components that would satisfy its services where that is the fault."""

    def __init__(self, rules: list[str], missing: list[str] | None = None) -> None:
        super().__init__("; ".join(rules))
        self.rules = rules
        self.missing = missing or []


P = ParamSpec("P")
R = TypeVar("R")


def _refusing(check: Callable[P, R]) -> Callable[P, R]:
    """A check whose parsers' ``ValueError`` (``redis[``) is a refusal."""

    @functools.wraps(check)
    def refuse(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return check(*args, **kwargs)
        except SelectionError:
            raise
        except ValueError as e:
            raise SelectionError([str(e)]) from None

    return refuse


def project_name_rule(name: str) -> str | None:
    """The rule a project name breaks, if any."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return t("validation.invalid_name")
    if name.lower() in {"aegis", "aegis-stack"}:
        return t("validation.reserved_name", name=name)
    if len(name) > 50:
        return t("validation.name_too_long")
    return None


def typed_options(spec: PluginSpec) -> list[OptionSpec]:
    """What a part's brackets take, as ``init`` reads them."""
    axis = TYPED_AXES.get(spec.name)
    return [axis] if axis else list(spec.options)


def _as_typed(component: str) -> SimpleNamespace:
    """A known component, as ``parse_options`` reads its brackets."""
    spec = COMPONENTS[extract_base_component_name(component)]
    return SimpleNamespace(name=spec.name, options=typed_options(spec))


def merged(components: list[str], extra: list[str]) -> list[str]:
    """``components``, then each of ``extra`` whose part is not among them
    yet: the first form of a part wins, so an explicit
    ``database[postgres]`` beats a plain ``database`` required of it."""
    have = {extract_base_component_name(c) for c in components}
    out = list(components)
    for component in extra:
        base = extract_base_component_name(component)
        if base not in have:
            out.append(component)
            have.add(base)
    return out


def _scheduler_rule(parsed: dict[str, dict]) -> str | None:
    """A persistent scheduler keeps its jobs in the stack's database, so
    their engines must match (``neon`` is postgres)."""
    by_part = {extract_base_component_name(c): p for c, p in parsed.items()}
    backend = by_part.get(ComponentNames.SCHEDULER, {}).get("backend")
    engine = by_part.get(ComponentNames.DATABASE, {}).get("engine")
    if engine == PostgresProviders.NEON:
        engine = StorageBackends.POSTGRES
    if backend in (None, StorageBackends.MEMORY) or engine in (None, backend):
        return None
    return t("add.scheduler_db_engine_mismatch", backend=backend, engine=engine)


@_refusing
def check_components(value: str) -> list[str]:
    """``--components`` as ``init`` builds them: each one known, its
    brackets ones it takes, no two in conflict, and everything they bring
    added. Raises ``SelectionError``."""
    selected = split_bracket_list(value)
    if any(not c for c in selected):
        raise SelectionError([Messages.EMPTY_COMPONENT_NAME])
    errors = DependencyResolver.validate_components(clean_component_names(selected))
    parsed: dict[str, dict] = {}
    for component in selected:
        if extract_base_component_name(component) in COMPONENTS:
            try:
                parsed[component] = parse_options(component, _as_typed(component))
            except ValueError as e:
                errors.append(str(e))
    if not errors and (rule := _scheduler_rule(parsed)):
        errors.append(rule)
    if errors:
        raise SelectionError(errors)
    brought = [
        extra
        for component, values in parsed.items()
        for extra in compute_auto_requires(_as_typed(component), values)
    ]
    selected = merged(selected, brought)
    resolved = DependencyResolver.resolve_dependencies(clean_component_names(selected))
    return restore_engine_info(resolved, selected)


def split_services(value: str) -> list[str]:
    """Split a ``--services`` value on its top-level commas, dropping empties."""
    return [service for service in split_bracket_list(value) if service]


@_refusing
def check_services(value: str) -> list[str]:
    """``--services`` as ``init`` takes them (empty entries dropped): each
    one known, its options ones it offers, and the services it needs
    beside it. Raises ``SelectionError``."""
    selected = split_services(value)
    unknown = [s for s in selected if extract_base_service_name(s) not in SERVICES]
    if unknown:
        raise SelectionError(
            [
                t("validation.unknown_services", names=", ".join(unknown)),
                f"Available services: {', '.join(SERVICES)}",
            ]
        )
    errors = ServiceResolver.validate_services(selected)
    if errors:
        raise SelectionError(errors)
    return selected


def stack_components(components: list[str] | None, services: list[str]) -> list[str]:
    """The components ``init`` builds for checked services. With
    ``--components`` given, every component a service needs must be among
    them (``SelectionError`` names the rule and what would satisfy it);
    without, the services bring theirs."""
    needed, _ = ServiceResolver.resolve_service_dependencies(services)
    if components is None:
        return needed
    present = merged(components, CORE_COMPONENTS)
    errors = ServiceResolver.validate_service_component_compatibility(services, present)
    if errors:
        have = {extract_base_component_name(c) for c in present}
        missing = [c for c in needed if extract_base_component_name(c) not in have]
        raise SelectionError(errors, sorted(missing))
    return merged(components, needed)


def build_replay_command(
    project_name: str,
    components: list[str],
    services: list[str],
) -> str:
    """The uvx one-liner that reproduces this exact stack non-interactively.

    Selections carry their bracket syntax (``scheduler[sqlite]``,
    ``auth[rbac]``, ``ai[memory,pydantic-ai,public,rag]``), so feeding them
    back through ``--components``/``--services`` re-resolves to the same
    project. CORE components ship in every project and are dropped.
    """
    parts = [f"uvx aegis-stack init {project_name}"]
    # Name each part once, keeping its configured form: a list not built
    # by ``merged`` can hold database beside database[postgres].
    by_base: dict[str, str] = {}
    order: list[str] = []
    for comp in components:
        base = comp.split("[", 1)[0]
        if base in CORE_COMPONENTS:
            continue
        if base not in by_base:
            by_base[base] = comp
            order.append(base)
        elif "[" in comp and "[" not in by_base[base]:
            by_base[base] = comp
    non_core = [by_base[base] for base in order]
    # Quoted: bracket syntax is a glob pattern to zsh (and friends), so an
    # unquoted database[postgres] makes the shell error before uvx runs.
    if non_core:
        parts.append(f'--components "{",".join(non_core)}"')
    if services:
        parts.append(f'--services "{",".join(services)}"')
    parts.append("--no-interactive")
    return " ".join(parts)


def init_command_for(
    project_name: str, components: str | None, services: str | None
) -> str:
    """The ``init`` command that builds this selection, with every
    component it brings spelled out. Raises ``SelectionError`` with what
    ``init`` refuses."""
    rule = project_name_rule(project_name)
    if rule:
        raise SelectionError([rule])
    checked = check_components(components) if components else None
    checked_services = check_services(services) if services else []
    stack = (
        stack_components(checked, checked_services)
        if checked_services
        else checked or []
    )
    return build_replay_command(project_name, stack, checked_services)
