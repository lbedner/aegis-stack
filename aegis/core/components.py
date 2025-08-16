"""
Component registry and specifications for Aegis Stack.

This module defines all available components, their dependencies, and metadata
used for project generation and validation.
"""

from dataclasses import dataclass
from enum import Enum


class ComponentType(Enum):
    """Component type classifications."""

    CORE = "core"  # Always included (backend, frontend)
    INFRASTRUCTURE = "infra"  # Redis, workers - foundation for services to use


@dataclass
class ComponentSpec:
    """Specification for a single component."""

    name: str
    type: ComponentType
    description: str
    requires: list[str] | None = None  # Hard dependencies
    recommends: list[str] | None = None  # Soft dependencies
    conflicts: list[str] | None = None  # Mutual exclusions
    docker_services: list[str] | None = None
    pyproject_deps: list[str] | None = None
    template_files: list[str] | None = None

    def __post_init__(self) -> None:
        """Ensure all list fields are initialized."""
        if self.requires is None:
            self.requires = []
        if self.recommends is None:
            self.recommends = []
        if self.conflicts is None:
            self.conflicts = []
        if self.docker_services is None:
            self.docker_services = []
        if self.pyproject_deps is None:
            self.pyproject_deps = []
        if self.template_files is None:
            self.template_files = []


# Component registry - single source of truth
COMPONENTS: dict[str, ComponentSpec] = {
    "backend": ComponentSpec(
        name="backend",
        type=ComponentType.CORE,
        description="FastAPI backend server",
        pyproject_deps=["fastapi>=0.116.1", "uvicorn>=0.35.0"],
        template_files=["app/components/backend/"],
    ),
    "frontend": ComponentSpec(
        name="frontend",
        type=ComponentType.CORE,
        description="Flet frontend interface",
        pyproject_deps=["flet>=0.28.3"],
        template_files=["app/components/frontend/"],
    ),
    "redis": ComponentSpec(
        name="redis",
        type=ComponentType.INFRASTRUCTURE,
        description="Redis cache and message broker",
        docker_services=["redis"],
        pyproject_deps=["redis>=5.0.0"],
    ),
    "worker": ComponentSpec(
        name="worker",
        type=ComponentType.INFRASTRUCTURE,
        description="Background task processing infrastructure with arq",
        requires=["redis"],  # Hard dependency
        pyproject_deps=["arq>=0.25.0"],
        docker_services=["worker"],
        template_files=["app/components/worker/", "app/entrypoints/worker.py"],
    ),
    "scheduler": ComponentSpec(
        name="scheduler",
        type=ComponentType.INFRASTRUCTURE,
        description="Scheduled task execution infrastructure",
        pyproject_deps=["apscheduler>=3.10.0"],
        docker_services=["scheduler"],
        template_files=["app/components/scheduler.py", "app/entrypoints/scheduler.py"],
    ),
}


def get_component(name: str) -> ComponentSpec:
    """Get component specification by name."""
    if name not in COMPONENTS:
        raise ValueError(f"Unknown component: {name}")
    return COMPONENTS[name]


def get_components_by_type(component_type: ComponentType) -> dict[str, ComponentSpec]:
    """Get all components of a specific type."""
    return {
        name: spec for name, spec in COMPONENTS.items() if spec.type == component_type
    }


def list_available_components() -> list[str]:
    """Get list of all available component names."""
    return list(COMPONENTS.keys())
