"""Resolved build plan shared by quick and guided init flows.

``resolve_build_plan`` runs the full selection-to-plan pipeline (component
dependency resolution, service-required component merge, auto-add
accounting, template previews) as a pure computation. Quick mode prints the
plan as today's terminal dump; the guided setup renders it as the REVIEW
screen. One resolution path, two presentations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.component_utils import (
    clean_component_names,
    extract_base_component_name,
    restore_engine_info,
)
from ..core.components import COMPONENTS, CORE_COMPONENTS, ComponentType
from ..core.dependency_resolver import DependencyResolver
from ..core.selection import merged
from ..core.service_resolver import ServiceResolver
from ..core.template_generator import TemplateGenerator


@dataclass
class BuildPlan:
    """Everything both init flows need to preview and confirm a build."""

    project_name: str
    components: list[str]
    """Final component list (bracket syntax preserved, CORE included)."""

    services: list[str]
    """Final service list (bracket syntax preserved)."""

    scheduler_backend: str
    auto_added_components: list[str] = field(default_factory=list)
    """Components pulled in by component dependency resolution."""

    service_component_map: dict[str, list[str]] = field(default_factory=dict)
    """Component -> the services that required it (service auto-adds)."""

    template_gen: TemplateGenerator | None = None
    template_files: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    worker_queues: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def _of_type(self, component_type: ComponentType) -> list[str]:
        """Selected components of one type, selection order preserved."""
        out = []
        for name in self.components:
            base = extract_base_component_name(name)
            if base in COMPONENTS and COMPONENTS[base].type == component_type:
                out.append(name)
        return out

    @property
    def infrastructure(self) -> list[str]:
        """Infrastructure components for display.

        Excludes optional frontends: describing those as infrastructure is
        what :attr:`frontend` exists to avoid.
        """
        return self._of_type(ComponentType.INFRASTRUCTURE)

    @property
    def frontend(self) -> list[str]:
        """Optional frontend components for display (CORE Flet is not one)."""
        return self._of_type(ComponentType.FRONTEND)


def resolve_build_plan(
    project_name: str,
    selected_components: list[str],
    scheduler_backend: str,
    selected_services: list[str],
    python_version: str,
) -> BuildPlan:
    """Resolve a raw interactive selection into a confirmed-ready plan.

    Mirrors the long-standing init pipeline: resolve component
    dependencies on clean names, restore engine brackets, merge
    service-required components (base-name de-duplicated, first occurrence
    wins so an explicit ``database[postgres]`` beats the resolver's plain
    ``database``), then build the template previews.
    """
    components = list(selected_components)
    auto_added: list[str] = []

    if components:
        original = list(components)
        # Auto-adds are judged against the PRE-resolution selection; judging
        # the resolved set against itself always yields "nothing missing".
        auto_added = DependencyResolver.get_missing_dependencies(
            clean_component_names([c for c in original if c not in CORE_COMPONENTS])
        )
        resolved_clean = DependencyResolver.resolve_dependencies(
            clean_component_names(components)
        )
        components = restore_engine_info(resolved_clean, original)

    services = list(selected_services)
    service_component_map: dict[str, list[str]] = {}
    if services:
        # Base-name comparison throughout: a service's plain requirement
        # (database) must neither duplicate nor claim credit for an explicit
        # bracketed selection (database[postgres]).
        before_merge_bases = {extract_base_component_name(c) for c in components}
        service_components, _ = ServiceResolver.resolve_service_dependencies(services)

        components = merged(components, service_components)

        service_added = [
            comp
            for comp in service_components
            if extract_base_component_name(comp) not in before_merge_bases
            and comp not in CORE_COMPONENTS
        ]
        for service_name in services:
            service_deps = ServiceResolver.resolve_service_dependencies([service_name])[
                0
            ]
            for comp in service_deps:
                if comp in service_added:
                    service_component_map.setdefault(comp, []).append(service_name)

    template_gen = TemplateGenerator(
        project_name,
        list(components),
        scheduler_backend,
        services,
        python_version,
    )

    return BuildPlan(
        project_name=project_name,
        components=components,
        services=services,
        scheduler_backend=scheduler_backend,
        auto_added_components=auto_added,
        service_component_map=service_component_map,
        template_gen=template_gen,
        template_files=template_gen.get_template_files(),
        entrypoints=template_gen.get_entrypoints(),
        worker_queues=template_gen.get_worker_queues(),
        dependencies=template_gen._get_pyproject_deps(),
    )
